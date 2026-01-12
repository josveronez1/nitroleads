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

def normalize_places_response(response_data, source='search'):
    """
    Normaliza resposta de /search ou /places para formato unificado.
    
    Args:
        response_data: Dict com resposta da API Serper
        source: 'search' ou 'places' - origem dos dados
    
    Returns:
        list: Lista normalizada de places no formato [{'title': ..., 'address': ..., 'phoneNumber': ...}]
    """
    places = []
    
    if source == 'search':
        # Verificar se tem 'places' na resposta
        if 'places' in response_data and isinstance(response_data['places'], list):
            places = response_data['places']
        # Verificar se tem 'localPack' na resposta
        elif 'localPack' in response_data:
            local_pack = response_data['localPack']
            # localPack pode ter estrutura diferente, tentar extrair places
            if isinstance(local_pack, dict):
                # Pode ter 'places' dentro do localPack
                if 'places' in local_pack and isinstance(local_pack['places'], list):
                    places = local_pack['places']
                # Ou pode ter lista direta de resultados
                elif 'results' in local_pack and isinstance(local_pack['results'], list):
                    places = local_pack['results']
    elif source == 'places':
        # Resposta direta de /places já vem como lista ou dict com 'places'
        if isinstance(response_data, list):
            places = response_data
        elif isinstance(response_data, dict) and 'places' in response_data:
            places = response_data['places']
    
    # Normalizar estrutura: garantir que cada place tem title, address, phoneNumber
    normalized = []
    for place in places:
        if isinstance(place, dict):
            normalized_place = {
                'title': place.get('title') or place.get('name') or '',
                'address': place.get('address') or place.get('formattedAddress') or '',
                'phoneNumber': place.get('phoneNumber') or place.get('phone') or '',
            }
            # Manter outros campos úteis se existirem
            for key in ['rating', 'reviews', 'website', 'category', 'latitude', 'longitude']:
                if key in place:
                    normalized_place[key] = place[key]
            normalized.append(normalized_place)
    
    return normalized


def search_google_maps(query, num=10, start=0):
    """
    Busca empresas no Google Maps via Serper com suporte a paginação.
    Usa endpoint /places.
    
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
        response_data = response.json()
        return normalize_places_response(response_data, source='places')
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar no Google Maps via Serper (query: {query}, num: {num}, start: {start}): {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar no Google Maps: {e}", exc_info=True)
        return []


def search_google_hybrid(query, num=10, start=0, min_results=None):
    """
    Busca híbrida otimizada: tenta /search primeiro, usa /places apenas quando necessário.
    Evita fazer 2 requisições quando 1 é suficiente.
    
    Args:
        query: Termo de busca (ex: "Advogado em São Paulo - SP")
        num: Número de resultados por página (padrão: 10)
        start: Offset/página inicial (padrão: 0)
        min_results: Número mínimo de resultados esperados (opcional). Se None, usa num.
    
    Returns:
        list: Lista normalizada de lugares encontrados
    """
    if min_results is None:
        min_results = num
    
    # Tentar /search primeiro
    url_search = "https://google.serper.dev/search"
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
        # Tentar /search primeiro
        response = requests.post(url_search, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        search_data = response.json()
        
        # Verificar se tem places ou localPack na resposta
        places_from_search = normalize_places_response(search_data, source='search')
        
        if places_from_search and len(places_from_search) >= min_results:
            # Se /search retornou resultados suficientes, usar apenas esses
            logger.info(f"Usando resultados de /search (places encontrados: {len(places_from_search)}, suficiente)")
            return places_from_search
        elif places_from_search:
            # Se /search retornou resultados mas insuficientes, usar /places como complemento
            logger.info(f"Usando /places como complemento (search retornou {len(places_from_search)} places, esperado: {min_results})")
            places_from_places = search_google_maps(query, num=num, start=start)
            
            # Combinar resultados, evitando duplicatas
            combined = places_from_search.copy()
            existing_titles = {p.get('title') for p in places_from_search}
            for place in places_from_places:
                if place.get('title') not in existing_titles:
                    combined.append(place)
                    if len(combined) >= min_results:
                        break
            
            return combined[:min_results]
        else:
            # Se /search não retornou places, usar /places como fallback
            logger.info("Usando /places como fallback (search não retornou places)")
            return search_google_maps(query, num=num, start=start)
            
    except requests.RequestException as e:
        logger.warning(f"Erro ao buscar via /search, usando /places como fallback: {e}")
        # Em caso de erro, usar /places como fallback
        return search_google_maps(query, num=num, start=start)
    except Exception as e:
        logger.error(f"Erro inesperado na busca híbrida: {e}", exc_info=True)
        # Em caso de erro, usar /places como fallback
        return search_google_maps(query, num=num, start=start)


def search_google_maps_paginated(query, max_results, max_pages=20):
    """
    Busca empresas no Google Maps via Serper com paginação automática.
    Usa busca híbrida (/search + /places) para maximizar resultados.
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
    
    logger.info(f"Iniciando busca paginada híbrida para '{query}': solicitando até {max_results_safe} resultados (máx. {max_pages} páginas)")
    
    while len(all_places) < max_results_safe and page < max_pages:
        start = page * results_per_page
        logger.info(f"Buscando página {page + 1} para '{query}' (start: {start}, num: {results_per_page})...")
        
        try:
            # Calcular quantos resultados ainda precisamos
            remaining_needed = max_results_safe - len(all_places)
            
            # Usar busca híbrida otimizada (tenta /search primeiro, fallback para /places)
            # Passar min_results para evitar buscas desnecessárias
            places = search_google_hybrid(query, num=results_per_page, start=start, min_results=min(remaining_needed, results_per_page))
            
            if not places:
                logger.info(f"Página {page + 1} retornou 0 resultados. Sem mais resultados disponíveis.")
                break
            
            all_places.extend(places)
            logger.info(f"Página {page + 1} retornou {len(places)} resultados. Total acumulado: {len(all_places)}")
            
            # Verificar se já atingimos a quantidade desejada ANTES de continuar
            if len(all_places) >= max_results_safe:
                logger.info(f"Quantidade solicitada atingida: {len(all_places)} resultados encontrados (solicitado: {max_results_safe}). Parando busca.")
                break
            
            # Se retornou menos que o esperado, provavelmente não há mais páginas
            if len(places) < results_per_page:
                logger.info(f"Página {page + 1} retornou menos que {results_per_page} resultados. Assumindo fim dos resultados.")
                break
            
            page += 1
                
        except Exception as e:
            logger.error(f"Erro ao buscar página {page + 1} para '{query}': {e}. Continuando com resultados já encontrados...", exc_info=True)
            # Continuar com os resultados já encontrados ao invés de abortar
            break
    
    logger.info(f"Busca paginada híbrida concluída para '{query}': {len(all_places)} resultados encontrados em {page + 1} página(s)")
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


