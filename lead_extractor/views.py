from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponse, JsonResponse, FileResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_http_methods
from django_ratelimit.decorators import ratelimit
from decouple import config
from pathlib import Path
from django.conf import settings
from .services import (
    search_google_maps, find_cnpj_by_name, enrich_company_viper, 
    get_partners_internal_queued, filter_existing_leads, search_cpf_viper, search_cnpj_viper,
    normalize_niche, normalize_location, get_cached_search, create_cached_search, get_leads_from_cache, search_incremental,
    wait_for_partners_processing, process_search_async, sanitize_lead_data, sanitize_socios_for_storage
)
import threading
from .models import Lead, Search, SearchLead, UserProfile, ViperRequestQueue, CachedSearch, NormalizedNiche, NormalizedLocation, LeadAccess, CreditTransaction
from .credit_service import debit_credits, check_credits
from .mercadopago_service import create_preference, handle_webhook, process_payment, CREDIT_PACKAGES
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


def password_reset_view(request):
    """
    Página para solicitar reset de senha usando Supabase Auth.
    """
    # Se já estiver autenticado, redirecionar para dashboard
    user_profile = getattr(request, 'user_profile', None)
    if user_profile:
        return redirect('dashboard')
    
    context = {
        'supabase_url': config('SUPABASE_URL', default=''),
        'supabase_key': config('SUPABASE_KEY', default=''),
    }
    return render(request, 'lead_extractor/password_reset.html', context)


def root_redirect_view(request):
    """
    View especial para a raiz que detecta hash de recovery e redireciona.
    SEMPRE renderiza a página HTML, pois o hash só pode ser detectado no client-side.
    O JavaScript na página decide o que fazer baseado no hash.
    """
    try:
        return render(request, 'lead_extractor/root_redirect.html', {})
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Erro em root_redirect_view: {e}", exc_info=True)
        return redirect('login')


