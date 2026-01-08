from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit
from decouple import config
from .services import (
    search_google_maps, find_cnpj_by_name, enrich_company_viper, 
    get_partners_internal_queued, filter_existing_leads, search_cpf_viper, search_cnpj_viper,
    normalize_niche, normalize_location, get_cached_search, create_cached_search, get_leads_from_cache, search_incremental,
    wait_for_partners_processing, process_search_async, sanitize_lead_data
)
import threading
from .models import Lead, Search, UserProfile, ViperRequestQueue, CachedSearch, NormalizedNiche, NormalizedLocation
from .credit_service import debit_credits, check_credits
from .stripe_service import create_checkout_session, create_custom_checkout_session, handle_webhook_event, CREDIT_PACKAGES, CREDIT_PRICE, MIN_CREDITS, MAX_CREDITS
from .decorators import require_user_profile, validate_user_ownership
import csv
import json
import logging

logger = logging.getLogger(__name__)


def has_valid_partners_data(lead):
    """
    Verifica se um Lead já possui dados válidos de sócios (QSA) salvos.
    Aceita múltiplos formatos de dados:
    - Dict com chave 'socios': {'socios': [...]}
    - Lista direta: [...]
    - Dict vazio ou None: não tem dados válidos
    
    Args:
        lead: Objeto Lead
    
    Returns:
        bool: True se tem dados válidos, False caso contrário
    """
    if not lead or not lead.viper_data:
        return False
    
    socios_qsa = lead.viper_data.get('socios_qsa')
    
    # Se não tem socios_qsa, não tem dados
    if not socios_qsa:
        return False
    
    # Caso 1: É uma lista diretamente (formato alternativo da API)
    if isinstance(socios_qsa, list):
        return len(socios_qsa) > 0
    
    # Caso 2: É um dict com chave 'socios'
    if isinstance(socios_qsa, dict):
        socios = socios_qsa.get('socios')
        # Pode ser lista ou None
        if isinstance(socios, list):
            return len(socios) > 0
        # Se tem outras chaves mas não 'socios', considerar inválido
        return False
    
    # Qualquer outro formato é inválido
    return False


def login_view(request):
    """
    Página de login usando Supabase Auth.
    """
    # Se já estiver autenticado, redirecionar para dashboard
    user_profile = getattr(request, 'user_profile', None)
    if user_profile:
        return redirect('dashboard')
    
    next_url = request.GET.get('next', '/')
    context = {
        'supabase_url': config('SUPABASE_URL', default=''),
        'supabase_key': config('SUPABASE_KEY', default=''),
        'next_url': next_url,
    }
    return render(request, 'lead_extractor/login.html', context)


def logout_view(request):
    """
    Faz logout do usuário.
    """
    # Limpar cookies (o front-end também vai fazer isso, mas garantimos aqui)
    response = redirect('login')
    response.delete_cookie('sb-access-token')
    response.delete_cookie('sb-refresh-token')
    response.delete_cookie('supabase-auth-token')
    return response


@ratelimit(key='ip', rate='100/m', method='GET', block=True)  # 100 requisições por minuto por IP
@ratelimit(key='ip', rate='20/m', method='POST', block=True)  # 20 requisições POST por minuto por IP
@require_user_profile
def dashboard(request):
    """
    Dashboard principal para busca de leads.
    Garante que leads salvos sejam apenas do usuário.
    """
    user_profile = request.user_profile
    
    # Middleware já garante que user_profile existe, mas verificamos por segurança
    if not user_profile:
        return redirect('login')
    
    results = []
    search_term = ""
    niche = ""
    location = ""
    quantity = 10  # Default
    
    try:
        if request.method == "POST" and user_profile:
            niche = request.POST.get('niche', '').strip()
            location = request.POST.get('location', '').strip()
            quantity = int(request.POST.get('quantity', 10))
            
            if not niche or not location:
                messages.error(request, 'Por favor, preencha o nicho e a localização.')
            else:
                # Construir query combinada
                search_term = f"{niche} em {location}"
                
                # Verificar créditos
                available_credits = check_credits(user_profile)
                if available_credits < quantity:
                    messages.warning(request, f'Você tem apenas {available_credits} créditos disponíveis. Ajustando quantidade.')
                    quantity = available_credits
                
                if quantity <= 0:
                    messages.error(request, 'Você não tem créditos suficientes para realizar a busca.')
                else:
                    # Normalizar entrada
                    niche_normalized = normalize_niche(niche)
                    location_normalized = normalize_location(location)
                    
                    cached_search = None
                    use_cache = False
                    
                    # Tentar buscar do cache se normalização funcionou
                    if niche_normalized and location_normalized:
                        cached_search = get_cached_search(niche_normalized, location_normalized)
                        if cached_search and cached_search.total_leads_cached >= quantity:
                            # Cache tem leads suficientes
                            use_cache = True
                    
                    # Criar objeto Search com status 'processing' para processamento assíncrono
                    search_obj = Search.objects.create(
                        user=user_profile,
                        niche=niche,
                        location=location,
                        quantity_requested=quantity,
                        cached_search=cached_search if use_cache else None,
                        status='processing',
                        processing_started_at=timezone.now(),
                        search_data={
                            'query': search_term,
                            'from_cache': use_cache,
                        }
                    )
                    
                    # Iniciar processamento em background
                    thread = threading.Thread(target=process_search_async, args=(search_obj.id,))
                    thread.daemon = True
                    thread.start()
                    
                    messages.info(request, f'Sua busca está sendo processada. Você pode sair desta página e verificar os resultados em "Base de Dados" em alguns instantes.')
    
    except Exception as e:
        logger.error(f"Erro ao processar busca no dashboard: {e}", exc_info=True)
        messages.error(request, f'Erro ao processar busca: {str(e)}')
    
    # Buscar créditos disponíveis
    available_credits = check_credits(user_profile) if user_profile else 0
    
    # Calcular métricas para o dashboard
    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    leads_today = Lead.objects.filter(
        user=user_profile,
        created_at__gte=today
    ).count() if user_profile else 0
    
    searches_today = Search.objects.filter(
        user=user_profile,
        created_at__gte=today
    ).count() if user_profile else 0
    
    context = {
        'results': results,
        'search_term': search_term,
        'niche': niche,
        'location': location,
        'quantity': quantity,
        'available_credits': available_credits,
        'leads_today': leads_today,
        'searches_today': searches_today,
        'user_profile': user_profile,
    }
    
    return render(request, 'lead_extractor/dashboard.html', context)