def filter_existing_leads(user_profile, new_places):
    """
    Retorna lugares do Google Maps e CNPJs globais existentes.
    NÃO faz buscas no Serper - apenas retorna dados para processamento posterior.
    A filtragem por CNPJs já acessados pelo usuário será feita durante o processamento,
    quando já temos o CNPJ extraído.
    
    Args:
        user_profile: Objeto UserProfile (não usado, mantido para compatibilidade)
        new_places: Lista de lugares retornados pelo Google Maps
    
    Returns:
        tuple: (filtered_places: list, existing_cnpjs: set)
            - filtered_places: Todos os lugares para processamento (filtragem por CNPJ será feita depois)
            - existing_cnpjs: Set de CNPJs que já existem globalmente (para evitar processamento duplicado)
    """
    from .models import LeadAccess
    
    if not new_places:
        return [], set()
    
    # Buscar CNPJs de leads globais existentes (para evitar duplicatas na mesma busca)
    # Não filtramos por usuário aqui - isso será feito durante o processamento quando já temos o CNPJ
    global_cnpjs = set(
        Lead.objects.exclude(cnpj__isnull=True)
        .exclude(cnpj='')
        .values_list('cnpj', flat=True)
    )
    
    # Retornar todos os lugares - a filtragem por CNPJ já acessado será feita durante o processamento
    # Isso evita fazer centenas de buscas no Serper antes mesmo de processar os leads
    return new_places, global_cnpjs


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
    Busca um CachedSearch existente.
    Dados nunca expiram - base histórica permanente.
    
    Args:
        niche_normalized: Nicho normalizado
        location_normalized: Localização normalizada (formato: "Cidade - UF")
    
    Returns:
        CachedSearch ou None: Cache existente ou None se não existe
    """
    if not niche_normalized or not location_normalized:
        return None
    
    try:
        cached = CachedSearch.objects.filter(
            niche_normalized=niche_normalized,
            location_normalized=location_normalized
        ).first()
        
        return cached
    except Exception as e:
        logger.error(f"Erro ao buscar cache: {e}", exc_info=True)
        return None


def create_cached_search(niche_normalized, location_normalized, total_leads):
    """
    Cria um novo CachedSearch.
    Dados nunca expiram - base histórica permanente.
    
    Args:
        niche_normalized: Nicho normalizado
        location_normalized: Localização normalizada
        total_leads: Total de leads no cache
    
    Returns:
        CachedSearch: Objeto criado
    """
    now = timezone.now()
    
    cached, created = CachedSearch.objects.get_or_create(
        niche_normalized=niche_normalized,
        location_normalized=location_normalized,
        defaults={
            'total_leads_cached': total_leads,
            'last_updated': now
        }
    )
    
    if not created:
        # Atualizar cache existente
        cached.total_leads_cached = total_leads
        cached.last_updated = now
        cached.save()
    
    return cached


def cleanup_old_search_accesses(user_profile):
    """
    Remove LeadAccess de pesquisas antigas (que não estão nas 3 últimas pesquisas).
    Isso torna os leads disponíveis novamente para o usuário em novas buscas.
    
    Args:
        user_profile: UserProfile do usuário
    
    Returns:
        int: Número de LeadAccess deletados
    """
    from .models import Search, LeadAccess
    
    try:
        # Buscar as 3 últimas pesquisas do usuário (por created_at)
        last_3_searches = Search.objects.filter(
            user=user_profile
        ).order_by('-created_at')[:3]
        
        if not last_3_searches.exists():
            # Se não há pesquisas, não há nada para limpar
            return 0
        
        # IDs das 3 últimas pesquisas
        last_3_search_ids = set(last_3_searches.values_list('id', flat=True))
        
        # Deletar todos os LeadAccess que pertencem a pesquisas que NÃO estão nas 3 últimas
        deleted_count = LeadAccess.objects.filter(
            user=user_profile,
            search__isnull=False
        ).exclude(search_id__in=last_3_search_ids).delete()[0]
        
        logger.info(f"cleanup_old_search_accesses: deletados {deleted_count} LeadAccess de pesquisas antigas para usuário {user_profile.id}")
        return deleted_count
    except Exception as e:
        logger.error(f"Erro ao limpar LeadAccess de pesquisas antigas: {e}", exc_info=True)
        return 0


def get_existing_leads_from_db(niche_normalized, location_normalized, quantity, user_profile, search_obj=None):
    """
    Busca leads existentes na base de dados global que correspondem à busca.
    Não depende de CachedSearch - busca diretamente na base por nicho e localização normalizados.
    Filtra leads que o usuário já tem acesso nas 3 últimas pesquisas.
    
    Args:
        niche_normalized: Nicho normalizado (ex: "advogado")
        location_normalized: Localização normalizada (ex: "sao paulo - sp")
        quantity: Quantidade desejada
        user_profile: UserProfile do usuário
        search_obj: Objeto Search (opcional, para vincular LeadAccess)
    
    Returns:
        tuple: (lista de leads encontrados, cached_search criado/atualizado)
            - Lista de leads no formato dict como no dashboard
            - CachedSearch criado ou atualizado (ou None se não encontrou leads)
    """
    from .models import Lead, LeadAccess, CachedSearch, Search
    from .credit_service import debit_credits
    
    if not niche_normalized or not location_normalized:
        return [], None
    
    try:
        # Primeiro, limpar LeadAccess de pesquisas antigas
        cleanup_old_search_accesses(user_profile)
        
        # Buscar leads na base global que correspondem à busca
        # Buscar por leads que têm cached_search com mesmo nicho e localização
        # OU buscar diretamente por leads que podem corresponder à busca
        # Como não temos um campo direto de nicho/localização no Lead, vamos buscar via CachedSearch
        
        # Tentar encontrar CachedSearch existente
        cached_search = get_cached_search(niche_normalized, location_normalized)
        
        if cached_search:
            # Se há CachedSearch, buscar leads dele
            leads_query = Lead.objects.filter(
                cached_search=cached_search,
                cnpj__isnull=False
            ).exclude(cnpj='')
        else:
            # Se não há CachedSearch, não há leads para esta busca específica
            # Retornar vazio
            return [], None
        
        # Buscar CNPJs que o usuário já tem acesso nas 3 últimas pesquisas
        last_3_searches = Search.objects.filter(
            user=user_profile
        ).order_by('-created_at')[:3]
        
        accessed_cnpjs = set()
        if last_3_searches.exists():
            last_3_search_ids = set(last_3_searches.values_list('id', flat=True))
            accessed_cnpjs = set(
                LeadAccess.objects.filter(
                    user=user_profile,
                    search_id__in=last_3_search_ids
                ).values_list('lead__cnpj', flat=True)
            )
        
        # Buscar leads que o usuário NÃO acessou nas 3 últimas pesquisas
        # Buscar mais do que necessário (2x) para garantir que temos leads suficientes
        available_leads = leads_query.exclude(
            cnpj__in=accessed_cnpjs
        ).order_by('-created_at')[:quantity * 3]
        
        # Converter para formato esperado pelo dashboard
        results = []
        cnpjs_processed = set()
        
        # Processar leads que o usuário ainda não acessou
        for lead in available_leads:
            if len(results) >= quantity:
                break
                
            cnpj = lead.cnpj
            
            # Evitar duplicatas na mesma busca
            if cnpj in cnpjs_processed:
                continue
            cnpjs_processed.add(cnpj)
            
            # Criar LeadAccess e debitar crédito (é novo acesso)
            lead_access, created = LeadAccess.objects.get_or_create(
                user=user_profile,
                lead=lead,
                defaults={
                    'search': search_obj,
                    'credits_paid': 1,
                }
            )
            
            # Se é novo acesso, debitar crédito
            if created:
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Lead (base existente): {lead.name}"
                )
                
                if not success:
                    logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")
                    # Continuar mesmo se débito falhar (já criou LeadAccess)
            
            # Sanitizar dados (esconder QSA/telefones até enriquecer)
            sanitized_viper_data = sanitize_lead_data(
                {'viper_data': lead.viper_data or {}},
                show_partners=(lead_access.enriched_at is not None)
            ).get('viper_data', {})
            
            # Formatar para retorno
            company_data = {
                'name': lead.name,
                'address': lead.address,
                'phone_maps': lead.phone_maps,
                'cnpj': cnpj,
                'viper_data': sanitized_viper_data
            }
            
            results.append(company_data)
        
        # Se encontrou leads, garantir que CachedSearch existe e está atualizado
        if results and cached_search:
            # Atualizar total_leads_cached se necessário
            # Contar leads únicos por CNPJ usando values('cnpj').distinct()
            total_leads = Lead.objects.filter(
                cached_search=cached_search,
                cnpj__isnull=False
            ).exclude(cnpj='').values('cnpj').distinct().count()
            
            if cached_search.total_leads_cached != total_leads:
                cached_search.total_leads_cached = total_leads
                cached_search.save(update_fields=['total_leads_cached', 'last_updated'])
        
        logger.info(f"get_existing_leads_from_db: retornando {len(results)} leads da base (solicitado: {quantity})")
        return results, cached_search
    except Exception as e:
        logger.error(f"Erro ao buscar leads existentes na base: {e}", exc_info=True)
        return [], None


def get_leads_from_cache(cached_search, user_profile, quantity, search_obj=None):
    """
    Busca leads globais de um CachedSearch e cria LeadAccess para rastrear acesso.
    Retorna leads com dados sanitizados (sem QSA/telefones até enriquecer).
    GARANTE que retorna quantity leads se houver no cache, incluindo leads que o usuário já acessou.
    
    Args:
        cached_search: Objeto CachedSearch
        user_profile: UserProfile do usuário
        quantity: Quantidade desejada
        search_obj: Objeto Search (opcional, para vincular LeadAccess)
    
    Returns:
        list: Lista de leads do cache (formato dict como no dashboard)
    """
    from .models import LeadAccess, Lead
    from .credit_service import debit_credits
    
    if not cached_search:
        return []
    
    try:
        # Buscar CNPJs já acessados pelo usuário
        accessed_cnpjs = set(
            LeadAccess.objects.filter(user=user_profile)
            .values_list('lead__cnpj', flat=True)
        )
        
        # Buscar leads do cache que o usuário NÃO acessou primeiro
        # Buscar mais do que necessário (2x) para garantir que temos leads suficientes
        # Não usar distinct('cnpj') com order_by diferente - fazer deduplicação em Python
        cached_leads_new = Lead.objects.filter(
            cached_search=cached_search,
            cnpj__isnull=False
        ).exclude(cnpj='').exclude(cnpj__in=accessed_cnpjs).order_by('-created_at')[:quantity * 3]
        
        # Converter para formato esperado pelo dashboard
        results = []
        cnpjs_processed = set()
        
        # Processar leads que o usuário ainda não acessou
        for lead in cached_leads_new:
            if len(results) >= quantity:
                break
                
            cnpj = lead.cnpj
            
            # Evitar duplicatas na mesma busca
            if cnpj in cnpjs_processed:
                continue
            cnpjs_processed.add(cnpj)
            
            # Criar LeadAccess e debitar crédito (é novo acesso)
            lead_access, created = LeadAccess.objects.get_or_create(
                user=user_profile,
                lead=lead,
                defaults={
                    'search': search_obj,
                    'credits_paid': 1,
                }
            )
            
            # Se é novo acesso, debitar crédito
            if created:
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Lead (cache): {lead.name}"
                )
                
                if not success:
                    logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")
                    # Continuar mesmo se débito falhar (já criou LeadAccess)
            
            # Sanitizar dados (esconder QSA/telefones até enriquecer)
            sanitized_viper_data = sanitize_lead_data(
                {'viper_data': lead.viper_data or {}},
                show_partners=(lead_access.enriched_at is not None)
            ).get('viper_data', {})
            
            # Formatar para retorno
            company_data = {
                'name': lead.name,
                'address': lead.address,
                'phone_maps': lead.phone_maps,
                'cnpj': cnpj,
                'viper_data': sanitized_viper_data
            }
            
            results.append(company_data)
        
        # Se ainda não temos leads suficientes, buscar leads que o usuário JÁ acessou
        # (mas sem debitar crédito novamente - apenas retornar os dados)
        if len(results) < quantity:
            additional_needed = quantity - len(results)
            cached_leads_accessed = Lead.objects.filter(
                cached_search=cached_search,
                cnpj__isnull=False,
                cnpj__in=accessed_cnpjs
            ).exclude(cnpj='').exclude(cnpj__in=cnpjs_processed).order_by('-created_at')[:additional_needed * 2]
            
            for lead in cached_leads_accessed:
                if len(results) >= quantity:
                    break
                    
                cnpj = lead.cnpj
                
                # Evitar duplicatas
                if cnpj in cnpjs_processed:
                    continue
                cnpjs_processed.add(cnpj)
                
                # Obter LeadAccess existente (não criar novo, não debitar crédito)
                lead_access = LeadAccess.objects.filter(
                    user=user_profile,
                    lead=lead
                ).first()
                
                if not lead_access:
                    # Se por algum motivo não existe, criar mas não debitar crédito
                    lead_access = LeadAccess.objects.create(
                        user=user_profile,
                        lead=lead,
                        search=search_obj,
                        credits_paid=0  # Não debitar crédito pois já foi debitado antes
                    )
                
                # Sanitizar dados
                sanitized_viper_data = sanitize_lead_data(
                    {'viper_data': lead.viper_data or {}},
                    show_partners=(lead_access.enriched_at is not None)
                ).get('viper_data', {})
                
                # Formatar para retorno
                company_data = {
                    'name': lead.name,
                    'address': lead.address,
                    'phone_maps': lead.phone_maps,
                    'cnpj': cnpj,
                    'viper_data': sanitized_viper_data
                }
                
                results.append(company_data)
        
        logger.info(f"get_leads_from_cache: retornando {len(results)} leads do cache (solicitado: {quantity})")
        return results
    except Exception as e:
        logger.error(f"Erro ao buscar leads do cache: {e}", exc_info=True)
        return []


def search_incremental(search_term, user_profile, quantity, existing_cnpjs):
    """
    Busca incremental apenas os leads que ainda não foram encontrados.
    Usa paginação se necessário, mas com limite menor (busca incremental precisa de menos resultados).
    Inclui cache de CNPJs para evitar buscas repetidas no Serper.
    
    Args:
        search_term: Termo de busca para Google Maps
        user_profile: UserProfile do usuário
        quantity: Quantidade adicional necessária
        existing_cnpjs: Set de CNPJs já existentes para evitar duplicatas
    
    Returns:
        tuple: (lista de novos places, set atualizado de existing_cnpjs)
    """
    # Cache de CNPJs em memória para evitar buscas repetidas no Serper
    cnpj_cache = {}
    
    # Limites rigorosos para evitar loops infinitos e consumo excessivo
    MAX_SERPER_CALLS = 50  # Máximo de chamadas ao Serper por busca incremental
    MAX_ITERATIONS_WITHOUT_NEW = 10  # Máximo de iterações sem encontrar novos leads válidos
    serper_calls = 0
    iterations_without_new = 0
    
    # Buscar lugares no Google Maps com paginação (limite menor para busca incremental)
    # Buscar mais do que necessário para garantir quantidade suficiente após filtros
    max_results = min(quantity * 3, 50)  # Buscar até 3x a quantidade ou máximo 50
    places = search_google_maps_paginated(search_term, max_results, max_pages=5)
    
    # Aplicar filtro de deduplicação (sem days_threshold - verifica LeadAccess)
    filtered_places, global_cnpjs = filter_existing_leads(user_profile, places)
    existing_cnpjs.update(global_cnpjs)
    
    # Remover CNPJs que já estão no existing_cnpjs
    new_places = []
    for place in filtered_places:
        # Verificar limite de chamadas ao Serper
        if serper_calls >= MAX_SERPER_CALLS:
            logger.warning(f"Limite de chamadas ao Serper atingido ({MAX_SERPER_CALLS}) na busca incremental. Parando busca.")
            break
        
        # Verificar limite de iterações sem novos leads
        if iterations_without_new >= MAX_ITERATIONS_WITHOUT_NEW:
            logger.info(f"Limite de iterações sem novos leads atingido ({MAX_ITERATIONS_WITHOUT_NEW}) na busca incremental. Parando busca.")
            break
        
        company_name = place.get('title', '')
        
        # Verificar cache antes de chamar find_cnpj_by_name
        if company_name in cnpj_cache:
            cnpj = cnpj_cache[company_name]
        else:
            # Buscar CNPJ e armazenar no cache
            cnpj = find_cnpj_by_name(company_name)
            serper_calls += 1
            cnpj_cache[company_name] = cnpj
        
        if cnpj and cnpj not in existing_cnpjs:
            new_places.append(place)
            existing_cnpjs.add(cnpj)
            iterations_without_new = 0  # Reset contador de iterações sem novos leads
            if len(new_places) >= quantity:
                break
        else:
            iterations_without_new += 1
    
    logger.info(f"Busca incremental concluída: {len(new_places)} novos leads encontrados, {serper_calls} chamadas ao Serper")
    return new_places, existing_cnpjs


def sanitize_lead_data(lead_data, show_partners=False, has_enriched_access=False):
    """
    Remove dados sensíveis de leads. REGRA CRÍTICA: Sócios/telefones/emails só aparecem após enriquecimento pago.
    
    Args:
        lead_data: Dict com dados do lead (formato do dashboard)
        show_partners: DEPRECATED - usar has_enriched_access. Se True, mostra sócios (apenas quando usuário pagou créditos)
        has_enriched_access: Se True, mostra dados enriquecidos (QSA, telefones, emails) - verifica LeadAccess.enriched_at
    
    Returns:
        dict: Dados sanitizados
    """
    # Criar cópia para não modificar o original
    sanitized = copy.deepcopy(lead_data)
    
    # Se show_partners foi passado (compatibilidade), usar como has_enriched_access
    if show_partners and not has_enriched_access:
        has_enriched_access = True
    
    # Esconder dados sensíveis
    if 'viper_data' in sanitized and sanitized['viper_data']:
        viper_data = sanitized['viper_data'].copy()
        
        # REGRA CRÍTICA: Telefones e emails só aparecem se has_enriched_access=True
        if not has_enriched_access:
            viper_data.pop('telefones', None)
            viper_data.pop('emails', None)
        
        # REGRA CRÍTICA: Sócios só aparecem se has_enriched_access=True
        if not has_enriched_access:
            viper_data.pop('socios_qsa', None)
        
        # Remover endereço fiscal detalhado (sempre escondido)
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
        
        credits_used = 0
        leads_processed = 0
        existing_cnpjs = set()
        results = []
        cached_search = None
        
        # PRIMEIRO: Verificar se há leads existentes na base de dados global
        # Isso é feito ANTES de qualquer busca no Serper
        if niche_normalized and location_normalized:
            existing_leads, cached_search = get_existing_leads_from_db(
                niche_normalized, location_normalized, quantity, user_profile, search_obj
            )
            
            if existing_leads:
                # Contar créditos usados e processar leads existentes
                for company_data in existing_leads:
                    cnpj = company_data.get('cnpj')
                    if cnpj:
                        # Verificar se LeadAccess foi criado nesta busca (novo acesso = crédito debitado)
                        from .models import LeadAccess
                        lead_access = LeadAccess.objects.filter(
                            user=user_profile,
                            lead__cnpj=cnpj,
                            search=search_obj
                        ).first()
                        
                        # Se LeadAccess existe e foi criado nesta busca com crédito pago, contar
                        if lead_access and lead_access.credits_paid > 0:
                            credits_used += 1
                        
                        existing_cnpjs.add(cnpj)
                    
                    leads_processed += 1
                    results.append(company_data)
                
                logger.info(f"Leads existentes encontrados: {leads_processed} leads retornados da base (solicitado: {quantity})")
        
        # Atualizar cached_search no search_obj se encontramos leads
        if cached_search:
            search_obj.cached_search = cached_search
            search_obj.save(update_fields=['cached_search'])
        
        # Se já temos leads suficientes, não fazer busca no Serper
        if leads_processed >= quantity:
            logger.info(f"Leads suficientes encontrados na base ({leads_processed}). Não fazendo busca no Serper.")
        else:
            # Se não temos leads suficientes, fazer busca no Serper
            additional_needed = quantity - leads_processed
            logger.info(f"Leads insuficientes na base ({leads_processed}/{quantity}). Buscando {additional_needed} leads adicionais no Serper.")
            
            # Verificar se há CachedSearch para usar cache
            use_cache = False
            if cached_search and cached_search.total_leads_cached >= additional_needed:
                use_cache = True
                logger.info(f"Usando cache do CachedSearch para buscar leads adicionais.")
            
            if use_cache:
                # Buscar leads globais do cache e criar LeadAccess
                # get_leads_from_cache garante que retorna quantity leads se houver no cache
                cached_results = get_leads_from_cache(cached_search, user_profile, additional_needed, search_obj)
                
                # Contar créditos usados verificando LeadAccess criados nesta busca
                from .models import LeadAccess
                for company_data in cached_results:
                    cnpj = company_data.get('cnpj')
                    if cnpj:
                        # Verificar se LeadAccess foi criado nesta busca (novo acesso = crédito debitado)
                        lead_access = LeadAccess.objects.filter(
                            user=user_profile,
                            lead__cnpj=cnpj,
                            search=search_obj
                        ).first()
                        
                        # Se LeadAccess existe e foi criado nesta busca com crédito pago, contar
                        if lead_access and lead_access.credits_paid > 0:
                            credits_used += 1
                        
                        existing_cnpjs.add(cnpj)
                    
                    leads_processed += 1
                    results.append(company_data)
                    
                    # Parar se já temos quantidade suficiente
                    if leads_processed >= quantity:
                        break
                
                logger.info(f"Cache usado: {leads_processed - len(existing_leads) if existing_leads else leads_processed} leads adicionais do cache (total: {leads_processed}/{quantity})")
            
            # Se ainda não temos leads suficientes após usar cache, fazer busca no Serper
            if leads_processed < quantity:
                # Busca completa (sem cache ou cache insuficiente)
                # Usar busca paginada para obter múltiplas páginas até atingir quantity
                additional_needed = quantity - leads_processed
                places = search_google_maps_paginated(search_term, additional_needed)
                filtered_places, existing_cnpjs_set = filter_existing_leads(user_profile, places)
                existing_cnpjs.update(existing_cnpjs_set)
                
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
                
                # Buscar lead global existente (sem filtro user)
                from .models import LeadAccess
                existing_lead = Lead.objects.filter(cnpj=cnpj).first()
                
                if existing_lead:
                    lead_obj = existing_lead
                    # Atualizar dados se necessário
                    if public_data:
                        if not lead_obj.viper_data:
                            lead_obj.viper_data = {}
                        lead_obj.viper_data.update(public_data)
                        lead_obj.save(update_fields=['viper_data'])
                else:
                    # Criar lead global (sem user)
                    lead_obj = Lead.objects.create(
                        cached_search=cached_search,
                        name=company_data['name'],
                        address=company_data['address'],
                        phone_maps=company_data['phone_maps'],
                        cnpj=cnpj,
                        viper_data=company_data['viper_data']
                    )
                        
                # Criar ou obter LeadAccess e debitar crédito
                lead_access, created = LeadAccess.objects.get_or_create(
                    user=user_profile,
                    lead=lead_obj,
                    defaults={
                        'search': search_obj,
                        'credits_paid': 1,
                    }
                )
                
                if created:
                    success, new_balance, error = debit_credits(
                        user_profile,
                        1,
                        description=f"Lead: {company_data['name']}"
                    )
                    
                    # Se débito falhar, PARAR busca completamente
                    if not success:
                        logger.error(f"Débito de crédito falhou: {error}. Parando busca.")
                        break
                    
                    credits_used += 1
                
                # Sanitizar dados (esconder QSA/telefones até enriquecer)
                sanitized_viper_data = sanitize_lead_data(
                    {'viper_data': lead_obj.viper_data or {}},
                    show_partners=(lead_access.enriched_at is not None)
                ).get('viper_data', {})
                
                company_data['viper_data'] = sanitized_viper_data
                leads_processed += 1
                processed_cnpjs_in_search.add(cnpj)
                results.append(company_data)
                
                # Atualizar CachedSearch se necessário
                if not cached_search:
                    cached_search = create_cached_search(niche_normalized, location_normalized, 0)
                    search_obj.cached_search = cached_search
                    search_obj.save(update_fields=['cached_search'])
                
                # Atualizar cached_search no lead se necessário
                if lead_obj.cached_search != cached_search:
                    lead_obj.cached_search = cached_search
                    lead_obj.save(update_fields=['cached_search'])
            
            # Atualizar total_leads_cached no CachedSearch após processar novos leads
            if cached_search:
                total_leads = Lead.objects.filter(
                    cached_search=cached_search,
                    cnpj__isnull=False
                ).exclude(cnpj='').distinct('cnpj').count()
                
                if cached_search.total_leads_cached != total_leads:
                    cached_search.total_leads_cached = total_leads
                    cached_search.save(update_fields=['total_leads_cached', 'last_updated'])
        
        # Atualizar CachedSearch com total de leads após processamento
        if cached_search and niche_normalized and location_normalized:
            # Contar leads únicos por CNPJ usando values('cnpj').distinct()
            total_leads = Lead.objects.filter(
                cached_search=cached_search,
                cnpj__isnull=False
            ).exclude(cnpj='').values('cnpj').distinct().count()
            
            if cached_search.total_leads_cached != total_leads:
                cached_search.total_leads_cached = total_leads
                cached_search.save(update_fields=['total_leads_cached', 'last_updated'])
        
        # Se ainda faltam leads após todas as tentativas, fazer busca incremental com limites de segurança
        if leads_processed < quantity:
            additional_needed = quantity - leads_processed
            logger.info(f"Faltam {additional_needed} leads, iniciando busca incremental...")
            
            # Calcular offset inicial baseado nas páginas já buscadas
            results_per_page = 10
            start_offset = len(places) if 'places' in locals() else 0
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
                        places_page = search_google_hybrid(search_term, num=results_per_page, start=page_offset)
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
                    incremental_filtered, _ = filter_existing_leads(user_profile, incremental_places_batch)
                    
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
                        
                        # Buscar lead global existente (sem filtro user)
                        from .models import LeadAccess
                        existing_lead = Lead.objects.filter(cnpj=cnpj).first()
                        
                        if existing_lead:
                            lead_obj = existing_lead
                            # Atualizar dados se necessário
                            if public_data:
                                if not lead_obj.viper_data:
                                    lead_obj.viper_data = {}
                                lead_obj.viper_data.update(public_data)
                                lead_obj.save(update_fields=['viper_data'])
                        else:
                            # Criar lead global (sem user)
                            lead_obj = Lead.objects.create(
                                name=company_data['name'],
                                address=company_data['address'],
                                phone_maps=company_data['phone_maps'],
                                cnpj=cnpj,
                                viper_data=company_data['viper_data']
                            )
                        
                        # Criar ou obter LeadAccess e debitar crédito
                        lead_access, created = LeadAccess.objects.get_or_create(
                            user=user_profile,
                            lead=lead_obj,
                            defaults={
                                'search': search_obj,
                                'credits_paid': 1,
                            }
                        )
                        
                        if created:
                            success, new_balance, error = debit_credits(
                                user_profile,
                                1,
                                description=f"Lead: {company_data['name']}"
                            )
                            
                            # Se débito falhar, PARAR busca completamente
                            if not success:
                                logger.error(f"Débito de crédito falhou: {error}. Parando busca incremental.")
                                break
                            
                            credits_used += 1
                    
                        # Sanitizar dados (esconder QSA/telefones até enriquecer)
                        sanitized_viper_data = sanitize_lead_data(
                            {'viper_data': lead_obj.viper_data or {}},
                            show_partners=(lead_access.enriched_at is not None)
                        ).get('viper_data', {})
                        
                        company_data['viper_data'] = sanitized_viper_data
                        leads_processed += 1
                        processed_cnpjs_in_search.add(cnpj)
                        leads_found_in_batch += 1
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
                
                # Associar leads ao cache (via LeadAccess)
                if cached_search_new:
                    # Buscar leads acessados nesta busca e atualizar cached_search
                    from .models import LeadAccess
                    accessed_leads = Lead.objects.filter(
                        accesses__search=search_obj,
                        cnpj__isnull=False
                    ).exclude(cnpj='').distinct()
                    accessed_leads.update(cached_search=cached_search_new)
                    
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