def password_reset_confirm_view(request):
    """
    Página para confirmar e redefinir a senha usando Supabase Auth.
    O Supabase gerencia o token via URL hash, então apenas renderizamos o template.
    """
    # Se já estiver autenticado, redirecionar para dashboard
    user_profile = getattr(request, 'user_profile', None)
    if user_profile:
        return redirect('dashboard')
    
    context = {
        'supabase_url': config('SUPABASE_URL', default=''),
        'supabase_key': config('SUPABASE_KEY', default=''),
    }
    return render(request, 'lead_extractor/password_reset_confirm.html', context)


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
    leads_today = LeadAccess.objects.filter(
        user=user_profile,
        accessed_at__gte=today
    ).count() if user_profile else 0
    
    searches_today = Search.objects.filter(
        user=user_profile,
        created_at__gte=today
    ).count() if user_profile else 0
    
    # Serializar results como JSON para uso no JavaScript
    results_json = json.dumps(results, ensure_ascii=False, default=str) if results else '[]'
    
    context = {
        'results': results,
        'results_json': results_json,  # JSON serializado para JavaScript (sempre definido)
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
def onboarding_view(request):
    """
    Onboarding em 4 passos para primeiro login.
    Se já completou, redireciona para o dashboard.
    """
    user_profile = request.user_profile
    if getattr(user_profile, 'onboarding_completed', True):
        return redirect('dashboard')
    context = {
        'user_profile': user_profile,
    }
    return render(request, 'lead_extractor/onboarding.html', context)


@require_user_profile
@require_POST
def onboarding_save_step(request):
    """
    POST /onboarding/step/
    Body JSON: step=1, role=owner|manager|sdr  OU  step=2, pain_points=[...]
    """
    user_profile = request.user_profile
    if getattr(user_profile, 'onboarding_completed', True):
        return JsonResponse({'error': 'Onboarding já concluído'}, status=400)
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    step = data.get('step')
    if step == 1:
        role = data.get('role')
        if role not in ('owner', 'manager', 'sdr'):
            return JsonResponse({'error': 'role inválido'}, status=400)
        user_profile.onboarding_role = role
        user_profile.save(update_fields=['onboarding_role'])
        return JsonResponse({'ok': True})
    if step == 2:
        pain_points = data.get('pain_points')
        if not isinstance(pain_points, list):
            pain_points = []
        allowed = {'mining_phones', 'finding_decision_maker', 'copy_paste_crm'}
        pain_points = [p for p in pain_points if p in allowed]
        user_profile.onboarding_pain_points = pain_points
        user_profile.save(update_fields=['onboarding_pain_points'])
        return JsonResponse({'ok': True})
    return JsonResponse({'error': 'step inválido'}, status=400)


@require_user_profile
@require_POST
def onboarding_start_demo(request):
    """
    POST /onboarding/start-demo/
    Body JSON: niche, location
    Cria Search com quantity=5 e search_data.onboarding=True, dispara process_search_async.
    """
    user_profile = request.user_profile
    if getattr(user_profile, 'onboarding_completed', True):
        return JsonResponse({'error': 'Onboarding já concluído'}, status=400)
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    niche = (data.get('niche') or '').strip()
    location = (data.get('location') or '').strip()
    if not niche or not location:
        return JsonResponse({'error': 'niche e location são obrigatórios'}, status=400)
    niche_normalized = normalize_niche(niche)
    location_normalized = normalize_location(location)
    search_term = f"{niche} em {location}"
    cached_search = get_cached_search(niche_normalized, location_normalized) if (niche_normalized and location_normalized) else None
    use_cache = bool(cached_search and cached_search.total_leads_cached >= 5)
    search_obj = Search.objects.create(
        user=user_profile,
        niche=niche,
        location=location,
        quantity_requested=5,
        cached_search=cached_search if use_cache else None,
        status='processing',
        processing_started_at=timezone.now(),
        search_data={
            'query': search_term,
            'from_cache': use_cache,
            'onboarding': True,
        },
    )
    thread = threading.Thread(target=process_search_async, args=(search_obj.id,))
    thread.daemon = True
    thread.start()
    return JsonResponse({'search_id': search_obj.id})


@require_user_profile
def onboarding_complete(request):
    """
    GET: tela "Escolha seu plano" (híbrido).
    POST: marca onboarding_completed=True e retorna JSON com redirect.
    """
    user_profile = request.user_profile
    if request.method == 'POST':
        user_profile.onboarding_completed = True
        user_profile.save(update_fields=['onboarding_completed'])
        return JsonResponse({'redirect': '/onboarding/complete/'})
    context = {
        'user_profile': user_profile,
        'available_credits': check_credits(user_profile),
    }
    return render(request, 'lead_extractor/onboarding_complete.html', context)


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

    # Buscar leads via LeadAccess (garantindo ownership)
    # Usar select_related para evitar N+1 queries
    lead_accesses = LeadAccess.objects.filter(user=user_profile).select_related('lead', 'search', 'lead__cached_search').order_by('-accessed_at')
    
    # Se search_id fornecido, filtrar por pesquisa (já validado acima)
    is_last_search = False
    if search_id:
        lead_accesses = lead_accesses.filter(search=search_obj)
        
        # Verificar se é a última pesquisa (mais recente)
        last_search = Search.objects.filter(user=user_profile).order_by('-created_at').first()
        if last_search and last_search.id == search_id:
            is_last_search = True

    # Contar leads para log de auditoria
    leads_count = lead_accesses.count()

    for lead_access in lead_accesses:
        lead = lead_access.lead
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
        try:
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
            cpf_clean = ''.join(filter(str.isdigit, cpf))
            data = search_cpf_viper(cpf_clean)
            
            if data:
                # Normalizar estrutura de dados para garantir compatibilidade
                # A API pode retornar em formatos diferentes, normalizar para o formato esperado
                normalized_data = {}
                
                # Copiar todos os dados originais primeiro
                if isinstance(data, dict):
                    normalized_data = data.copy()
                else:
                    normalized_data = {}
                
                # Garantir que campos esperados pelo template existam
                # Telefones fixos
                if 'telefones_fixos' not in normalized_data:
                    # Tentar encontrar em diferentes estruturas
                    if 'TELEFONES_FIXOS' in normalized_data:
                        telefones_fixos = normalized_data.get('TELEFONES_FIXOS', {})
                        if isinstance(telefones_fixos, dict) and 'TELEFONE' in telefones_fixos:
                            normalized_data['telefones_fixos'] = [telefones_fixos['TELEFONE']] if telefones_fixos['TELEFONE'] else []
                        elif isinstance(telefones_fixos, list):
                            normalized_data['telefones_fixos'] = telefones_fixos
                        else:
                            normalized_data['telefones_fixos'] = []
                    else:
                        normalized_data['telefones_fixos'] = []
                
                # Telefones móveis
                if 'telefones_moveis' not in normalized_data:
                    if 'TELEFONES_MOVEIS' in normalized_data:
                        telefones_moveis = normalized_data.get('TELEFONES_MOVEIS', {})
                        if isinstance(telefones_moveis, dict) and 'TELEFONE' in telefones_moveis:
                            normalized_data['telefones_moveis'] = [telefones_moveis['TELEFONE']] if telefones_moveis['TELEFONE'] else []
                        elif isinstance(telefones_moveis, list):
                            normalized_data['telefones_moveis'] = telefones_moveis
                        else:
                            normalized_data['telefones_moveis'] = []
                    else:
                        normalized_data['telefones_moveis'] = []
                
                # WhatsApps
                if 'whatsapps' not in normalized_data:
                    normalized_data['whatsapps'] = normalized_data.get('WHATSAPPS', [])
                
                # Emails
                if 'emails' not in normalized_data:
                    if 'EMAILS' in normalized_data:
                        emails = normalized_data.get('EMAILS', {})
                        if isinstance(emails, dict) and 'EMAIL' in emails:
                            normalized_data['emails'] = [emails['EMAIL']] if emails['EMAIL'] else []
                        elif isinstance(emails, list):
                            normalized_data['emails'] = emails
                        else:
                            normalized_data['emails'] = []
                    else:
                        normalized_data['emails'] = []
                
                # Dados gerais
                if 'dados_gerais' not in normalized_data:
                    normalized_data['dados_gerais'] = normalized_data.get('DADOS_GERAIS', {})
                
                # Combinar todos os telefones em uma lista única para compatibilidade
                all_phones = []
                if normalized_data.get('telefones_fixos'):
                    all_phones.extend(normalized_data['telefones_fixos'])
                if normalized_data.get('telefones_moveis'):
                    all_phones.extend(normalized_data['telefones_moveis'])
                if normalized_data.get('whatsapps'):
                    all_phones.extend(normalized_data['whatsapps'])
                normalized_data['telefones'] = list(set([p for p in all_phones if p]))
                
                # Debitar crédito
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Busca por CPF: {cpf_clean}"
                )
                
                if success:
                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'data': normalized_data,
                            'credits_remaining': new_balance
                        })
                    # Renderizar template com resultado (usar dados normalizados + dados originais para campos extras)
                    # Combinar dados normalizados com dados originais para ter todos os campos
                    template_data = normalized_data.copy()
                    # Adicionar campos extras que podem estar nos dados originais
                    if isinstance(data, dict):
                        for key in ['enderecos', 'renda_estimada', 'ocupacao', 'participacoes', 'ENDERECOS', 'RENDA_ESTIMADA', 'OCUPACAO', 'PARTICIPACOES']:
                            if key in data:
                                # Normalizar chaves maiúsculas para minúsculas
                                normalized_key = key.lower()
                                value = data[key]
                                # Garantir que listas sejam realmente listas
                                if normalized_key in ['enderecos', 'participacoes'] and not isinstance(value, list):
                                    if value:
                                        template_data[normalized_key] = [value] if isinstance(value, dict) else []
                                    else:
                                        template_data[normalized_key] = []
                                else:
                                    template_data[normalized_key] = value
                    
                    # Garantir que dados_gerais existe
                    if 'dados_gerais' not in template_data or not template_data['dados_gerais']:
                        template_data['dados_gerais'] = {}
                    
                    # Garantir que todos os campos esperados existam (mesmo que vazios)
                    for field in ['telefones_fixos', 'telefones_moveis', 'whatsapps', 'emails', 'enderecos', 'renda_estimada', 'ocupacao', 'participacoes']:
                        if field not in template_data:
                            template_data[field] = [] if field in ['telefones_fixos', 'telefones_moveis', 'whatsapps', 'emails', 'enderecos', 'participacoes'] else {}
                    
                    # Log para debug (remover em produção se necessário)
                    logger.info(f"Renderizando template cpf_result com dados: {list(template_data.keys())}")
                    
                    # Garantir que CPF está no dados_gerais se não estiver
                    if 'dados_gerais' in template_data and isinstance(template_data['dados_gerais'], dict):
                        if 'CPF' not in template_data['dados_gerais'] and cpf_clean:
                            template_data['dados_gerais']['CPF'] = cpf_clean
                    
                    try:
                        # Garantir que user_profile e available_credits estão no contexto
                        # (necessários para o base.html renderizar corretamente)
                        response = render(request, 'lead_extractor/cpf_result.html', {
                            'data': template_data,
                            'cpf': cpf_clean,
                            'credits_remaining': new_balance,
                            'user_profile': user_profile,
                            'available_credits': new_balance
                        })
                        logger.info(f"Template renderizado com sucesso para CPF {cpf_clean}")
                        return response
                    except Exception as render_error:
                        logger.error(f"Erro ao renderizar template cpf_result: {render_error}", exc_info=True)
                        logger.error(f"Dados que causaram erro: {str(template_data)[:500]}")
                        # Tentar renderizar uma versão simplificada
                        try:
                            return render(request, 'lead_extractor/cpf_result.html', {
                                'error': f'Erro ao processar dados: {str(render_error)}',
                                'cpf': cpf_clean,
                                'credits_remaining': new_balance
                            })
                        except:
                            if is_ajax:
                                return JsonResponse({'error': f'Erro ao exibir resultados: {str(render_error)}'}, status=500)
                            messages.error(request, f'Erro ao exibir resultados: {str(render_error)}')
                            return redirect('simple_search')
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
            
        except Exception as e:
            logger.error(f"Erro ao buscar CPF: {e}", exc_info=True)
            if is_ajax:
                return JsonResponse({'error': f'Erro ao processar busca: {str(e)}'}, status=500)
            messages.error(request, f'Erro ao processar busca: {str(e)}')
            return redirect('simple_search')
    
    if is_ajax:
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    return redirect('simple_search')


