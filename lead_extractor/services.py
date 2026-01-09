import requests
import json
import re
import os
import sys
import subprocess
import logging
import unicodedata
import threading
import copy
import fcntl
from pathlib import Path
from datetime import timedelta
from django.utils import timezone
from decouple import config
from .models import Lead, NormalizedNiche, NormalizedLocation, CachedSearch, Search

logger = logging.getLogger(__name__)

# Diretório base do projeto (2 níveis acima deste arquivo: lead_extractor/services.py -> projeto/)
BASE_DIR = Path(__file__).resolve().parent.parent

# Caminho ABSOLUTO para o arquivo de tokens
# Usar diretório 'secure' fora de STATIC_ROOT para evitar exposição via web
SECURE_DIR = BASE_DIR / "secure"
TOKENS_FILE = SECURE_DIR / "viper_tokens.json"

# Caminho ABSOLUTO para o auth_bot.py
AUTH_BOT_PATH = BASE_DIR / "auth_bot.py"

# Timeout para execução do auth_bot (em segundos)
AUTH_BOT_TIMEOUT = 90

# Pegando as chaves do arquivo .env com segurança
SERPER_API_KEY = config('SERPER_API_KEY', default='')
VIPER_API_KEY = config('VIPER_API_KEY', default='')
# Nota: Removemos o VIPER_JWT_TOKEN daqui porque agora ele vem do arquivo JSON


def get_auth_headers():
    """
    Lê o arquivo 'viper_tokens.json' de forma segura com file locking.
    
    Usa caminho ABSOLUTO para garantir que funcione independente do CWD.
    Usa file locking (fcntl.flock) para evitar race conditions.
    
    Returns:
        dict ou None: Headers de autenticação ou None se falhar
    """
    try:
        if not TOKENS_FILE.exists():
            logger.warning(f"Arquivo de tokens não encontrado: {TOKENS_FILE}")
            return None
        
        # Abrir com lock compartilhado (permite múltiplas leituras simultâneas)
        with open(TOKENS_FILE, "r") as f:
            try:
                # Lock compartilhado (LOCK_SH) - permite outras leituras
                fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                try:
                    data = json.load(f)
                    # Validar que tem os campos necessários
                    if 'Authorization' in data:
                        return data
                    else:
                        logger.warning("Arquivo de tokens não contém 'Authorization'")
                        return None
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                # Arquivo está sendo escrito, aguardar um pouco e tentar novamente
                logger.info("Arquivo de tokens está bloqueado, aguardando...")
                import time
                time.sleep(0.5)
                # Tentar novamente sem lock não-bloqueante
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                    if 'Authorization' in data:
                        return data
                    return None
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON de tokens: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao ler tokens do Viper: {e}", exc_info=True)
        return None


