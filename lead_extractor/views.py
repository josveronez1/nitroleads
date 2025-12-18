from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from decouple import config
from .services import (
    search_google_maps, find_cnpj_by_name, enrich_company_viper, 
    get_partners_internal, get_partners_internal_queued, filter_existing_leads, search_cpf_viper, search_cnpj_viper
)
from .models import Lead, Search, UserProfile, ViperRequestQueue
from .credit_service import debit_credits, check_credits
from .stripe_service import create_checkout_session, create_custom_checkout_session, handle_webhook_event, CREDIT_PACKAGES, CREDIT_PRICE, MIN_CREDITS, MAX_CREDITS
from .decorators import require_user_profile, validate_user_ownership
import csv
import json

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
                # Buscar lugares no Google Maps
                places = search_google_maps(search_term)
                
                # Aplicar filtro de deduplicação
                filtered_places, existing_cnpjs = filter_existing_leads(user_profile, places, days_threshold=30)
                
                # Criar objeto Search para salvar
                search_obj = Search.objects.create(
                    user=user_profile,
                    niche=niche,
                    location=location,
                    quantity_requested=quantity,
                    search_data={
                        'query': search_term,
                        'total_places_found': len(places),
                        'filtered_places': len(filtered_places),
                    }
                )
                
                credits_used = 0
                leads_processed = 0
                queue_items = []  # Armazenar queue_ids para buscar resultados depois
                
                # Processar até atingir a quantidade solicitada
                for place in filtered_places[:quantity]:
                    if leads_processed >= quantity:
                        break
                    
                    company_data = {
                        'name': place.get('title'),
                        'address': place.get('address'),
                        'phone_maps': place.get('phoneNumber'),
                        'cnpj': None,
                        'viper_data': {},
                        'queue_id': None  # Para armazenar ID da fila
                    }
                    
                    # 1. Buscar CNPJ
                    cnpj = find_cnpj_by_name(company_data['name'])
                    
                    if cnpj:
                        company_data['cnpj'] = cnpj
                        
                        # 2. Buscar dados públicos (Telefone/Endereço)
                        public_data = enrich_company_viper(cnpj)
                        if public_data:
                            company_data['viper_data'].update(public_data)
                        
                        # 3. Buscar Sócios usando FILA (API Interna/Secreta)
                        # Enfileirar a requisição em vez de processar diretamente
                        queue_result = get_partners_internal_queued(cnpj, user_profile)
                        company_data['queue_id'] = queue_result.get('queue_id')
                        queue_items.append(company_data['queue_id'])
                        
                        # Verificar se já existe lead com este CNPJ para este usuário
                        existing_lead = Lead.objects.filter(
                            user=user_profile,
                            cnpj=cnpj
                        ).first()
                        
                        if existing_lead:
                            # Atualizar last_seen_by_user
                            existing_lead.last_seen_by_user = timezone.now()
                            existing_lead.save(update_fields=['last_seen_by_user'])
                            lead_obj = existing_lead
                        else:
                            # Criar novo lead (com dados parciais, sócios serão adicionados depois)
                            lead_obj = Lead.objects.create(
                                user=user_profile,
                                search=search_obj,
                                name=company_data['name'],
                                address=company_data['address'],
                                phone_maps=company_data['phone_maps'],
                                cnpj=cnpj,
                                viper_data=company_data['viper_data']  # Sem sócios ainda
                            )
                            
                            # Debitar crédito apenas para leads novos
                            success, new_balance, error = debit_credits(
                                user_profile,
                                1,
                                description=f"Lead: {company_data['name']}"
                            )
                            
                            if success:
                                credits_used += 1
                            else:
                                messages.warning(request, f'Erro ao debitar crédito: {error}')
                                continue
                        
                        leads_processed += 1
                        results.append(company_data)
                
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
                    ],
                    'queue_items': queue_items  # IDs das requisições na fila
                }
                search_obj.save()
                
                if queue_items:
                    messages.info(request, f'Busca iniciada! {leads_processed} leads encontrados. {credits_used} créditos utilizados. Os dados dos sócios estão sendo processados...')
                else:
                    messages.success(request, f'Busca concluída! {leads_processed} leads encontrados. {credits_used} créditos utilizados.')
    
    # Buscar créditos disponíveis
    available_credits = check_credits(user_profile) if user_profile else 0
    
    # Se há resultados, verificar se há queue_items para processar
    queue_items = []
    if results:
        queue_items = [r.get('queue_id') for r in results if r.get('queue_id')]
    
    # Converter queue_items para JSON seguro para o template
    queue_items_json = json.dumps(queue_items) if queue_items else '[]'
    
    context = {
        'results': results,
        'search_term': search_term,
        'niche': niche,
        'location': location,
        'quantity': quantity,
        'available_credits': available_credits,
        'user_profile': user_profile,
        'queue_items': queue_items,  # IDs das requisições na fila
        'queue_items_json': queue_items_json,  # JSON seguro para JavaScript
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
            # Buscar sócios também usando FILA
            queue_result = get_partners_internal_queued(cnpj, user_profile)
            # Retornar queue_id para o frontend fazer polling
            data['queue_id'] = queue_result.get('queue_id')
            
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
            session = create_checkout_session(package_id, user_profile.id, user_profile.email)
            
            if session:
                return JsonResponse({'session_id': session.id, 'url': session.url})
            else:
                return JsonResponse({'error': 'Erro ao criar sessão de checkout'}, status=500)
                
        except ValueError:
            return JsonResponse({'error': 'ID de pacote inválido'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
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
            
            if credits < MIN_CREDITS or credits > MAX_CREDITS:
                return JsonResponse({
                    'error': f'Quantidade de créditos deve estar entre {MIN_CREDITS} e {MAX_CREDITS}'
                }, status=400)
            
            session = create_custom_checkout_session(credits, user_profile.id, user_profile.email)
            
            if session:
                return JsonResponse({'session_id': session.id, 'url': session.url})
            else:
                return JsonResponse({'error': 'Erro ao criar sessão de checkout'}, status=500)
                
        except ValueError:
            return JsonResponse({'error': 'Quantidade de créditos inválida'}, status=400)
        except Exception as e:
            logger.error(f"Erro ao criar checkout customizado: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método não permitido'}, status=405)


@csrf_exempt
def stripe_webhook(request):
    """
    Endpoint para receber webhooks do Stripe.
    """
    import json
    import stripe
    
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    webhook_secret = config('STRIPE_WEBHOOK_SECRET', default='')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)
    
    # Processar evento
    if handle_webhook_event(event):
        return HttpResponse(status=200)
    else:
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