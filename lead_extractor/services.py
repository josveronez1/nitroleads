import requests
import json
import re
import os
import subprocess
import logging
import unicodedata
from datetime import timedelta
from django.utils import timezone
from decouple import config
from .models import Lead, NormalizedNiche, NormalizedLocation, CachedSearch

logger = logging.getLogger(__name__)

# Pegando as chaves do arquivo .env com segurança
SERPER_API_KEY = config('SERPER_API_KEY', default='')
VIPER_API_KEY = config('VIPER_API_KEY', default='')
# Nota: Removemos o VIPER_JWT_TOKEN daqui porque agora ele vem do arquivo JSON

def get_auth_headers():
    """
    Função auxiliar que tenta ler o arquivo 'viper_tokens.json'
    gerado pelo auth_bot.py para pegar Token e Cookies atualizados.
    """
    try:
        # Tenta abrir o arquivo na raiz do projeto
        file_path = "viper_tokens.json"
        
        if not os.path.exists(file_path):
            logger.warning("Arquivo 'viper_tokens.json' não encontrado. Rode o auth_bot.py.")
            return None
            
        with open(file_path, "r") as f:
            return json.load(f)
            
    except Exception as e:
        logger.error(f"Erro ao ler tokens do Viper: {e}", exc_info=True)
        return None

def search_google_maps(query):
    """Busca empresas no Google Maps via Serper"""
    url = "https://google.serper.dev/places"
    payload = json.dumps({"q": query})
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, headers=headers, data=payload)
        return response.json().get('places', [])
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar no Google Maps via Serper: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar no Google Maps: {e}", exc_info=True)
        return []

def find_cnpj_by_name(company_name):
    """Busca 'CNPJ [Nome]' no Google e extrai via Regex"""
    url = "https://google.serper.dev/search"
    payload = json.dumps({"q": f"CNPJ {company_name}"})
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload)
        data = response.json()
        
        if 'organic' in data:
            for result in data['organic']:
                snippet = result.get('snippet', '') + " " + result.get('title', '')
                # Regex robusto para CNPJ
                cnpj_match = re.search(r'\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}', snippet)
                if cnpj_match:
                    # Retorna apenas números
                    return re.sub(r'\D', '', cnpj_match.group())
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar CNPJ no Google via Serper: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar CNPJ: {e}", exc_info=True)
    
    return None