@require_user_profile
def search_by_cnpj(request):
    """
    Busca dados por CNPJ usando API Viper.
    Salva o Lead no banco de dados, mas NÃO cria uma Search visível para o usuário.
    O Lead fica salvo no banco mas não aparece no histórico do usuário.
    """
    user_profile = request.user_profile
    
    if request.method == 'POST':
        cnpj = request.POST.get('cnpj', '').strip()
        
        if not cnpj:
            messages.error(request, 'CNPJ não fornecido')
            return redirect('simple_search')
        
        # Limpar CNPJ (remover formatação)
        cnpj_clean = ''.join(filter(str.isdigit, cnpj))
        
        if len(cnpj_clean) != 14:
            messages.error(request, 'CNPJ inválido')
            return redirect('simple_search')
        
        # Verificar créditos
        available_credits = check_credits(user_profile)
        if available_credits < 1:
            messages.error(request, 'Créditos insuficientes')
            return redirect('simple_search')
        
        try:
            # Verificar se já existe Lead com este CNPJ (pode ser de qualquer usuário ou sem usuário)
            existing_lead = Lead.objects.filter(cnpj=cnpj_clean).first()
            
            if existing_lead and existing_lead.viper_data:
                # Já existe - usar dados existentes
                logger.info(f"Reutilizando Lead existente {existing_lead.id} para CNPJ {cnpj_clean}")
                lead = existing_lead
                data = lead.viper_data.copy()
                
                # Verificar se precisa buscar sócios
                if not has_valid_partners_data(lead):
                    queue_result = get_partners_internal_queued(cnpj_clean, user_profile, lead=lead)
                    queue_id = queue_result.get('queue_id')
                    if queue_id:
                        partners_data = wait_for_partners_processing(queue_id, user_profile, timeout=60)
                        if partners_data:
                            data['socios_qsa'] = partners_data
                            lead.viper_data = data
                            lead.save(update_fields=['viper_data'])
            else:
                # Buscar dados do CNPJ
                data = search_cnpj_viper(cnpj_clean)
                
                if not data:
                    messages.error(request, 'CNPJ não encontrado ou erro na busca')
                    return redirect('simple_search')
                
                # Buscar sócios também usando FILA
                queue_result = get_partners_internal_queued(cnpj_clean, user_profile)
                queue_id = queue_result.get('queue_id')
                is_new = queue_result.get('is_new', True)
                
                if not is_new:
                    logger.info(f"Reutilizando requisição existente para CNPJ {cnpj_clean}, queue_id: {queue_id}")
                
                # Aguardar processamento (com timeout)
                if queue_id:
                    partners_data = wait_for_partners_processing(queue_id, user_profile, timeout=60)
                    if partners_data:
                        data['socios_qsa'] = partners_data
                
                # Criar Lead com os dados encontrados (SEM criar Search - não aparece no histórico)
                lead_name = data.get('razao_social') or data.get('nome_fantasia') or f'Empresa CNPJ {cnpj_clean}'
                address_parts = []
                if data.get('logradouro'):
                    address_parts.append(data.get('logradouro'))
                if data.get('numero'):
                    address_parts.append(data.get('numero'))
                if data.get('bairro'):
                    address_parts.append(data.get('bairro'))
                if data.get('cidade'):
                    address_parts.append(data.get('cidade'))
                if data.get('uf'):
                    address_parts.append(data.get('uf'))
                if data.get('cep'):
                    address_parts.append(f"CEP: {data.get('cep')}")
                
                # Criar Lead SEM associar a usuário (user=None) para não aparecer no histórico
                # Mas salvar no banco para reutilização futura
                lead = Lead.objects.create(
                    user=None,  # Não associar ao usuário - não aparece no histórico
                    search=None,  # Sem Search - não aparece no histórico
                    name=lead_name,
                    cnpj=cnpj_clean,
                    address=', '.join(address_parts) if address_parts else None,
                    viper_data=data
                )
                
                logger.info(f"Lead {lead.id} criado para busca rápida por CNPJ {cnpj_clean} (não associado a usuário)")
            
            # Garantir que lead e data estão definidos
            if not lead or not data:
                logger.error(f"Erro: lead ou data não definidos após processamento (CNPJ: {cnpj_clean})")
                messages.error(request, 'Erro ao processar dados do CNPJ')
                return redirect('simple_search')
            
            # Debitar crédito
            success, new_balance, error = debit_credits(
                user_profile,
                1,
                description=f"Busca rápida por CNPJ: {cnpj_clean}"
            )
            
            if success:
                messages.success(request, 'Busca realizada com sucesso!')
                # Garantir que data está atualizado no lead
                if lead.viper_data != data:
                    lead.viper_data = data
                    lead.save(update_fields=['viper_data'])
                
                context = {
                    'lead': lead,  # Usar lead real para o template
                    'cnpj': cnpj_clean,
                    'data': data,  # Usar data diretamente (garantido estar definido)
                    'user_profile': user_profile,
                    'available_credits': new_balance,
                }
                return render(request, 'lead_extractor/cnpj_result.html', context)
            else:
                messages.error(request, f'Erro ao debitar crédito: {error}')
        except Exception as e:
            logger.error(f"Erro ao buscar CNPJ {cnpj_clean}: {e}", exc_info=True)
            messages.error(request, f'Erro ao processar busca: {str(e)}')
            return redirect('simple_search')
    
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
    # Mostrar apenas as 3 últimas pesquisas (por created_at)
    # Prefetch LeadAccess para otimizar queries (leads agora são acessados via LeadAccess)
    searches = Search.objects.filter(user=user_profile).select_related('user', 'cached_search').prefetch_related('search_leads__lead').order_by('-created_at')[:3]
    
    # Identificar última pesquisa (mais recente)
    last_search_id = None
    if searches:
        last_search_id = searches[0].id if isinstance(searches, list) else searches.first().id
    
    # Não usar paginação - apenas mostrar as 3 últimas
    # Converter para lista para compatibilidade com template
    searches_list = list(searches)
    
    # Calcular para cada pesquisa se todos os leads já têm dados de sócios
    searches_with_partners_status = []
    for search in searches_list:
        display_leads = search.get_leads_for_display(user_profile)
        all_leads_have_partners = True
        leads_count = 0
        for item in display_leads:
            leads_count += 1
            if not has_valid_partners_data(item['lead']):
                all_leads_have_partners = False
                break
        
        searches_with_partners_status.append({
            'search': search,
            'display_leads': display_leads,
            'all_leads_have_partners': all_leads_have_partners if leads_count > 0 else False
        })
    
    context = {
        'searches': searches_list,
        'searches_with_partners_status': searches_with_partners_status,
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
        'mercadopago_public_key': config('MERCADOPAGO_PUBLIC_KEY', default=''),
    }

    return render(request, 'lead_extractor/purchase_credits.html', context)