@ratelimit(key='user', rate='10/m', method='GET', block=True)  # 10 exportações por minuto por usuário
@require_user_profile
def export_leads_csv(request, search_id=None):
    """
    Exporta leads para CSV.
    Se search_id for fornecido, exporta apenas os leads daquela pesquisa.
    Garantimos que apenas leads do usuário sejam exportados.
    """
    user_profile = request.user_profile
    
    # Validar ownership se search_id fornecido
    if search_id:
        try:
            search_obj = Search.objects.get(id=search_id, user=user_profile)
        except Search.DoesNotExist:
            logger.warning(f"Tentativa de acesso não autorizado: usuário {user_profile.email} tentou exportar pesquisa {search_id}")
            messages.error(request, 'Pesquisa não encontrada ou você não tem permissão para acessá-la.')
            return redirect('dashboard')
    
    # Log de auditoria para exportação
    logger.info(f"Exportação CSV iniciada por {user_profile.email} (search_id: {search_id})")
    
    response = HttpResponse(content_type='text/csv')
    filename = f"leads_exportados_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    # Cabeçalho organizado
    writer.writerow(['Empresa', 'CNPJ', 'Telefone (Maps)', 'Telefones (Viper)', 'Emails', 'Sócios / Decisores', 'Endereço (Maps)', 'Endereço (Fiscal)'])

    # Filtrar leads do usuário (garantindo ownership)
    # Usar select_related para evitar N+1 queries em search e cached_search
    # Nota: viper_data é necessário para exportação, então não usamos defer aqui
    leads = Lead.objects.filter(user=user_profile).select_related('search', 'cached_search').order_by('-created_at')
    
    # Se search_id fornecido, filtrar por pesquisa (já validado acima)
    is_last_search = False
    if search_id:
        leads = leads.filter(search=search_obj)
        
        # Verificar se é a última pesquisa (mais recente)
        last_search = Search.objects.filter(user=user_profile).order_by('-created_at').first()
        if last_search and last_search.id == search_id:
            is_last_search = True

    for lead in leads:
        viper = lead.viper_data or {}
        
        # Exportar dados enriquecidos apenas se estiverem disponíveis (usuário pagou para ver)
        # 1. Telefones Viper
        phones_list = viper.get('telefones', [])
        phones_str = " | ".join([str(p) for p in phones_list if p]) if phones_list else ""
        
        # 2. Emails
        emails_list = viper.get('emails', [])
        emails_str = " | ".join([str(e) for e in emails_list if e]) if emails_list else ""
        
        # 3. Sócios (incluir nome, cargo e CPF se disponível)
        socios_str = ""
        qsa = viper.get('socios_qsa')
        if qsa and isinstance(qsa, dict) and 'socios' in qsa:
            lista_socios = qsa['socios']
            socios_info = []
            for s in lista_socios:
                nome = s.get('NOME') or s.get('nome', '')
                cargo = s.get('CARGO') or s.get('qualificacao') or 'Sócio'
                cpf = s.get('DOCUMENTO') or s.get('CPF') or s.get('cpf', '')
                
                socio_text = f"{nome} ({cargo})"
                if cpf:
                    socio_text += f" - CPF: {cpf}"
                
                # Se tem dados de CPF enriquecidos, incluir telefones e emails
                if s.get('cpf_enriched') and s.get('cpf_data'):
                    cpf_data = s.get('cpf_data', {})
                    # API Viper retorna telefones_fixos, telefones_moveis e emails
                    telefones_cpf = [t for t in (cpf_data.get('telefones_fixos', []) + cpf_data.get('telefones_moveis', []) + cpf_data.get('whatsapps', [])) if t]
                    emails_cpf = [e for e in cpf_data.get('emails', []) if e]
                    
                    if telefones_cpf:
                        socio_text += f" - Tel: {' | '.join(telefones_cpf)}"
                    if emails_cpf:
                        socio_text += f" - Email: {' | '.join(emails_cpf)}"
                
                socios_info.append(socio_text)
            socios_str = " || ".join(socios_info)

        # 4. Endereço Fiscal (Viper)
        endereco_fiscal_str = ""
        lista_ends = viper.get('enderecos', [])
        if lista_ends and len(lista_ends) > 0:
            end = lista_ends[0]
            logradouro = end.get('LOGRADOURO') or end.get('logradouro') or ''
            numero = end.get('NUMERO') or end.get('numero') or ''
            bairro = end.get('BAIRRO') or end.get('bairro') or ''
            cidade = end.get('CIDADE') or end.get('cidade') or ''
            uf = end.get('UF') or end.get('uf') or ''
            endereco_fiscal_str = f"{logradouro}, {numero} - {bairro}, {cidade}/{uf}"

        writer.writerow([
            lead.name,
            lead.cnpj,
            lead.phone_maps or "",
            phones_str,
            emails_str,
            socios_str,
            lead.address or "", # Endereço do Maps
            endereco_fiscal_str # Endereço do CNPJ
        ])

    # Log de auditoria para conclusão de exportação
    logger.info(f"[AUDITORIA] Exportação CSV concluída por {user_profile.email} (user_id: {user_profile.id}, leads_exportados: {leads_count})")
    
    return response


