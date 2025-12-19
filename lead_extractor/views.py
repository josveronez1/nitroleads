from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from decouple import config
from .services import (
    search_google_maps, find_cnpj_by_name, enrich_company_viper, 
    get_partners_internal_queued, filter_existing_leads, search_cpf_viper, search_cnpj_viper,
    normalize_niche, normalize_location, get_cached_search, create_cached_search, get_leads_from_cache, search_incremental,
    wait_for_partners_processing
)
from .models import Lead, Search, UserProfile, ViperRequestQueue, CachedSearch, NormalizedNiche, NormalizedLocation
from .credit_service import debit_credits, check_credits
from .stripe_service import create_checkout_session, create_custom_checkout_session, handle_webhook_event, CREDIT_PACKAGES, CREDIT_PRICE, MIN_CREDITS, MAX_CREDITS
from .decorators import require_user_profile, validate_user_ownership
import csv
import json
import logging

logger = logging.getLogger(__name__)

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
    quantity = 50  # Default
    
    try:
        if request.method == "POST" and user_profile:
            niche = request.POST.get('niche', '').strip()
            location = request.POST.get('location', '').strip()
            quantity = int(request.POST.get('quantity', 50))
            
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
                    
                    # Criar objeto Search para salvar
                    search_obj = Search.objects.create(
                        user=user_profile,
                        niche=niche,
                        location=location,
                        quantity_requested=quantity,
                        cached_search=cached_search if use_cache else None,
                        search_data={
                            'query': search_term,
                            'from_cache': use_cache,
                        }
                    )
                    
                    credits_used = 0
                    leads_processed = 0
                    existing_cnpjs = set()
                    
                    if use_cache:
                        # Buscar leads do cache
                        cached_results = get_leads_from_cache(cached_search, user_profile, quantity)
                        
                        for company_data in cached_results:
                            # Debitar crédito para cada lead do cache (mesmo preço)
                            success, new_balance, error = debit_credits(
                                user_profile,
                                1,
                                description=f"Lead (cache): {company_data['name']}"
                            )
                            
                            if success:
                                credits_used += 1
                                leads_processed += 1
                                results.append(company_data)
                                if company_data.get('cnpj'):
                                    existing_cnpjs.add(company_data['cnpj'])
                            else:
                                messages.warning(request, f'Erro ao debitar crédito: {error}')
                        
                        # Verificar se precisa buscar mais (busca incremental)
                        if leads_processed < quantity:
                            additional_needed = quantity - leads_processed
                            new_places, existing_cnpjs = search_incremental(
                                search_term, user_profile, additional_needed, existing_cnpjs
                            )
                            
                            # Processar novos lugares encontrados
                            for place in new_places:
                                if leads_processed >= quantity:
                                    break
                                
                                company_data = {
                                    'name': place.get('title'),
                                    'address': place.get('address'),
                                    'phone_maps': place.get('phoneNumber'),
                                    'cnpj': None,
                                    'viper_data': {}
                                }
                                
                                cnpj = find_cnpj_by_name(company_data['name'])
                                if cnpj:
                                    company_data['cnpj'] = cnpj
                                    public_data = enrich_company_viper(cnpj)
                                    if public_data:
                                        company_data['viper_data'].update(public_data)
                                    
                                    # Buscar ou criar Lead
                                    existing_lead = Lead.objects.filter(
                                        user=user_profile,
                                        cnpj=cnpj
                                    ).first()
                                    
                                    if not existing_lead:
                                        lead_obj = Lead.objects.create(
                                            user=user_profile,
                                            search=search_obj,
                                            name=company_data['name'],
                                            address=company_data['address'],
                                            phone_maps=company_data['phone_maps'],
                                            cnpj=cnpj,
                                            viper_data=company_data['viper_data']
                                        )
                                        
                                        success, new_balance, error = debit_credits(
                                            user_profile,
                                            1,
                                            description=f"Lead: {company_data['name']}"
                                        )
                                        
                                        if not success:
                                            messages.warning(request, f'Erro ao debitar crédito: {error}')
                                            continue
                                        
                                        credits_used += 1
                                    else:
                                        lead_obj = existing_lead
                                        existing_lead.last_seen_by_user = timezone.now()
                                        existing_lead.save(update_fields=['last_seen_by_user'])
                                    
                                    # Enfileirar busca de sócios e aguardar processamento
                                    queue_result = get_partners_internal_queued(cnpj, user_profile, lead=lead_obj)
                                    queue_id = queue_result.get('queue_id')
                                    
                                    # Aguardar processamento (com timeout)
                                    partners_data = wait_for_partners_processing(queue_id, user_profile, timeout=60)
                                    
                                    # Recarregar Lead para pegar dados atualizados
                                    lead_obj.refresh_from_db()
                                    
                                    # Atualizar company_data com dados completos do Lead
                                    if lead_obj.viper_data:
                                        company_data['viper_data'] = lead_obj.viper_data
                                    
                                    leads_processed += 1
                                    results.append(company_data)
                    else:
                        # Busca completa (sem cache ou cache insuficiente)
        places = search_google_maps(search_term)
                        filtered_places, existing_cnpjs_set = filter_existing_leads(user_profile, places, days_threshold=30)
                        existing_cnpjs = existing_cnpjs_set
                        
                        # Atualizar search_data
                        search_obj.search_data.update({
                            'total_places_found': len(places),
                            'filtered_places': len(filtered_places),
                        })
                        
                        # Processar até atingir a quantidade solicitada
                        for place in filtered_places[:quantity]:
                            if leads_processed >= quantity:
                                break
                            
            company_data = {
                'name': place.get('title'),
                'address': place.get('address'),
                'phone_maps': place.get('phoneNumber'),
                'cnpj': None,
                                'viper_data': {}
            }
            
            cnpj = find_cnpj_by_name(company_data['name'])
            if cnpj:
                company_data['cnpj'] = cnpj
                public_data = enrich_company_viper(cnpj)
                if public_data:
                    company_data['viper_data'].update(public_data)
                
                                # Buscar ou criar Lead
                                existing_lead = Lead.objects.filter(
                                    user=user_profile,
                                    cnpj=cnpj
                                ).first()
                                
                                if existing_lead:
                                    lead_obj = existing_lead
                                    existing_lead.last_seen_by_user = timezone.now()
                                    existing_lead.save(update_fields=['last_seen_by_user'])
                                else:
                                    lead_obj = Lead.objects.create(
                                        user=user_profile,
                                        search=search_obj,
                    name=company_data['name'],
                    address=company_data['address'],
                    phone_maps=company_data['phone_maps'],
                    cnpj=cnpj,
                    viper_data=company_data['viper_data']
                )
            
                                    success, new_balance, error = debit_credits(
                                        user_profile,
                                        1,
                                        description=f"Lead: {company_data['name']}"
                                    )
                                    
                                    if not success:
                                        messages.warning(request, f'Erro ao debitar crédito: {error}')
                                        continue
                                    
                                    credits_used += 1
                                
                                # Enfileirar busca de sócios e aguardar processamento
                                queue_result = get_partners_internal_queued(cnpj, user_profile, lead=lead_obj)
                                queue_id = queue_result.get('queue_id')
                                
                                # Aguardar processamento (com timeout)
                                partners_data = wait_for_partners_processing(queue_id, user_profile, timeout=60)
                                
                                # Recarregar Lead para pegar dados atualizados
                                lead_obj.refresh_from_db()
                                
                                # Atualizar company_data com dados completos do Lead
                                if lead_obj.viper_data:
                                    company_data['viper_data'] = lead_obj.viper_data
                                
                                leads_processed += 1
            results.append(company_data)

                        # Criar ou atualizar cache com os novos leads
                        if niche_normalized and location_normalized:
                            # Buscar ou criar cache
                            cached_search_new = get_cached_search(niche_normalized, location_normalized)
                            if not cached_search_new:
                                cached_search_new = create_cached_search(niche_normalized, location_normalized, leads_processed)
                            
                            # Associar leads ao cache e atualizar search_obj
                            if cached_search_new:
                                Lead.objects.filter(
                                    search=search_obj,
                                    cnpj__isnull=False
                                ).exclude(cnpj='').update(cached_search=cached_search_new)
                                
                                search_obj.cached_search = cached_search_new
                                search_obj.save(update_fields=['cached_search'])
                    
                    # Atualizar search_obj com resultados
                    search_obj.results_count = leads_processed
                    search_obj.credits_used = credits_used
                    search_obj.results_data = {
                        'leads': [
                            {
                                'name': r['name'],
                                'cnpj': r.get('cnpj'),
                            }
                            for r in results
                        ]
                    }
                    search_obj.save()
                    
                    messages.success(request, f'Busca concluída! {leads_processed} leads encontrados. {credits_used} créditos utilizados.')
    
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