@require_user_profile
def create_checkout(request):
    """
    Cria preferência de pagamento no Mercado Pago para exibir no Payment Brick (modal).
    Aceita package_id (pacote fixo) ou custom_credits (compra personalizada).
    """
    user_profile = request.user_profile

    if request.method == 'POST':
        package_id = request.POST.get('package_id')
        custom_credits = request.POST.get('custom_credits')

        pkg_id = int(package_id) if package_id and str(package_id).isdigit() else None
        cust_cred = int(custom_credits) if custom_credits and str(custom_credits).isdigit() else None

        if pkg_id is None and cust_cred is None:
            return JsonResponse({'error': 'Informe package_id ou custom_credits'}, status=400)

        if pkg_id is not None and cust_cred is not None:
            return JsonResponse({'error': 'Informe apenas package_id ou custom_credits'}, status=400)

        try:
            result = create_preference(
                user_profile,
                package_id=pkg_id,
                custom_credits=cust_cred,
            )
            if result:
                return JsonResponse({
                    'preference_id': result['preference_id'],
                    'amount': result['amount'],
                    'credits': result['credits'],
                    'description': result['description'],
                    'external_reference': result.get('external_reference'),
                })
            return JsonResponse({
                'error': 'Erro ao criar preferência. Verifique MERCADOPAGO_ACCESS_TOKEN.'
            }, status=500)
        except Exception as e:
            logger.error("Erro ao criar preferência MP: %s", e, exc_info=True)
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método não permitido'}, status=405)