@require_user_profile
def simple_search(request):
    """
    Página de busca rápida por CPF/CNPJ.
    """
    user_profile = getattr(request, 'user_profile', None)
    if not user_profile:
        return redirect('login')
    available_credits = check_credits(user_profile)
    
    context = {
        'user_profile': user_profile,
        'available_credits': available_credits,
    }
    
    return render(request, 'lead_extractor/simple_search.html', context)


@require_user_profile
def search_by_cpf(request):
    """
    Busca dados por CPF usando API Viper.
    - Se for requisição AJAX (header X-Requested-With ou Accept: application/json): retorna JSON
    - Se for requisição de formulário HTML: renderiza template com resultado
    """
    user_profile = request.user_profile
    
    # Detectar se é requisição AJAX
    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        'application/json' in request.headers.get('Accept', '') or
        request.content_type == 'application/json'
    )
    
    if request.method == 'POST':
        cpf = request.POST.get('cpf', '').strip()
        
        if not cpf:
            if is_ajax:
                return JsonResponse({'error': 'CPF não fornecido'}, status=400)
            messages.error(request, 'CPF não fornecido')
            return redirect('simple_search')
        
        # Verificar créditos
        available_credits = check_credits(user_profile)
        if available_credits < 1:
            if is_ajax:
                return JsonResponse({'error': 'Créditos insuficientes'}, status=402)
            messages.error(request, 'Créditos insuficientes')
            return redirect('simple_search')
        
        # Buscar dados do CPF
        data = search_cpf_viper(cpf)
        
        if data:
            # Debitar crédito
            success, new_balance, error = debit_credits(
                user_profile,
                1,
                description=f"Busca por CPF: {cpf}"
            )
            
            if success:
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'data': data,
                        'credits_remaining': new_balance
                    })
                # Renderizar template com resultado
                return render(request, 'lead_extractor/cpf_result.html', {
                    'data': data,
                    'cpf': cpf,
                    'credits_remaining': new_balance
                })
            else:
                if is_ajax:
                    return JsonResponse({'error': f'Erro ao debitar crédito: {error}'}, status=500)
                messages.error(request, f'Erro ao debitar crédito: {error}')
                return redirect('simple_search')
        else:
            if is_ajax:
                return JsonResponse({'error': 'CPF não encontrado ou erro na busca'}, status=404)
            messages.error(request, 'CPF não encontrado ou erro na busca')
            return redirect('simple_search')
    
    if is_ajax:
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    return redirect('simple_search')


@require_user_profile
def search_by_cnpj(request):
    """
    Busca dados por CNPJ usando API Viper.
    """
    user_profile = request.user_profile
    
    if request.method == 'POST':
        cnpj = request.POST.get('cnpj', '').strip()
        
        if not cnpj:
            messages.error(request, 'CNPJ não fornecido')
            return redirect('simple_search')
        
        # Verificar créditos
        available_credits = check_credits(user_profile)
        if available_credits < 1:
            messages.error(request, 'Créditos insuficientes')
            return redirect('simple_search')
        
        # Buscar dados do CNPJ
        data = search_cnpj_viper(cnpj)
        
        if data:
            # Buscar sócios também usando FILA (síncrono)
            queue_result = get_partners_internal_queued(cnpj, user_profile)
            queue_id = queue_result.get('queue_id')
            is_new = queue_result.get('is_new', True)
            
            if not is_new:
                logger.info(f"Reutilizando requisição existente para CNPJ {cnpj}, queue_id: {queue_id}")
            
            # Aguardar processamento (com timeout)
            if queue_id:
                partners_data = wait_for_partners_processing(queue_id, user_profile, timeout=60)
                if partners_data:
                    data['socios_qsa'] = partners_data
            
            # Debitar crédito
            success, new_balance, error = debit_credits(
                user_profile,
                1,
                description=f"Busca por CNPJ: {cnpj}"
            )
            
            if success:
                messages.success(request, 'Busca realizada com sucesso!')
                context = {
                    'cnpj': cnpj,
                    'data': data,
                    'user_profile': user_profile,
                    'available_credits': new_balance,
                }
                return render(request, 'lead_extractor/cnpj_result.html', context)
            else:
                messages.error(request, f'Erro ao debitar crédito: {error}')
        else:
            messages.error(request, 'CNPJ não encontrado ou erro na busca')
    
    return redirect('simple_search')