@require_user_profile
def export_leads_csv(request, search_id=None):
    """
    Exporta leads para CSV.
    Se search_id for fornecido, exporta apenas os leads daquela pesquisa.
    Garantimos que apenas leads do usuário sejam exportados.
    """
    user_profile = request.user_profile
    
    response = HttpResponse(content_type='text/csv')
    filename = f"leads_exportados_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    # Cabeçalho organizado
    writer.writerow(['Empresa', 'CNPJ', 'Telefone (Maps)', 'Telefones (Viper)', 'Emails', 'Sócios / Decisores', 'Endereço (Maps)', 'Endereço (Fiscal)'])

    # Filtrar leads do usuário (garantindo ownership)
    leads = Lead.objects.filter(user=user_profile).order_by('-created_at')
    
    # Se search_id fornecido, validar ownership e filtrar por pesquisa
    if search_id:
        try:
            # Garantir que a pesquisa pertence ao usuário
            search_obj = Search.objects.get(id=search_id, user=user_profile)
            leads = leads.filter(search=search_obj)
        except Search.DoesNotExist:
            messages.error(request, 'Pesquisa não encontrada ou você não tem permissão para acessá-la.')
            return redirect('dashboard')

    for lead in leads:
        viper = lead.viper_data or {}
        
        # 1. Telefones Viper
        phones_list = viper.get('telefones', [])
        phones_str = " | ".join([str(p) for p in phones_list if p])
        
        # 2. Emails
        emails_list = viper.get('emails', [])
        emails_str = " | ".join([str(e) for e in emails_list if e])
        
        # 3. Sócios (CORREÇÃO AQUI)
        socios_str = ""
        qsa = viper.get('socios_qsa')
        # Verifica se qsa existe e se tem a chave 'socios' dentro
        if qsa and isinstance(qsa, dict) and 'socios' in qsa:
            lista_socios = qsa['socios']
            names = []
            for s in lista_socios:
                # Tenta pegar NOME (maiúsculo) ou nome (minúsculo)
                nome = s.get('NOME') or s.get('nome')
                cargo = s.get('CARGO') or s.get('qualificacao') or ''
                if nome:
                    names.append(f"{nome} ({cargo})")
            socios_str = " | ".join(names)

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
    """
    user_profile = request.user_profile
    
    if request.method == 'POST':
        cpf = request.POST.get('cpf', '').strip()
        
        if not cpf:
            error_msg = 'CPF não fornecido'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': error_msg}, status=400)
            messages.error(request, error_msg)
            return redirect('simple_search')
        
        # Verificar créditos
        available_credits = check_credits(user_profile)
        if available_credits < 1:
            error_msg = 'Créditos insuficientes'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': error_msg}, status=402)
            messages.error(request, error_msg)
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
                # Salvar no banco se necessário
                # Nota: busca por CPF não salva leads automaticamente, apenas retorna dados
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'data': data,
                        'credits_remaining': new_balance
                    })
                
                messages.success(request, 'Busca realizada com sucesso!')
                context = {
                    'cpf': cpf,
                    'data': data,
                    'user_profile': user_profile,
                    'available_credits': new_balance,
                }
                return render(request, 'lead_extractor/cpf_result.html', context)
            else:
                error_msg = f'Erro ao debitar crédito: {error}'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': error_msg}, status=500)
                messages.error(request, error_msg)
        else:
            error_msg = 'CPF não encontrado ou erro na busca'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': error_msg}, status=404)
            messages.error(request, error_msg)
    
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
def search_history(request):
    """
    Visualiza pesquisas antigas do usuário.
    Garante que apenas pesquisas do usuário sejam exibidas.
    """
    user_profile = request.user_profile
    
    # Garantir que apenas pesquisas do usuário sejam listadas
    searches = Search.objects.filter(user=user_profile).order_by('-created_at')
    
    # Paginação
    paginator = Paginator(searches, 20)  # 20 por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'searches': page_obj,
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
    """
    user_profile = request.user_profile
    
    try:
        queue_item = ViperRequestQueue.objects.get(id=queue_id, user=user_profile)
        
        if queue_item.status == 'completed':
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