@require_user_profile
def process_payment_view(request):
    """
    Recebe formData do Payment Brick e cria o pagamento no Mercado Pago.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    form_data = data.get('formData', data)
    selected_payment_method = data.get('selectedPaymentMethod')
    amount = data.get('amount')
    description = data.get('description')
    external_reference = data.get('external_reference')

    if not all([form_data, amount is not None, external_reference]):
        return JsonResponse({
            'error': 'Campos obrigatórios: formData, amount, external_reference'
        }, status=400)

    try:
        user_profile = request.user_profile
        result = process_payment(
            form_data=form_data,
            amount=amount,
            description=description or 'Créditos NitroLeads',
            external_reference=external_reference,
            payer_email=user_profile.email,
            selected_payment_method=selected_payment_method,
        )

        if result:
            return JsonResponse({
                'success': True,
                'payment_id': result.get('id'),
                'status': result.get('status'),
                'payment_method_id': result.get('payment_method_id'),
            })
        return JsonResponse({'error': 'Erro ao processar pagamento. Verifique os logs do servidor.'}, status=500)
    except ValueError as e:
        logger.error("Erro em process_payment_view (MP API): %s", e)
        return JsonResponse({'error': str(e)}, status=500)
    except Exception as e:
        logger.error("Erro em process_payment_view: %s", e, exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def mercadopago_webhook(request):
    """
    Endpoint para receber webhooks do Mercado Pago (notificações de pagamento).
    """
    logger.info("Webhook Mercado Pago recebido")
    try:
        ok = handle_webhook(request.body, request.META)
        return HttpResponse(status=200 if ok else 500)
    except Exception as e:
        logger.error("Erro ao processar webhook Mercado Pago: %s", e, exc_info=True)
        return HttpResponse(status=500)


@require_user_profile
def api_payment_status(request):
    """
    Verifica se um pagamento MP já foi creditado (via webhook).
    Usado pelo frontend para polling e redirecionar para sucesso.
    """
    payment_id = request.GET.get('payment_id')
    if not payment_id:
        return JsonResponse({'credited': False, 'error': 'payment_id ausente'}, status=400)
    credited = CreditTransaction.objects.filter(mp_payment_id=str(payment_id)).exists()
    return JsonResponse({'credited': credited})


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
def payment_cancel(request):
    """
    Página de cancelamento de pagamento.
    Redireciona para a página de compra de créditos.
    """
    messages.info(request, 'Pagamento cancelado. Você pode tentar novamente quando quiser.')
    return redirect('purchase_credits')


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
    Se q estiver vazio, retorna todos os nichos ativos (até 200) para carregamento completo.
    """
    q = request.GET.get('q', '').strip()
    
    try:
        if q:
            # Buscar nichos que contêm a query (case insensitive)
            niches = NormalizedNiche.objects.filter(
                display_name__icontains=q,
                is_active=True
            ).order_by('display_name')[:20]
        else:
            # Retornar todos os nichos ativos (para carregamento completo no front-end)
            niches = NormalizedNiche.objects.filter(
                is_active=True
            ).order_by('display_name')[:1000]
        
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
    Se q estiver vazio, retorna todas as localizações ativas (até 200) para carregamento completo.
    """
    q = request.GET.get('q', '').strip()
    
    try:
        if q:
            # Buscar cidades que contêm a query (case insensitive)
            # Formato esperado: "Cidade - UF"
            locations = NormalizedLocation.objects.filter(
                display_name__icontains=q,
                is_active=True
            ).order_by('state', 'city')[:20]
        else:
            # Retornar todas as localizações ativas (para carregamento completo no front-end)
            locations = NormalizedLocation.objects.filter(
                is_active=True
            ).order_by('state', 'city')[:1000]
        
        results = [{'value': loc.display_name, 'display': loc.display_name} for loc in locations]
        
        return JsonResponse({'results': results})
    except Exception as e:
        logger.error(f"Erro ao buscar localizações para autocomplete: {e}", exc_info=True)
        return JsonResponse({'results': []})


@require_http_methods(["GET"])
def serve_favicon(request):
    """
    Serve o favicon diretamente, sem passar pelo WhiteNoise.
    Isso resolve o problema de 403 com arquivos com hash.
    """
    favicon_path = Path(settings.BASE_DIR) / 'static' / 'images' / 'favicon.ico'
    
    # Fallback para o caminho original se não encontrar
    if not favicon_path.exists():
        favicon_path = Path(settings.BASE_DIR) / 'lead_extractor' / 'static' / 'lead_extractor' / 'images' / 'favicon.ico'
    
    if favicon_path.exists():
        return FileResponse(open(favicon_path, 'rb'), content_type='image/x-icon')
    else:
        return HttpResponse(status=404)


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


@require_user_profile
def api_search_leads(request, search_id):
    """
    Endpoint para obter leads de uma busca específica.
    GET /api/search/<int:search_id>/leads/
    Query: ?onboarding=1 — quando a busca é de onboarding, retorna tabela com 2 linhas completas e resto oculto.
    """
    user_profile = request.user_profile
    
    try:
        search_obj = Search.objects.get(id=search_id, user=user_profile)
        from django.template.loader import render_to_string
        
        display_leads = search_obj.get_leads_for_display(user_profile)
        is_onboarding = (
            request.GET.get('onboarding') == '1' and
            search_obj.search_data.get('onboarding') is True
        )
        
        if is_onboarding and display_leads:
            # Primeiras 2 linhas completas (show_full=True); resto com nome/endereço visíveis e resto em blur
            full_count = min(2, len(display_leads))
            display_leads_full = [
                {**item, 'show_full': True}
                for item in display_leads[:full_count]
            ]
            placeholder_leads = [
                {'name': item['lead'].name or '-', 'address': item['lead'].address or '-'}
                for item in display_leads[full_count:]
            ]
            leads_html = render_to_string(
                'lead_extractor/partials/onboarding_leads_table.html',
                {
                    'search': search_obj,
                    'user_profile': user_profile,
                    'display_leads_full': display_leads_full,
                    'placeholder_leads': placeholder_leads,
                },
                request=request
            )
        else:
            leads_html = render_to_string(
                'lead_extractor/partials/search_leads_table.html',
                {
                    'search': search_obj,
                    'user_profile': user_profile,
                    'display_leads': display_leads,
                },
                request=request
            )
        
        return HttpResponse(leads_html)
        
    except Search.DoesNotExist:
        return JsonResponse({'error': 'Pesquisa não encontrada'}, status=404)
    except Exception as e:
        logger.error(f"Erro ao obter leads da busca {search_id}: {e}", exc_info=True)
        return JsonResponse({'error': f'Erro ao obter leads: {str(e)}'}, status=500)


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
        
        # Buscar LeadAccess (apenas do usuário e da pesquisa)
        lead_accesses_to_enrich = LeadAccess.objects.filter(
            lead_id__in=lead_ids,
            user=user_profile,
            search=search_obj
        ).select_related('lead')
        
        if lead_accesses_to_enrich.count() != len(lead_ids):
            return JsonResponse({'error': 'Alguns leads não foram encontrados ou não pertencem a esta pesquisa'}, status=400)
        
        credits_used = 0
        enriched_count = 0
        
        # Processar cada lead
        for lead_access in lead_accesses_to_enrich:
            lead = lead_access.lead
            
            if not lead.cnpj:
                continue
            
            # Verificar se já foi enriquecido
            if lead_access.enriched_at is not None:
                # Já foi enriquecido, apenas contar
                enriched_count += 1
                continue
            
            # Verificar se dados enriquecidos já existem no lead global
            has_enriched_data = False
            if lead.viper_data:
                has_phones = bool(lead.viper_data.get('telefones'))
                has_emails = bool(lead.viper_data.get('emails'))
                has_partners = has_valid_partners_data(lead)
                has_enriched_data = has_phones or has_emails or has_partners
            
            if not has_enriched_data:
                # Buscar dados faltantes da API
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
                    if not has_valid_partners_data(lead):
                        # Enfileirar busca de sócios (sem aguardar)
                        queue_result = get_partners_internal_queued(lead.cnpj, user_profile, lead=lead)
                        if not queue_result.get('is_new', True):
                            logger.info(f"Reutilizando requisição existente para Lead {lead.id} (CNPJ: {lead.cnpj})")
                    
                    lead.save(update_fields=['viper_data'])
            
            # Debitar crédito e atualizar enriched_at
            success, new_balance, error = debit_credits(
                user_profile,
                1,
                description=f"Enriquecimento: {lead.name}"
            )
            
            if success:
                lead_access.enriched_at = timezone.now()
                lead_access.save(update_fields=['enriched_at'])
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
        
        # Buscar LeadAccess (apenas do usuário e da pesquisa)
        lead_accesses_to_process = LeadAccess.objects.filter(
            lead_id__in=lead_ids,
            user=user_profile,
            search=search_obj
        ).select_related('lead')
        
        if lead_accesses_to_process.count() != len(lead_ids):
            return JsonResponse({
                'error': 'Alguns leads não foram encontrados ou não pertencem a esta pesquisa'
            }, status=400)
        
        results = []
        credits_debited = 0
        errors = []
        
        for lead_access in lead_accesses_to_process:
            lead = lead_access.lead
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
                
                # Atualizar enriched_at se ainda não foi atualizado
                if lead_access.enriched_at is None:
                    lead_access.enriched_at = timezone.now()
                    lead_access.save(update_fields=['enriched_at'])
                
                # Recarregar Lead para pegar dados atualizados (se já existirem)
                lead.refresh_from_db()
                
                partners_raw = lead.viper_data.get('socios_qsa', {}) if lead.viper_data else {}
                partners_sanitized = sanitize_socios_for_storage(partners_raw) if partners_raw else {}
                results.append({
                    'lead_id': lead.id,
                    'name': lead.name,
                    'cnpj': lead.cnpj,
                    'partners': partners_sanitized if isinstance(partners_sanitized, dict) else {'socios': partners_sanitized},
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
def api_partners_status(request, search_id):
    """
    Endpoint para verificar status de processamento de sócios.
    POST /api/search/<int:search_id>/partners-status/
    Body: {'lead_ids': [1, 2, 3]}
    Retorna leads que foram atualizados com dados de sócios.
    """
    user_profile = request.user_profile
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    try:
        search_obj = Search.objects.get(id=search_id, user=user_profile)
        
        # Obter lista de lead_ids do body
        data = json.loads(request.body) if request.body else {}
        lead_ids = data.get('lead_ids', [])
        
        if not lead_ids:
            return JsonResponse({'error': 'Nenhum lead_id fornecido'}, status=400)
        
        updated_leads = []
        all_processed = True
        
        for lead_id in lead_ids:
            try:
                # Prefer SearchLead (nova estrutura); fallback para LeadAccess
                sl = SearchLead.objects.filter(search=search_obj, lead_id=lead_id).select_related('lead').first()
                if sl:
                    lead = sl.lead
                else:
                    lead_access = search_obj.lead_accesses.filter(lead_id=lead_id).first()
                    if not lead_access:
                        continue
                    lead = lead_access.lead
                has_partners = has_valid_partners_data(lead)
                
                if has_partners:
                    updated_leads.append({
                        'lead_id': lead.id,
                        'viper_data': lead.viper_data
                    })
                else:
                    all_processed = False
                    
            except Exception as e:
                logger.error(f"Erro ao verificar lead {lead_id}: {e}", exc_info=True)
                all_processed = False
        
        return JsonResponse({
            'updated_leads': updated_leads,
            'all_processed': all_processed
        })
        
    except Search.DoesNotExist:
        return JsonResponse({'error': 'Pesquisa não encontrada'}, status=404)
    except Exception as e:
        logger.error(f"Erro ao verificar status de sócios: {e}", exc_info=True)
        return JsonResponse({'error': f'Erro ao verificar status: {str(e)}'}, status=500)


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
                # Buscar lead (pode ser sem usuário - busca rápida por CNPJ)
                lead = Lead.objects.filter(id=lead_id).first()
                if not lead:
                    errors.append(f"Lead {lead_id} não encontrado")
                    continue
                
                # Se o lead tem usuário, validar ownership
                if lead.user and lead.user != user_profile:
                    errors.append(f"Lead {lead_id} não pertence ao usuário")
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
                    'cpf_data': cpf_data  # Usar cpf_data para compatibilidade com template
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


LP_DIST = Path(settings.BASE_DIR) / 'lp' / 'Landing-Page---NitroLeads' / 'dist'


META_PIXEL_LP_SNIPPET = '''<!-- Meta Pixel Code -->
<script>
!function(f,b,e,v,n,t,s)
{if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '%s');
fbq('track', 'PageView');
</script>
<noscript><img height="1" width="1" style="display:none"
src="https://www.facebook.com/tr?id=%s&ev=PageView&noscript=1"
/></noscript>
<!-- End Meta Pixel Code -->
'''


def lp_index(request):
    """Serve a landing page em /lp (com Meta Pixel injetado se META_PIXEL_ID estiver configurado)."""
    index_path = LP_DIST / 'index.html'
    if not index_path.exists():
        return HttpResponse(
            '<h1>Landing Page não encontrada</h1>'
            '<p>Execute <code>cd lp/Landing-Page---NitroLeads && npm install && npm run build</code> primeiro.</p>',
            status=404,
        )
    with open(index_path, 'r', encoding='utf-8') as f:
        html = f.read()
    pixel_id = getattr(settings, 'META_PIXEL_ID', '') or ''
    if pixel_id and '</head>' in html:
        pixel_block = META_PIXEL_LP_SNIPPET % (pixel_id, pixel_id)
        html = html.replace('</head>', pixel_block + '\n</head>', 1)
    return HttpResponse(html, content_type='text/html; charset=utf-8')


def lp_static(request, path):
    """Serve os arquivos estáticos da LP (assets, etc) em /lp/*"""
    file_path = LP_DIST / path
    if not file_path.exists() or not file_path.is_file():
        return HttpResponse('Not Found', status=404)
    if '..' in path:
        return HttpResponse('Forbidden', status=403)
    content_type_map = {
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.ico': 'image/x-icon',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
    }
    content_type = content_type_map.get(file_path.suffix.lower(), 'application/octet-stream')
    return FileResponse(open(file_path, 'rb'), content_type=content_type)