@require_user_profile
@require_POST
@validate_user_ownership(Search, lookup_field='user')
def delete_search(request, search_id, **kwargs):
    """
    Deleta uma pesquisa e seus leads associados.
    O decorator validate_user_ownership já valida a propriedade e adiciona search_obj aos kwargs.
    """
    try:
        # O decorator já valida e adiciona search_obj aos kwargs
        search = kwargs.get('search_obj')
        if not search:
            search = Search.objects.get(id=search_id, user=request.user_profile)
        # Log de auditoria para exclusão
        logger.info(f"[AUDITORIA] Pesquisa {search_id} excluída por {request.user_profile.email} (user_id: {request.user_profile.id})")
        search.delete()  # Isso também deleta os leads associados devido ao CASCADE
        return JsonResponse({'success': True, 'message': 'Pesquisa excluída com sucesso.'})
    except Search.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Pesquisa não encontrada.'}, status=404)
    except Exception as e:
        logger.error(f"Erro ao deletar pesquisa {search_id}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': f'Erro ao excluir pesquisa: {str(e)}'}, status=500)

@require_user_profile
@ensure_csrf_cookie
def search_history(request):
    """
    Visualiza pesquisas antigas do usuário.
    Garante que apenas pesquisas do usuário sejam exibidas.
    Dados sensíveis são escondidos exceto na última pesquisa.
    """
    user_profile = request.user_profile
    
    # Garantir que apenas pesquisas do usuário sejam listadas
    searches = Search.objects.filter(user=user_profile).select_related('user', 'cached_search').prefetch_related('leads').order_by('-created_at')
    
    # Identificar última pesquisa (mais recente)
    last_search_id = None
    if searches.exists():
        last_search_id = searches.first().id
    
    # Paginação
    paginator = Paginator(searches, 20)  # 20 por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'searches': page_obj,
        'last_search_id': last_search_id,
        'user_profile': user_profile,
        'available_credits': check_credits(user_profile),
    }
    
    return render(request, 'lead_extractor/search_history.html', context)


@require_user_profile
def purchase_credits(request):
    """
    Página para comprar créditos.
    """
    user_profile = request.user_profile
    
    context = {
        'user_profile': user_profile,
        'available_credits': check_credits(user_profile),
        'packages': CREDIT_PACKAGES,
        'CREDIT_PRICE': CREDIT_PRICE,
        'MIN_CREDITS': MIN_CREDITS,
        'MAX_CREDITS': MAX_CREDITS,
    }
    
    return render(request, 'lead_extractor/purchase_credits.html', context)


@require_user_profile
def create_checkout(request):
    """
    Cria sessão de checkout do Stripe.
    """
    user_profile = request.user_profile
    
    if request.method == 'POST':
        package_id = request.POST.get('package_id')
        
        if not package_id:
            return JsonResponse({'error': 'Pacote não fornecido'}, status=400)
        
        try:
            package_id = int(package_id)
            logger.info(f"Criando checkout para usuário {user_profile.email}, pacote {package_id}")
            session = create_checkout_session(package_id, user_profile.id, user_profile.email)
            
            if session:
                logger.info(f"Checkout criado com sucesso: {session.id}")
                return JsonResponse({'session_id': session.id, 'url': session.url})
            else:
                logger.error(f"Erro ao criar checkout: função retornou None")
                return JsonResponse({'error': 'Erro ao criar sessão de checkout'}, status=500)
                
        except ValueError as e:
            logger.error(f"Erro de valor ao criar checkout: {e}")
            return JsonResponse({'error': 'ID de pacote inválido'}, status=400)
        except Exception as e:
            logger.error(f"Erro inesperado ao criar checkout: {e}", exc_info=True)
            return JsonResponse({'error': f'Erro ao criar checkout: {str(e)}'}, status=500)
    
    return JsonResponse({'error': 'Método não permitido'}, status=405)


@require_user_profile
def create_custom_checkout(request):
    """
    Cria sessão de checkout customizada do Stripe para quantidade personalizada de créditos.
    """
    user_profile = request.user_profile
    
    if request.method == 'POST':
        try:
            credits = int(request.POST.get('credits', 0))
            logger.info(f"Criando checkout customizado para usuário {user_profile.email}, {credits} créditos")
            
            if credits < MIN_CREDITS or credits > MAX_CREDITS:
                logger.warning(f"Quantidade de créditos inválida: {credits}")
                return JsonResponse({
                    'error': f'Quantidade de créditos deve estar entre {MIN_CREDITS} e {MAX_CREDITS}'
                }, status=400)
            
            session = create_custom_checkout_session(credits, user_profile.id, user_profile.email)
            
            if session:
                logger.info(f"Checkout customizado criado com sucesso: {session.id}")
                return JsonResponse({'session_id': session.id, 'url': session.url})
            else:
                logger.error(f"Erro ao criar checkout customizado: função retornou None")
                return JsonResponse({'error': 'Erro ao criar sessão de checkout'}, status=500)
                
        except ValueError as e:
            logger.error(f"Erro de valor ao criar checkout customizado: {e}")
            return JsonResponse({'error': 'Quantidade de créditos inválida'}, status=400)
        except Exception as e:
            logger.error(f"Erro inesperado ao criar checkout customizado: {e}", exc_info=True)
            return JsonResponse({'error': f'Erro ao criar checkout: {str(e)}'}, status=500)
    
    return JsonResponse({'error': 'Método não permitido'}, status=405)