def enrich_company_viper(cnpj):
    """Consulta dados detalhados no Viper (API PÚBLICA) pelo CNPJ"""
    if not VIPER_API_KEY:
        return None

    url = f"https://api.viperphone.com.br/ws/viperphone/cnpj/{cnpj}"
    headers = {
        'Authorization': f'Basic {VIPER_API_KEY}'
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar dados da empresa no Viper (CNPJ: {cnpj}): {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar dados da empresa no Viper: {e}", exc_info=True)
    
    return None

def get_partners_internal(cnpj, retry=True): # Adicionamos o parâmetro retry
    """
    Busca o QSA com retry automático:
    Se der 401, roda o auth_bot.py e tenta de novo.
    """
    auth_headers = get_auth_headers()
    
    # Se não tem headers, tenta gerar agora
    if not auth_headers and retry:
        logger.info("Nenhum token encontrado. Rodando robô de autenticação do Viper...")
        subprocess.run(["python", "auth_bot.py"])
        auth_headers = get_auth_headers()

    if not auth_headers:
        return []

    url = "https://sistemas.vipersolucoes.com.br/server/api/infoqualy/consultaCNPJSocios"
    
    headers = auth_headers.copy()
    headers.update({
        'content-type': 'application/json',
        'origin': 'https://sistemas.vipersolucoes.com.br',
        'referer': 'https://sistemas.vipersolucoes.com.br/',
    })
    
    payload = {"CNPJ": str(cnpj).strip()}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            return response.json()
            
        elif response.status_code == 401 and retry:
            logger.warning(f"Token do Viper expirado (401). Renovando tokens e tentando novamente (CNPJ: {cnpj})...")
            # Roda o bot (vai levar uns 10-15s)
            subprocess.run(["python", "auth_bot.py"])
            # Chama a função de novo (recursiva), mas sem retry infinito (retry=False)
            return get_partners_internal(cnpj, retry=False)
            
        else:
            logger.error(f"Erro ao buscar sócios no Viper (CNPJ: {cnpj}): Status {response.status_code} - {response.text}")
            
    except requests.RequestException as e:
        logger.error(f"Erro de rede ao buscar sócios no Viper (CNPJ: {cnpj}): {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar sócios no Viper: {e}", exc_info=True)
        
    return []


def filter_existing_leads(user_profile, new_places, days_threshold=30):
    """
    Filtra leads que já foram vistos pelo usuário nos últimos X dias.
    Implementa lógica híbrida: prioriza leads novos, mas permite reutilizar após X dias.
    
    Args:
        user_profile: Objeto UserProfile
        new_places: Lista de lugares retornados pelo Google Maps
        days_threshold: Número de dias para considerar um lead como "reutilizável" (padrão 30)
    
    Returns:
        tuple: (filtered_places: list, existing_cnpjs: set)
            - filtered_places: Lugares que podem ser processados (novos ou antigos que podem ser reutilizados)
            - existing_cnpjs: Set de CNPJs que já existem (para evitar processamento duplicado)
    """
    if not user_profile or not new_places:
        return [], set()
    
    # Calcular data limite para reutilização
    threshold_date = timezone.now() - timedelta(days=days_threshold)
    
    # Buscar leads existentes do usuário
    existing_leads = Lead.objects.filter(
        user=user_profile
    ).select_related('user')
    
    # Criar sets de identificadores existentes
    existing_cnpjs = set(existing_leads.exclude(cnpj__isnull=True).exclude(cnpj='').values_list('cnpj', flat=True))
    existing_names = set(existing_leads.values_list('name', flat=True))
    
    # Filtrar lugares: manter apenas os que não existem ou que foram vistos há mais de X dias
    filtered_places = []
    
    for place in new_places:
        place_name = place.get('title', '')
        
        # Verificar se existe lead com mesmo nome
        if place_name in existing_names:
            # Verificar se foi visto recentemente (dentro do threshold)
            recent_lead = existing_leads.filter(
                name=place_name,
                last_seen_by_user__gte=threshold_date
            ).first()
            
            if recent_lead:
                # Lead foi visto recentemente, não incluir (prioriza novos)
                continue
            else:
                # Lead existe mas foi visto há mais de X dias, pode reutilizar
                filtered_places.append(place)
        else:
            # Lead novo, incluir
            filtered_places.append(place)
    
    return filtered_places, existing_cnpjs


def search_cpf_viper(cpf):
    """
    Busca dados por CPF usando API Viper pública.
    
    Args:
        cpf: CPF (apenas números ou formatado)
    
    Returns:
        dict: Dados retornados pela API Viper ou None em caso de erro
    """
    if not VIPER_API_KEY:
        return None
    
    # Limpar CPF (remover pontos, traços, etc)
    cpf_clean = re.sub(r'\D', '', str(cpf))
    
    if len(cpf_clean) != 11:
        return None
    
    url = f"https://api.viperphone.com.br/ws/viperphone/cpf/{cpf_clean}"
    headers = {
        'Authorization': f'Basic {VIPER_API_KEY}'
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar CPF no Viper (CPF: {cpf}): {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar CPF no Viper: {e}", exc_info=True)
    
    return None


def search_cnpj_viper(cnpj):
    """
    Busca dados por CNPJ usando API Viper pública.
    Usa a função existente enrich_company_viper.
    
    Args:
        cnpj: CNPJ (apenas números ou formatado)
    
    Returns:
        dict: Dados retornados pela API Viper ou None em caso de erro
    """
    # Limpar CNPJ
    cnpj_clean = re.sub(r'\D', '', str(cnpj))
    
    if len(cnpj_clean) != 14:
        return None
    
    return enrich_company_viper(cnpj_clean)


def get_partners_internal_queued(cnpj, user_profile):
    """
    Busca o QSA usando fila para evitar requisições simultâneas.
    Adiciona a requisição à fila e retorna um dict com status e queue_id.
    
    Args:
        cnpj: CNPJ para buscar sócios
        user_profile: UserProfile do usuário
    
    Returns:
        dict: {
            'status': 'queued',
            'queue_id': id da requisição na fila,
            'data': None (será preenchido quando processado)
        }
    """
    from .viper_queue_service import enqueue_viper_request
    
    # Adicionar à fila
    queue_item = enqueue_viper_request(
        user_profile=user_profile,
        request_type='partners',
        request_data={'cnpj': str(cnpj).strip()},
        priority=0
    )
    
    # Retornar status de enfileirado
    return {
        'status': 'queued',
        'queue_id': queue_item.id,
        'data': None
    }


def remove_accents(text):
    """
    Remove acentos de uma string.
    
    Args:
        text: String a ser normalizada
    
    Returns:
        str: String sem acentos
    """
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join([c for c in nfkd if not unicodedata.combining(c)])


def normalize_niche(niche):
    """
    Normaliza um nicho para formato padrão.
    
    Args:
        niche: String do nicho (ex: "Advogado", "advogado", "ADVOGADO")
    
    Returns:
        str: Nicho normalizado (lowercase, sem acentos, espaços normalizados)
    """
    if not niche:
        return ''
    
    # Remove acentos
    normalized = remove_accents(niche)
    # Lowercase
    normalized = normalized.lower()
    # Remove espaços extras
    normalized = ' '.join(normalized.split())
    
    return normalized


def normalize_location(location):
    """
    Normaliza uma localização para formato "Cidade - UF".
    
    Args:
        location: String da localização (ex: "São Paulo", "são paulo - sp", "SAO PAULO-SP")
    
    Returns:
        str: Localização normalizada no formato "Cidade - UF" ou None se inválida
    """
    if not location:
        return None
    
    # Remove espaços extras
    location = ' '.join(location.split())
    
    # Tentar diferentes formatos de entrada
    # Formato 1: "Cidade - UF" ou "Cidade -UF" ou "Cidade- UF"
    match = re.match(r'^(.+?)\s*-\s*([A-Z]{2})$', location.upper())
    if match:
        city = match.group(1).strip()
        state = match.group(2).strip()
    else:
        # Formato 2: Apenas cidade (tentar buscar no banco)
        # Por enquanto, assumir que é apenas cidade e não normalizar
        # Isso será melhorado quando tivermos o autocomplete funcionando
        return None
    
    # Buscar no banco de dados
    try:
        normalized_location = NormalizedLocation.objects.filter(
            city__iexact=city,
            state=state,
            is_active=True
        ).first()
        
        if normalized_location:
            return normalized_location.display_name
        else:
            # Se não encontrou, criar formato padrão (capitalizar cidade)
            city_formatted = city.title()
            return f"{city_formatted} - {state}"
    except Exception as e:
        logger.error(f"Erro ao normalizar localização '{location}': {e}", exc_info=True)
        # Fallback: retornar formato padrão
        city_formatted = city.title() if 'city' in locals() else location.title()
        state_formatted = state if 'state' in locals() else ''
        if state_formatted:
            return f"{city_formatted} - {state_formatted}"
        return None


def get_or_create_normalized_niche(niche):
    """
    Busca ou cria um NormalizedNiche.
    
    Args:
        niche: String do nicho
    
    Returns:
        NormalizedNiche: Objeto NormalizedNiche
    """
    normalized_name = normalize_niche(niche)
    
    if not normalized_name:
        return None
    
    niche_obj, created = NormalizedNiche.objects.get_or_create(
        name=normalized_name,
        defaults={
            'display_name': niche.strip().title(),
            'is_active': True
        }
    )
    
    return niche_obj


def get_cached_search(niche_normalized, location_normalized):
    """
    Busca um CachedSearch válido (não expirado).
    
    Args:
        niche_normalized: Nicho normalizado
        location_normalized: Localização normalizada (formato: "Cidade - UF")
    
    Returns:
        CachedSearch ou None: Cache válido ou None se não existe ou está expirado
    """
    if not niche_normalized or not location_normalized:
        return None
    
    now = timezone.now()
    
    try:
        cached = CachedSearch.objects.filter(
            niche_normalized=niche_normalized,
            location_normalized=location_normalized,
            expires_at__gt=now  # Ainda não expirado
        ).first()
        
        return cached
    except Exception as e:
        logger.error(f"Erro ao buscar cache: {e}", exc_info=True)
        return None


def create_cached_search(niche_normalized, location_normalized, total_leads):
    """
    Cria um novo CachedSearch.
    
    Args:
        niche_normalized: Nicho normalizado
        location_normalized: Localização normalizada
        total_leads: Total de leads no cache
    
    Returns:
        CachedSearch: Objeto criado
    """
    now = timezone.now()
    expires_at = now + timedelta(days=90)
    
    cached, created = CachedSearch.objects.get_or_create(
        niche_normalized=niche_normalized,
        location_normalized=location_normalized,
        defaults={
            'total_leads_cached': total_leads,
            'expires_at': expires_at,
            'last_updated': now
        }
    )
    
    if not created:
        # Atualizar cache existente
        cached.total_leads_cached = total_leads
        cached.last_updated = now
        cached.expires_at = expires_at
        cached.save()
    
    return cached


def get_leads_from_cache(cached_search, user_profile, quantity):
    """
    Busca leads de um CachedSearch e cria cópias para o usuário se necessário.
    
    Args:
        cached_search: Objeto CachedSearch
        user_profile: UserProfile do usuário
        quantity: Quantidade desejada
    
    Returns:
        list: Lista de leads do cache (formato dict como no dashboard)
    """
    if not cached_search:
        return []
    
    try:
        # Buscar leads do cache (pode ser de qualquer usuário, pois é cache global)
        # Pegar leads únicos por CNPJ usando distinct
        cached_leads_raw = Lead.objects.filter(
            cached_search=cached_search,
            cnpj__isnull=False
        ).exclude(cnpj='').values_list('cnpj', flat=True).distinct()[:quantity]
        
        # Buscar os objetos Lead completos para os CNPJs únicos
        cached_leads = Lead.objects.filter(
            cached_search=cached_search,
            cnpj__in=list(cached_leads_raw)
        ).order_by('cnpj', '-created_at')  # Pegar o mais recente de cada CNPJ
        
        # Converter para formato esperado pelo dashboard
        results = []
        cnpjs_processed = set()
        
        for lead in cached_leads:
            cnpj = lead.cnpj
            
            # Evitar duplicatas (manualmente, já que pode haver múltiplos leads com mesmo CNPJ)
            if cnpj in cnpjs_processed:
                continue
            cnpjs_processed.add(cnpj)
            
            # Verificar se já existe lead para este usuário
            existing_lead = Lead.objects.filter(
                user=user_profile,
                cnpj=cnpj
            ).first()
            
            if not existing_lead:
                # Criar novo lead para este usuário a partir do cache
                Lead.objects.create(
                    user=user_profile,
                    cached_search=cached_search,
                    name=lead.name,
                    address=lead.address,
                    phone_maps=lead.phone_maps,
                    cnpj=cnpj,
                    viper_data=lead.viper_data or {},
                    first_extracted_at=lead.first_extracted_at or timezone.now()
                )
            else:
                # Atualizar last_seen_by_user do lead existente
                existing_lead.last_seen_by_user = timezone.now()
                existing_lead.save(update_fields=['last_seen_by_user'])
            
            # Formatar para retorno
            company_data = {
                'name': lead.name,
                'address': lead.address,
                'phone_maps': lead.phone_maps,
                'cnpj': cnpj,
                'viper_data': lead.viper_data or {},
                'queue_id': None  # Leads do cache já têm dados completos, sócios serão buscados depois se necessário
            }
            
            results.append(company_data)
            
            # Limitar quantidade
            if len(results) >= quantity:
                break
        
        return results
    except Exception as e:
        logger.error(f"Erro ao buscar leads do cache: {e}", exc_info=True)
        return []


def search_incremental(search_term, user_profile, quantity, existing_cnpjs):
    """
    Busca incremental apenas os leads que ainda não foram encontrados.
    
    Args:
        search_term: Termo de busca para Google Maps
        user_profile: UserProfile do usuário
        quantity: Quantidade adicional necessária
        existing_cnpjs: Set de CNPJs já existentes para evitar duplicatas
    
    Returns:
        tuple: (lista de novos places, set atualizado de existing_cnpjs)
    """
    # Buscar lugares no Google Maps
    places = search_google_maps(search_term)
    
    # Aplicar filtro de deduplicação
    filtered_places, _ = filter_existing_leads(user_profile, places, days_threshold=30)
    
    # Remover CNPJs que já estão no existing_cnpjs
    new_places = []
    for place in filtered_places[:quantity * 2]:  # Buscar mais para garantir quantidade suficiente
        # Tentar encontrar CNPJ
        cnpj = find_cnpj_by_name(place.get('title', ''))
        if cnpj and cnpj not in existing_cnpjs:
            new_places.append(place)
            existing_cnpjs.add(cnpj)
            if len(new_places) >= quantity:
                break
    
    return new_places, existing_cnpjs