def run_auth_bot() -> bool:
    """
    Executa o auth_bot.py de forma segura com timeout.
    
    - Usa caminho absoluto para o script
    - Usa o mesmo interpretador Python que está rodando
    - Preserva e adiciona variáveis de ambiente necessárias
    - Tem timeout para evitar travamento indefinido
    
    Returns:
        bool: True se executou com sucesso (exit code 0), False caso contrário
    """
    logger.info(f"Executando auth_bot: {AUTH_BOT_PATH}")
    
    if not AUTH_BOT_PATH.exists():
        logger.error(f"auth_bot.py não encontrado em: {AUTH_BOT_PATH}")
        return False
    
    # Preparar ambiente
    env = os.environ.copy()
    
    # Garantir que LD_LIBRARY_PATH está definido (necessário para Playwright/Chromium)
    ld_path = env.get('LD_LIBRARY_PATH', '')
    if '/usr/lib/x86_64-linux-gnu' not in ld_path:
        if ld_path:
            env['LD_LIBRARY_PATH'] = f"/usr/lib/x86_64-linux-gnu:{ld_path}"
        else:
            env['LD_LIBRARY_PATH'] = '/usr/lib/x86_64-linux-gnu'
    
    # Garantir PLAYWRIGHT_BROWSERS_PATH se não estiver definido
    if 'PLAYWRIGHT_BROWSERS_PATH' not in env:
        # Tentar detectar automaticamente
        home_dir = Path.home()
        playwright_cache = home_dir / '.cache' / 'ms-playwright'
        if playwright_cache.exists():
            env['PLAYWRIGHT_BROWSERS_PATH'] = str(playwright_cache)
    
    try:
        result = subprocess.run(
            [sys.executable, str(AUTH_BOT_PATH)],
            env=env,
            cwd=str(BASE_DIR),
            timeout=AUTH_BOT_TIMEOUT,
            capture_output=True,
            text=True
        )
        
        # Logar output do auth_bot
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                logger.info(f"[auth_bot] {line}")
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                logger.warning(f"[auth_bot stderr] {line}")
        
        if result.returncode == 0:
            logger.info("auth_bot executado com sucesso")
            return True
        else:
            logger.error(f"auth_bot falhou com código de saída: {result.returncode}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"auth_bot excedeu o timeout de {AUTH_BOT_TIMEOUT}s")
        return False
    except Exception as e:
        logger.error(f"Erro ao executar auth_bot: {e}", exc_info=True)
        return False

def search_google_maps(query, num=10, start=0):
    """
    Busca empresas no Google Maps via Serper com suporte a paginação.
    
    Args:
        query: Termo de busca (ex: "Advogado em São Paulo - SP")
        num: Número de resultados por página (padrão: 10)
        start: Offset/página inicial (padrão: 0)
    
    Returns:
        list: Lista de lugares encontrados
    """
    url = "https://google.serper.dev/places"
    payload = {
        "q": query,
        "num": num,
        "start": start
    }
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()  # Levanta exceção para status HTTP de erro
        return response.json().get('places', [])
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar no Google Maps via Serper (query: {query}, num: {num}, start: {start}): {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar no Google Maps: {e}", exc_info=True)
        return []


def search_google_maps_paginated(query, max_results, max_pages=20):
    """
    Busca empresas no Google Maps via Serper com paginação automática.
    Faz múltiplas requisições até atingir a quantidade desejada ou esgotar os resultados.
    
    Args:
        query: Termo de busca (ex: "Advogado em São Paulo - SP")
        max_results: Quantidade máxima de resultados desejada
        max_pages: Limite máximo de páginas para evitar consumo excessivo (padrão: 20)
    
    Returns:
        list: Lista completa de lugares encontrados (pode ser menor que max_results se não houver mais resultados)
    """
    all_places = []
    page = 0
    results_per_page = 10  # API Serper retorna ~10 resultados por página
    max_results_safe = min(max_results, 200)  # Limite de segurança: máximo 200 resultados
    
    logger.info(f"Iniciando busca paginada para '{query}': solicitando até {max_results_safe} resultados (máx. {max_pages} páginas)")
    
    while len(all_places) < max_results_safe and page < max_pages:
        start = page * results_per_page
        logger.info(f"Buscando página {page + 1} para '{query}' (start: {start}, num: {results_per_page})...")
        
        try:
            places = search_google_maps(query, num=results_per_page, start=start)
            
            if not places:
                logger.info(f"Página {page + 1} retornou 0 resultados. Sem mais resultados disponíveis.")
                break
            
            all_places.extend(places)
            logger.info(f"Página {page + 1} retornou {len(places)} resultados. Total acumulado: {len(all_places)}")
            
            # Se retornou menos que o esperado, provavelmente não há mais páginas
            if len(places) < results_per_page:
                logger.info(f"Página {page + 1} retornou menos que {results_per_page} resultados. Assumindo fim dos resultados.")
                break
            
            page += 1
            
            # Verificar se já atingimos a quantidade desejada
            if len(all_places) >= max_results_safe:
                logger.info(f"Quantidade solicitada atingida: {len(all_places)} resultados encontrados (solicitado: {max_results_safe})")
                break
                
        except Exception as e:
            logger.error(f"Erro ao buscar página {page + 1} para '{query}': {e}. Continuando com resultados já encontrados...", exc_info=True)
            # Continuar com os resultados já encontrados ao invés de abortar
            break
    
    logger.info(f"Busca paginada concluída para '{query}': {len(all_places)} resultados encontrados em {page + 1} página(s)")
    return all_places[:max_results_safe]  # Garantir que não exceda o limite


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

def get_partners_internal(cnpj, retry=True):
    """
    Busca o QSA (Quadro de Sócios e Administradores) na API interna do Viper.
    
    Fluxo:
    1. Tenta ler tokens do arquivo
    2. Se não tem tokens e retry=True, executa auth_bot
    3. Faz requisição à API
    4. Se receber 401 e retry=True, renova tokens e tenta novamente
    
    Args:
        cnpj: CNPJ da empresa (apenas números)
        retry: Se True, tenta renovar tokens automaticamente em caso de erro
        
    Returns:
        list: Lista de sócios ou lista vazia em caso de erro
    """
    auth_headers = get_auth_headers()
    
    # Se não tem headers, tenta gerar agora
    if not auth_headers and retry:
        logger.info("Nenhum token encontrado. Executando auth_bot...")
        if run_auth_bot():
            auth_headers = get_auth_headers()
        else:
            logger.error("Falha ao executar auth_bot")

    if not auth_headers:
        logger.warning("Sem tokens de autenticação disponíveis")
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
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            return response.json()
            
        elif response.status_code == 401 and retry:
            logger.warning(f"Token do Viper expirado (401). Renovando tokens... (CNPJ: {cnpj})")
            if run_auth_bot():
                # Chama a função de novo (recursiva), mas sem retry infinito
                return get_partners_internal(cnpj, retry=False)
            else:
                logger.error("Falha ao renovar tokens após 401")
                return []
            
        else:
            logger.error(f"Erro ao buscar sócios no Viper (CNPJ: {cnpj}): Status {response.status_code} - {response.text}")
            
    except requests.Timeout:
        logger.error(f"Timeout ao buscar sócios no Viper (CNPJ: {cnpj})")
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


def get_partners_internal_queued(cnpj, user_profile, lead=None):
    """
    Busca o QSA usando fila para evitar requisições simultâneas.
    Verifica se já existe requisição pendente/processando antes de criar nova.
    Adiciona a requisição à fila e retorna um dict com status e queue_id.
    
    Args:
        cnpj: CNPJ para buscar sócios
        user_profile: UserProfile do usuário
        lead: Lead opcional para associar à requisição
    
    Returns:
        dict: {
            'status': 'queued' ou 'existing',
            'queue_id': id da requisição na fila,
            'data': None (será preenchido quando processado),
            'is_new': True se foi criada nova, False se reutilizada
        }
    """
    from .viper_queue_service import enqueue_viper_request
    
    # Adicionar à fila (ou reutilizar existente)
    queue_item, is_new = enqueue_viper_request(
        user_profile=user_profile,
        request_type='partners',
        request_data={'cnpj': str(cnpj).strip()},
        priority=0,
        lead=lead
    )
    
    # Retornar status de enfileirado
    return {
        'status': 'queued' if is_new else 'existing',
        'queue_id': queue_item.id,
        'data': None,
        'is_new': is_new
    }


def wait_for_partners_processing(queue_id, user_profile, timeout=60, poll_interval=1):
    """
    Aguarda o processamento de uma requisição de sócios na fila.
    
    Args:
        queue_id: ID da requisição na fila
        user_profile: UserProfile do usuário (para validação)
        timeout: Tempo máximo de espera em segundos (default: 60)
        poll_interval: Intervalo entre verificações em segundos (default: 1)
    
    Returns:
        dict ou None: Resultado da requisição se completada, None se falhou ou timeout
    """
    from .models import ViperRequestQueue
    import time
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            queue_item = ViperRequestQueue.objects.get(id=queue_id, user=user_profile)
            
            if queue_item.status == 'completed':
                return queue_item.result_data
            elif queue_item.status == 'failed':
                logger.warning(f"Requisição {queue_id} falhou: {queue_item.error_message}")
                return None
            
            # Aguardar antes de verificar novamente
            time.sleep(poll_interval)
            
        except ViperRequestQueue.DoesNotExist:
            logger.error(f"Requisição {queue_id} não encontrada")
            return None
        except Exception as e:
            logger.error(f"Erro ao verificar status da requisição {queue_id}: {e}", exc_info=True)
            return None
    
    logger.warning(f"Timeout aguardando processamento da requisição {queue_id}")
    return None


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
            
            # Formatar para retorno (viper_data já inclui QSA se disponível no cache)
            company_data = {
                'name': lead.name,
                'address': lead.address,
                'phone_maps': lead.phone_maps,
                'cnpj': cnpj,
                'viper_data': lead.viper_data or {}
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
    Usa paginação se necessário, mas com limite menor (busca incremental precisa de menos resultados).
    
    Args:
        search_term: Termo de busca para Google Maps
        user_profile: UserProfile do usuário
        quantity: Quantidade adicional necessária
        existing_cnpjs: Set de CNPJs já existentes para evitar duplicatas
    
    Returns:
        tuple: (lista de novos places, set atualizado de existing_cnpjs)
    """
    # Buscar lugares no Google Maps com paginação (limite menor para busca incremental)
    # Buscar mais do que necessário para garantir quantidade suficiente após filtros
    max_results = min(quantity * 3, 50)  # Buscar até 3x a quantidade ou máximo 50
    places = search_google_maps_paginated(search_term, max_results, max_pages=5)
    
    # Aplicar filtro de deduplicação
    filtered_places, _ = filter_existing_leads(user_profile, places, days_threshold=30)
    
    # Remover CNPJs que já estão no existing_cnpjs
    new_places = []
    for place in filtered_places:
        # Tentar encontrar CNPJ
        cnpj = find_cnpj_by_name(place.get('title', ''))
        if cnpj and cnpj not in existing_cnpjs:
            new_places.append(place)
            existing_cnpjs.add(cnpj)
            if len(new_places) >= quantity:
                break
    
    return new_places, existing_cnpjs


def sanitize_lead_data(lead_data, show_partners=False):
    """
    Remove dados sensíveis de leads. REGRA CRÍTICA: Sócios só aparecem após busca paga.
    
    Args:
        lead_data: Dict com dados do lead (formato do dashboard)
        show_partners: Se True, mostra sócios (apenas quando usuário pagou créditos)
    
    Returns:
        dict: Dados sanitizados
    """
    # Criar cópia para não modificar o original
    sanitized = copy.deepcopy(lead_data)
    
    # Esconder dados sensíveis
    if 'viper_data' in sanitized and sanitized['viper_data']:
        viper_data = sanitized['viper_data'].copy()
        
        # Remover telefones e emails do Viper (sempre escondidos)
        viper_data.pop('telefones', None)
        viper_data.pop('emails', None)
        
        # REGRA CRÍTICA: Sócios só aparecem se show_partners=True (após busca paga)
        if not show_partners:
            viper_data.pop('socios_qsa', None)
        
        # Remover endereço fiscal detalhado
        viper_data.pop('enderecos', None)
        
        sanitized['viper_data'] = viper_data
    
    return sanitized


def process_search_async(search_id):
    """
    Processa uma busca de forma assíncrona em background.
    Esta função roda em uma thread separada.
    
    Args:
        search_id: ID do objeto Search a processar
    """
    from .models import Search as SearchModel
    from .credit_service import debit_credits
    from django.contrib import messages
    
    try:
        search_obj = SearchModel.objects.get(id=search_id)
        user_profile = search_obj.user
        
        # Marcar como processando
        search_obj.status = 'processing'
        search_obj.processing_started_at = timezone.now()
        search_obj.save(update_fields=['status', 'processing_started_at'])
        
        # Obter dados da busca
        niche = search_obj.niche
        location = search_obj.location
        quantity = search_obj.quantity_requested
        search_term = f"{niche} em {location}"
        
        # Normalizar entrada
        niche_normalized = normalize_niche(niche)
        location_normalized = normalize_location(location)
        
        cached_search = None
        use_cache = False
        
        # Tentar buscar do cache
        if niche_normalized and location_normalized:
            cached_search = get_cached_search(niche_normalized, location_normalized)
            if cached_search and cached_search.total_leads_cached >= quantity:
                use_cache = True
        
        # Atualizar cached_search no search_obj
        if use_cache:
            search_obj.cached_search = cached_search
            search_obj.save(update_fields=['cached_search'])
        
        credits_used = 0
        leads_processed = 0
        existing_cnpjs = set()
        results = []
        
        if use_cache:
            # Buscar leads do cache
            cached_results = get_leads_from_cache(cached_search, user_profile, quantity)
            
            for company_data in cached_results:
                # Debitar crédito para cada lead do cache
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
                            
                            if success:
                                credits_used += 1
                        else:
                            lead_obj = existing_lead
                            existing_lead.last_seen_by_user = timezone.now()
                            existing_lead.save(update_fields=['last_seen_by_user'])
                        
                        # Não buscar sócios automaticamente - será feito opcionalmente pelo usuário
                        if lead_obj.viper_data:
                            company_data['viper_data'] = lead_obj.viper_data
                        
                        leads_processed += 1
                        results.append(company_data)
        else:
            # Busca completa (sem cache ou cache insuficiente)
            # Usar busca paginada para obter múltiplas páginas até atingir quantity
            places = search_google_maps_paginated(search_term, quantity)
            filtered_places, existing_cnpjs_set = filter_existing_leads(user_profile, places, days_threshold=30)
            existing_cnpjs = existing_cnpjs_set
            
            # Set para rastrear CNPJs já processados nesta busca específica (evitar duplicatas)
            processed_cnpjs_in_search = set()
            
            # Calcular número de páginas buscadas (aproximado)
            results_per_page = 10
            pages_searched = (len(places) + results_per_page - 1) // results_per_page if places else 0
            api_calls_made = pages_searched
            
            # Atualizar search_data com informações de paginação
            search_obj.search_data.update({
                'total_places_found': len(places),
                'filtered_places': len(filtered_places),
                'pages_searched': pages_searched,
                'api_calls_made': api_calls_made,
            })
            search_obj.save(update_fields=['search_data'])
            
            # Processar até atingir a quantidade solicitada
            for place in filtered_places:
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
                
                # Se não tem CNPJ, pular e continuar
                if not cnpj:
                    logger.info(f"Lead '{company_data['name']}' não tem CNPJ, pulando e buscando mais leads...")
                    continue
                
                # Se CNPJ já foi processado nesta busca, pular (evitar duplicatas)
                if cnpj in processed_cnpjs_in_search:
                    logger.info(f"CNPJ {cnpj} já foi processado nesta busca, pulando...")
                    continue
                
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
                
                # SEMPRE debitar crédito, mesmo se lead já existia
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Lead: {company_data['name']}"
                )
                
                # Se débito falhar, PARAR busca completamente
                if not success:
                    logger.error(f"Débito de crédito falhou: {error}. Parando busca.")
                    break
                
                # Só incrementar contadores se débito foi bem-sucedido
                credits_used += 1
                leads_processed += 1
                processed_cnpjs_in_search.add(cnpj)
                
                # Não buscar sócios automaticamente - será feito opcionalmente pelo usuário
                if lead_obj.viper_data:
                    company_data['viper_data'] = lead_obj.viper_data
                
                results.append(company_data)
            
            # Se faltam leads, fazer busca incremental com limites de segurança
            if leads_processed < quantity:
                additional_needed = quantity - leads_processed
                logger.info(f"Faltam {additional_needed} leads, iniciando busca incremental...")
                
                # Calcular offset inicial baseado nas páginas já buscadas
                results_per_page = 10
                start_offset = len(places)  # Começar após os leads já buscados
                incremental_page = 0
                max_incremental_iterations = 20  # Limite de 20 iterações (200 requisições máx)
                max_api_requests = 50  # Limite máximo de requisições à API Serper
                consecutive_empty_iterations = 0  # Contador de iterações sem leads válidos
                max_consecutive_empty = 3  # Parar após 3 iterações consecutivas sem leads válidos
                api_requests_made = 0
                
                while leads_processed < quantity and incremental_page < max_incremental_iterations:
                    # Verificar limite de requisições à API
                    if api_requests_made >= max_api_requests:
                        logger.warning(f"Limite de requisições à API atingido ({max_api_requests}). Parando busca incremental.")
                        break
                    
                    # Buscar mais leads usando offset crescente para evitar duplicatas
                    # Reduzir para 5 páginas por iteração (50 leads) ao invés de 20 (200 leads)
                    pages_per_iteration = 5
                    current_offset = start_offset + (incremental_page * results_per_page * pages_per_iteration)
                    logger.info(f"Busca incremental (iteração {incremental_page + 1}, offset: {current_offset}, páginas: {pages_per_iteration})...")
                    
                    # Buscar páginas em lotes menores
                    incremental_places_batch = []
                    for page_in_batch in range(pages_per_iteration):
                        if leads_processed >= quantity:
                            break
                        
                        if api_requests_made >= max_api_requests:
                            break
                        
                        page_offset = current_offset + (page_in_batch * results_per_page)
                        places_page = search_google_maps(search_term, num=results_per_page, start=page_offset)
                        api_requests_made += 1
                        
                        if not places_page:
                            logger.info(f"Não há mais resultados disponíveis na página {page_in_batch + 1} (offset: {page_offset}).")
                            break
                        
                        incremental_places_batch.extend(places_page)
                        
                        # Se retornou menos que o esperado, provavelmente não há mais páginas
                        if len(places_page) < results_per_page:
                            break
                    
                    if not incremental_places_batch:
                        consecutive_empty_iterations += 1
                        logger.info(f"Nenhum resultado encontrado nesta iteração. Iterações consecutivas vazias: {consecutive_empty_iterations}/{max_consecutive_empty}")
                        
                        if consecutive_empty_iterations >= max_consecutive_empty:
                            logger.warning(f"Parando busca incremental: {max_consecutive_empty} iterações consecutivas sem encontrar resultados.")
                            break
                        
                        incremental_page += 1
                        continue
                    
                    # Filtrar leads já processados
                    incremental_filtered, _ = filter_existing_leads(user_profile, incremental_places_batch, days_threshold=30)
                    
                    leads_found_in_batch = 0
                    leads_without_cnpj = 0
                    leads_duplicated = 0
                    
                    for place in incremental_filtered:
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
                        
                        # Se não tem CNPJ, pular (sem log individual para reduzir spam)
                        if not cnpj:
                            leads_without_cnpj += 1
                            continue
                        
                        # Se CNPJ já foi processado nesta busca, pular
                        if cnpj in processed_cnpjs_in_search:
                            leads_duplicated += 1
                            continue
                        
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
                        
                        # SEMPRE debitar crédito
                        success, new_balance, error = debit_credits(
                            user_profile,
                            1,
                            description=f"Lead: {company_data['name']}"
                        )
                        
                        # Se débito falhar, PARAR busca completamente
                        if not success:
                            logger.error(f"Débito de crédito falhou: {error}. Parando busca incremental.")
                            break
                        
                        # Só incrementar contadores se débito foi bem-sucedido
                        credits_used += 1
                        leads_processed += 1
                        processed_cnpjs_in_search.add(cnpj)
                        leads_found_in_batch += 1
                        
                        if lead_obj.viper_data:
                            company_data['viper_data'] = lead_obj.viper_data
                        
                        results.append(company_data)
                    
                    # Log resumido da iteração
                    if leads_found_in_batch > 0:
                        consecutive_empty_iterations = 0  # Resetar contador se encontrou leads
                        logger.info(f"Busca incremental: {leads_found_in_batch} leads válidos, {leads_without_cnpj} sem CNPJ, {leads_duplicated} duplicados. Total: {leads_processed}/{quantity} (requisições: {api_requests_made}/{max_api_requests})")
                    else:
                        consecutive_empty_iterations += 1
                        logger.info(f"Busca incremental: nenhum lead válido encontrado ({leads_without_cnpj} sem CNPJ, {leads_duplicated} duplicados). Iterações vazias: {consecutive_empty_iterations}/{max_consecutive_empty}")
                        
                        if consecutive_empty_iterations >= max_consecutive_empty:
                            logger.warning(f"Parando busca incremental: {max_consecutive_empty} iterações consecutivas sem encontrar leads válidos.")
                            break
                    
                    incremental_page += 1
                    additional_needed = quantity - leads_processed
                    if additional_needed <= 0:
                        break
                
                if leads_processed < quantity:
                    logger.info(f"Busca incremental concluída. Processados {leads_processed} de {quantity} leads solicitados. Requisições à API: {api_requests_made}")
            
            # Criar ou atualizar cache com os novos leads
            if niche_normalized and location_normalized:
                cached_search_new = get_cached_search(niche_normalized, location_normalized)
                if not cached_search_new:
                    cached_search_new = create_cached_search(niche_normalized, location_normalized, leads_processed)
                
                # Associar leads ao cache
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
        search_obj.status = 'completed'
        search_obj.save(update_fields=['results_count', 'credits_used', 'results_data', 'status'])
        
        logger.info(f"Busca {search_id} concluída: {leads_processed} leads processados, {credits_used} créditos debitados")
        
    except SearchModel.DoesNotExist:
        logger.error(f"Search {search_id} não encontrado")
    except Exception as e:
        logger.error(f"Erro ao processar busca {search_id}: {e}", exc_info=True)
        try:
            search_obj = SearchModel.objects.get(id=search_id)
            search_obj.status = 'failed'
            search_obj.save(update_fields=['status'])
        except:
            pass