@csrf_exempt
def stripe_webhook(request):
    """
    Endpoint para receber webhooks do Stripe.
    """
    import stripe
    
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    webhook_secret = config('STRIPE_WEBHOOK_SECRET', default='')
    
    logger.info("Webhook do Stripe recebido")
    
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET não está configurada")
        return HttpResponse(status=500)
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        logger.info(f"Evento do Stripe verificado: {event['type']} (ID: {event['id']})")
    except ValueError as e:
        logger.error(f"Erro ao decodificar payload do webhook: {e}")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Erro na verificação da assinatura do webhook: {e}")
        return HttpResponse(status=400)
    
    # Processar evento
    try:
        result = handle_webhook_event(event)
        if result:
            logger.info(f"Evento {event['type']} processado com sucesso")
            return HttpResponse(status=200)
        else:
            logger.error(f"Falha ao processar evento {event['type']}")
            return HttpResponse(status=500)
    except Exception as e:
        logger.error(f"Erro inesperado ao processar webhook: {e}", exc_info=True)
        return HttpResponse(status=500)


@require_user_profile
def payment_success(request):
    """
    Página de sucesso após pagamento.
    """
    user_profile = request.user_profile
    session_id = request.GET.get('session_id')
    
    context = {
        'user_profile': user_profile,
        'available_credits': check_credits(user_profile) if user_profile else 0,
        'session_id': session_id,
    }
    
    return render(request, 'lead_extractor/payment_success.html', context)


@require_user_profile
def viper_queue_status(request, queue_id):
    """
    Retorna status de uma requisição na fila do Viper.
    Valida ownership para garantir que usuário só acessa suas próprias requisições.
    """
    user_profile = request.user_profile
    
    try:
        queue_item = ViperRequestQueue.objects.get(id=queue_id, user=user_profile)
        
        response_data = {
            'status': queue_item.status,
            'queue_id': queue_item.id,
            'created_at': queue_item.created_at.isoformat(),
        }
        
        if queue_item.status == 'completed':
            response_data['result'] = queue_item.result_data
            response_data['completed_at'] = queue_item.completed_at.isoformat() if queue_item.completed_at else None
        elif queue_item.status == 'failed':
            response_data['error'] = queue_item.error_message
            response_data['completed_at'] = queue_item.completed_at.isoformat() if queue_item.completed_at else None
        elif queue_item.status == 'processing':
            response_data['started_at'] = queue_item.started_at.isoformat() if queue_item.started_at else None
        
        return JsonResponse(response_data)
        
    except ViperRequestQueue.DoesNotExist:
        return JsonResponse({'error': 'Requisição não encontrada'}, status=404)


@require_user_profile
def get_viper_result(request, queue_id):
    """
    Busca resultado de uma requisição processada na fila do Viper.
    Valida ownership para garantir que usuário só acessa suas próprias requisições.
    """
    user_profile = request.user_profile
    
    try:
        queue_item = ViperRequestQueue.objects.get(id=queue_id, user=user_profile)
        
        # Log de auditoria para acesso a dados sensíveis
        logger.info(f"[AUDITORIA] Acesso a resultado Viper (queue_id: {queue_id}) por {user_profile.email} (user_id: {user_profile.id})")
        
        if queue_item.status == 'completed':
            # result_data já contém apenas dados de sócios (normalizados)
            # Não precisa sanitizar pois usuário já pagou créditos para ver
            return JsonResponse({
                'status': 'completed',
                'result': queue_item.result_data
            })
        elif queue_item.status == 'failed':
            return JsonResponse({
                'status': 'failed',
                'error': queue_item.error_message
            }, status=400)
        else:
            # Ainda processando ou pendente
            return JsonResponse({
                'status': queue_item.status,
                'message': 'Requisição ainda sendo processada'
            }, status=202)  # 202 Accepted
        
    except ViperRequestQueue.DoesNotExist:
        return JsonResponse({'error': 'Requisição não encontrada'}, status=404)


@require_user_profile
def api_autocomplete_niches(request):
    """
    Endpoint de autocomplete para nichos.
    GET /api/autocomplete/niches/?q=adv
    """
    q = request.GET.get('q', '').strip()
    
    if not q:
        return JsonResponse({'results': []})
    
    try:
        # Buscar nichos que começam com a query (case insensitive)
        niches = NormalizedNiche.objects.filter(
            display_name__icontains=q,
            is_active=True
        ).order_by('display_name')[:20]
        
        results = [{'value': niche.display_name, 'display': niche.display_name} for niche in niches]
        
        return JsonResponse({'results': results})
    except Exception as e:
        logger.error(f"Erro ao buscar nichos para autocomplete: {e}", exc_info=True)
        return JsonResponse({'results': []})


@require_user_profile
def api_autocomplete_locations(request):
    """
    Endpoint de autocomplete para localizações (cidades).
    GET /api/autocomplete/locations/?q=são
    """
    q = request.GET.get('q', '').strip()
    
    if not q:
        return JsonResponse({'results': []})
    
    try:
        # Buscar cidades que começam com a query (case insensitive)
        # Formato esperado: "Cidade - UF"
        locations = NormalizedLocation.objects.filter(
            display_name__icontains=q,
            is_active=True
        ).order_by('state', 'city')[:20]
        
        results = [{'value': loc.display_name, 'display': loc.display_name} for loc in locations]
        
        return JsonResponse({'results': results})
    except Exception as e:
        logger.error(f"Erro ao buscar localizações para autocomplete: {e}", exc_info=True)
        return JsonResponse({'results': []})


@require_user_profile
def api_search_status(request, search_id):
    """
    Endpoint para verificar status de uma busca.
    GET /api/search/<int:search_id>/status/
    """
    user_profile = request.user_profile
    
    try:
        search_obj = Search.objects.get(id=search_id, user=user_profile)
        
        return JsonResponse({
            'status': search_obj.status,
            'results_count': search_obj.results_count,
            'credits_used': search_obj.credits_used,
            'processing_started_at': search_obj.processing_started_at.isoformat() if search_obj.processing_started_at else None,
            'created_at': search_obj.created_at.isoformat(),
        })
    except Search.DoesNotExist:
        return JsonResponse({'error': 'Pesquisa não encontrada'}, status=404)


@ratelimit(key='user', rate='30/m', method='POST', block=True)  # 30 requisições por minuto por usuário
@require_user_profile
def enrich_leads(request, search_id):
    """
    Enriquece leads selecionados de uma pesquisa.
    POST /search/<int:search_id>/enrich/
    Body: {'lead_ids': [1, 2, 3]}
    """
    user_profile = request.user_profile
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    try:
        # Validar que a pesquisa pertence ao usuário
        search_obj = Search.objects.get(id=search_id, user=user_profile)
        
        # Obter IDs dos leads a enriquecer
        data = json.loads(request.body) if request.body else {}
        lead_ids = data.get('lead_ids', [])
        
        if not lead_ids:
            return JsonResponse({'error': 'Nenhum lead selecionado'}, status=400)
        
        # Validar créditos suficientes
        available_credits = check_credits(user_profile)
        if available_credits < len(lead_ids):
            return JsonResponse({
                'error': f'Créditos insuficientes. Necessário: {len(lead_ids)}, Disponível: {available_credits}'
            }, status=402)
        
        # Buscar leads (apenas do usuário e da pesquisa)
        leads_to_enrich = Lead.objects.filter(
            id__in=lead_ids,
            user=user_profile,
            search=search_obj
        )
        
        if leads_to_enrich.count() != len(lead_ids):
            return JsonResponse({'error': 'Alguns leads não foram encontrados ou não pertencem a esta pesquisa'}, status=400)
        
        credits_used = 0
        enriched_count = 0
        
        # Processar cada lead
        for lead in leads_to_enrich:
            if not lead.cnpj:
                continue
            
            # Buscar dados faltantes
            public_data = enrich_company_viper(lead.cnpj)
            if public_data:
                # Atualizar viper_data com novos dados
                if not lead.viper_data:
                    lead.viper_data = {}
                
                # Adicionar telefones e emails se não existirem
                if 'telefones' in public_data and public_data['telefones']:
                    if 'telefones' not in lead.viper_data or not lead.viper_data['telefones']:
                        lead.viper_data['telefones'] = public_data['telefones']
                
                if 'emails' in public_data and public_data['emails']:
                    if 'emails' not in lead.viper_data or not lead.viper_data['emails']:
                        lead.viper_data['emails'] = public_data['emails']
                
                # Buscar sócios se não existirem
                if 'socios_qsa' not in lead.viper_data or not lead.viper_data.get('socios_qsa'):
                    # Enfileirar busca de sócios (sem aguardar)
                    queue_result = get_partners_internal_queued(lead.cnpj, user_profile, lead=lead)
                    if not queue_result.get('is_new', True):
                        logger.info(f"Reutilizando requisição existente para Lead {lead.id} (CNPJ: {lead.cnpj})")
            
            # Debitar crédito
            success, new_balance, error = debit_credits(
                user_profile,
                1,
                description=f"Enriquecimento: {lead.name}"
            )
            
            if success:
                lead.save(update_fields=['viper_data'])
                credits_used += 1
                enriched_count += 1
            else:
                logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")
        
        return JsonResponse({
            'success': True,
            'enriched_count': enriched_count,
            'credits_used': credits_used,
            'message': f'{enriched_count} lead(s) enriquecido(s) com sucesso'
        })
        
    except Search.DoesNotExist:
        return JsonResponse({'error': 'Pesquisa não encontrada'}, status=404)
    except Exception as e:
        logger.error(f"Erro ao enriquecer leads: {e}", exc_info=True)
        return JsonResponse({'error': f'Erro ao enriquecer leads: {str(e)}'}, status=500)


@ratelimit(key='user', rate='30/m', method='POST', block=True)  # 30 requisições por minuto por usuário
@require_user_profile
def search_partners(request, search_id):
    """
    Busca sócios (QSA) para empresas selecionadas de uma pesquisa.
    IMPORTANTE: Sempre debita créditos, mesmo se dados já existirem no banco.
    POST /search/<int:search_id>/partners/
    Body: {'lead_ids': [1, 2, 3]}
    Valida ownership da pesquisa e dos leads.
    """
    user_profile = request.user_profile
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    try:
        # Validar que a pesquisa pertence ao usuário
        search_obj = Search.objects.get(id=search_id, user=user_profile)
        
        # Obter IDs dos leads
        data = json.loads(request.body) if request.body else {}
        lead_ids = data.get('lead_ids', [])
        
        if not lead_ids:
            return JsonResponse({'error': 'Nenhum lead selecionado'}, status=400)
        
        # Validar créditos suficientes (1 crédito por empresa)
        available_credits = check_credits(user_profile)
        if available_credits < len(lead_ids):
            return JsonResponse({
                'error': f'Créditos insuficientes. Necessário: {len(lead_ids)}, Disponível: {available_credits}'
            }, status=402)
        
        # Buscar leads (apenas do usuário e da pesquisa)
        leads_to_process = Lead.objects.filter(
            id__in=lead_ids,
            user=user_profile,
            search=search_obj
        )
        
        if leads_to_process.count() != len(lead_ids):
            return JsonResponse({
                'error': 'Alguns leads não foram encontrados ou não pertencem a esta pesquisa'
            }, status=400)
        
        results = []
        credits_debited = 0
        errors = []
        
        for lead in leads_to_process:
            try:
                # IMPORTANTE: Debitar crédito ANTES de buscar/exibir sócios
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Sócios (QSA) para {lead.name} (CNPJ: {lead.cnpj})"
                )
                
                if not success:
                    errors.append(f"Erro ao debitar crédito para {lead.name}: {error}")
                    continue
                
                credits_debited += 1
                
                # Verificar se já tem sócios salvos no banco (usando função helper robusta)
                has_partners = has_valid_partners_data(lead)
                
                if has_partners:
                    # Dados já existem - usar dados salvos (não fazer nova requisição à API)
                    logger.info(f"Usando dados de sócios já salvos para Lead {lead.id} (CNPJ: {lead.cnpj}) - não será enfileirado")
                else:
                    # Dados não existem - buscar via API (mas não aguardar - processar em background)
                    if not lead.cnpj:
                        errors.append(f"Lead {lead.name} não possui CNPJ")
                        continue
                    
                    # Enfileirar busca de sócios (processamento assíncrono)
                    queue_result = get_partners_internal_queued(lead.cnpj, user_profile, lead=lead)
                    queue_id = queue_result.get('queue_id')
                    is_new = queue_result.get('is_new', True)
                    
                    if not queue_id:
                        errors.append(f"Erro ao enfileirar busca de sócios para {lead.name}")
                        continue
                    
                    # Não aguardar - os dados serão processados pela fila
                    # O usuário pode recarregar a página depois para ver os resultados
                    if is_new:
                        logger.info(f"Busca de sócios enfileirada para Lead {lead.id} (CNPJ: {lead.cnpj}), queue_id: {queue_id}")
                    else:
                        logger.info(f"Reutilizando requisição existente para Lead {lead.id} (CNPJ: {lead.cnpj}), queue_id: {queue_id}")
                
                # Recarregar Lead para pegar dados atualizados (se já existirem)
                lead.refresh_from_db()
                
                results.append({
                    'lead_id': lead.id,
                    'name': lead.name,
                    'cnpj': lead.cnpj,
                    'partners': lead.viper_data.get('socios_qsa', {}) if lead.viper_data else {},
                    'processed': has_partners  # Indica se já tinha dados ou foi enfileirado
                })
                
            except Exception as e:
                logger.error(f"Erro ao processar lead {lead.id}: {e}", exc_info=True)
                errors.append(f"Erro ao processar {lead.name}: {str(e)}")
        
        return JsonResponse({
            'success': True,
            'processed': len(results),
            'credits_debited': credits_debited,
            'results': results,
            'errors': errors if errors else None
        })
        
    except Search.DoesNotExist:
        return JsonResponse({'error': 'Pesquisa não encontrada'}, status=404)
    except Exception as e:
        logger.error(f"Erro ao buscar sócios: {e}", exc_info=True)
        return JsonResponse({'error': f'Erro ao buscar sócios: {str(e)}'}, status=500)


@require_user_profile
def search_cpf_batch(request):
    """
    Busca dados de CPF em lote para sócios selecionados.
    IMPORTANTE: Sempre debita créditos, mesmo se dados já existirem no banco.
    POST /search/cpf/batch/
    Body: {'cpfs': [{'lead_id': 1, 'cpf': '12345678900', 'socio_name': 'João Silva'}, ...]}
    """
    user_profile = request.user_profile
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    try:
        # Obter lista de CPFs
        data = json.loads(request.body) if request.body else {}
        cpfs_data = data.get('cpfs', [])
        
        if not cpfs_data:
            return JsonResponse({'error': 'Nenhum CPF fornecido'}, status=400)
        
        # Validar créditos suficientes (1 crédito por CPF)
        available_credits = check_credits(user_profile)
        if available_credits < len(cpfs_data):
            return JsonResponse({
                'error': f'Créditos insuficientes. Necessário: {len(cpfs_data)}, Disponível: {available_credits}'
            }, status=402)
        
        results = []
        credits_debited = 0
        errors = []
        
        for cpf_item in cpfs_data:
            lead_id = cpf_item.get('lead_id')
            cpf = cpf_item.get('cpf', '').strip()
            socio_name = cpf_item.get('socio_name', '')
            
            if not lead_id or not cpf:
                errors.append(f"Dados incompletos: lead_id={lead_id}, cpf={cpf}")
                continue
            
            try:
                # Buscar lead (validar ownership)
                lead = Lead.objects.filter(id=lead_id, user=user_profile).first()
                if not lead:
                    errors.append(f"Lead {lead_id} não encontrado ou não pertence ao usuário")
                    continue
                
                # IMPORTANTE: Debitar crédito ANTES de buscar/exibir dados
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Busca por CPF: {cpf} ({socio_name})"
                )
                
                if not success:
                    errors.append(f"Erro ao debitar crédito para CPF {cpf}: {error}")
                    continue
                
                credits_debited += 1
                
                # Verificar se já tem dados do CPF salvos no lead
                viper_data = lead.viper_data or {}
                socios_qsa = viper_data.get('socios_qsa', {})
                socios_list = socios_qsa.get('socios', []) if isinstance(socios_qsa, dict) else []
                
                cpf_clean = cpf.replace('.', '').replace('-', '').strip()
                cpf_data = None
                found_socio = None
                
                # Buscar sócio pelo CPF e verificar se já tem dados enriquecidos
                # NOTA: API Viper retorna CPF no campo 'DOCUMENTO', não 'CPF' ou 'cpf'
                for socio in socios_list:
                    socio_cpf = str(socio.get('DOCUMENTO') or socio.get('CPF') or socio.get('cpf') or '').replace('.', '').replace('-', '').strip()
                    if socio_cpf == cpf_clean:
                        found_socio = socio
                        # Verificar se já tem dados do CPF
                        if socio.get('cpf_enriched') and socio.get('cpf_data'):
                            # Usar dados salvos (não fazer nova requisição à API)
                            logger.info(f"Usando dados de CPF já salvos para {cpf}")
                            cpf_data = socio.get('cpf_data')
                        break
                
                if not found_socio:
                    errors.append(f"Sócio com CPF {cpf} não encontrado no lead {lead_id}")
                    continue
                
                if not cpf_data:
                    # Dados não existem - buscar via API
                    cpf_data = search_cpf_viper(cpf_clean)
                    
                    if not cpf_data:
                        errors.append(f"Não foi possível obter dados para CPF {cpf}")
                        continue
                    
                    # Atualizar Lead.viper_data com dados do CPF no sócio correspondente
                    if not lead.viper_data:
                        lead.viper_data = {}
                    
                    if 'socios_qsa' not in lead.viper_data:
                        lead.viper_data['socios_qsa'] = {}
                    
                    if 'socios' not in lead.viper_data['socios_qsa']:
                        lead.viper_data['socios_qsa']['socios'] = []
                    
                    # Atualizar sócio específico (usando DOCUMENTO como campo principal)
                    for i, socio in enumerate(lead.viper_data['socios_qsa']['socios']):
                        socio_cpf = str(socio.get('DOCUMENTO') or socio.get('CPF') or socio.get('cpf') or '').replace('.', '').replace('-', '').strip()
                        if socio_cpf == cpf_clean:
                            lead.viper_data['socios_qsa']['socios'][i]['cpf_enriched'] = True
                            lead.viper_data['socios_qsa']['socios'][i]['cpf_data'] = cpf_data
                            break
                    
                    lead.save(update_fields=['viper_data'])
                
                results.append({
                    'lead_id': lead_id,
                    'cpf': cpf,
                    'socio_name': socio_name,
                    'data': cpf_data
                })
                
            except Exception as e:
                logger.error(f"Erro ao processar CPF {cpf}: {e}", exc_info=True)
                errors.append(f"Erro ao processar CPF {cpf}: {str(e)}")
        
        return JsonResponse({
            'success': True,
            'processed': len(results),
            'credits_debited': credits_debited,
            'results': results,
            'errors': errors if errors else None
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar CPFs em lote: {e}", exc_info=True)
        return JsonResponse({'error': f'Erro ao buscar CPFs: {str(e)}'}, status=500)


@csrf_exempt
@require_POST
def github_webhook(request):
    """
    Webhook do GitHub para deploy automático.
    Executa deploy quando há push na branch main.
    """
    from django.conf import settings
    import subprocess
    import hmac
    import hashlib
    import os
    
    # Verificar secret (opcional mas recomendado)
    github_secret = getattr(settings, 'GITHUB_WEBHOOK_SECRET', None)
    
    if github_secret:
        signature = request.META.get('HTTP_X_HUB_SIGNATURE_256', '')
        if not signature:
            logger.warning("Webhook GitHub: Missing signature")
            return JsonResponse({'error': 'Missing signature'}, status=401)
        
        body = request.body
        expected_signature = 'sha256=' + hmac.new(
            github_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning("Webhook GitHub: Invalid signature")
            return JsonResponse({'error': 'Invalid signature'}, status=401)
    
    # Verificar se é push na branch main
    try:
        payload = json.loads(request.body)
        ref = payload.get('ref', '')
        
        if ref != 'refs/heads/main':
            logger.info(f"Webhook GitHub: Not main branch ({ref}), skipping")
            return JsonResponse({'message': 'Not main branch, skipping'}, status=200)
        
        # Executar deploy
        deploy_script = '/home/nitroleads/apps/nitroleads/deploy-webhook.sh'
        
        # Verificar se o script existe
        if not os.path.exists(deploy_script):
            logger.error(f"Webhook GitHub: Deploy script not found: {deploy_script}")
            return JsonResponse({'error': 'Deploy script not found'}, status=500)
        
        # Executar em background para não travar a requisição
        subprocess.Popen(
            [deploy_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd='/home/nitroleads/apps/nitroleads'
        )
        
        logger.info("Webhook GitHub: Deploy iniciado via webhook")
        return JsonResponse({'message': 'Deploy iniciado'}, status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"Webhook GitHub: Invalid JSON payload: {e}", exc_info=True)
        return JsonResponse({'error': 'Invalid JSON payload'}, status=400)
    except Exception as e:
        logger.error(f"Webhook GitHub: Erro ao processar webhook: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)