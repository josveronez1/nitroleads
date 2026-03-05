import json
import logging
import re
import requests
from decouple import config

logger = logging.getLogger(__name__)

SERPER_API_KEY = config('SERPER_API_KEY', default='')
SERPER_GL = config('SERPER_GL', default='br')
SERPER_HL = config('SERPER_HL', default='pt-br')

def _normalize_company_name_for_cache(name):
    """Normaliza nome para cache (strip, collapse espaços). Evita duplicatas por variações mínimas."""
    if not name or not isinstance(name, str):
        return ""
    return " ".join(name.strip().split())

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

def search_google_maps(query, num=10, page=1):
    """
    Busca empresas no Google Maps via Serper com suporte a paginação.
    Usa endpoint /places. Paginação via page (1-based). gl/hl para Brasil.
    
    Args:
        query: Termo de busca (ex: "Advogado em São Paulo - SP")
        num: Número de resultados por página (padrão: 10)
        page: Página (1-based). Serper usa page, não start.
    
    Returns:
        list: Lista de lugares encontrados
    """
    url = "https://google.serper.dev/places"
    payload = {
        "q": query,
        "gl": SERPER_GL,
        "hl": SERPER_HL,
        "num": num,
        "page": page
    }
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        response_data = response.json()
        return normalize_places_response(response_data, source='places')
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar no Google Maps via Serper (query: {query}, num: {num}, page: {page}): {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar no Google Maps: {e}", exc_info=True)
        return []


def search_google_hybrid(query, num=10, page=1, min_results=None):
    """
    Busca híbrida otimizada: tenta /search primeiro, usa /places apenas quando necessário.
    Paginação via page (1-based). gl/hl para Brasil.
    
    Args:
        query: Termo de busca (ex: "Advogado em São Paulo - SP")
        num: Número de resultados por página (padrão: 10)
        page: Página (1-based). Serper usa page, não start.
        min_results: Número mínimo de resultados esperados (opcional). Se None, usa num.
    
    Returns:
        list: Lista normalizada de lugares encontrados
    """
    if min_results is None:
        min_results = num
    
    url_search = "https://google.serper.dev/search"
    payload = {
        "q": query,
        "gl": SERPER_GL,
        "hl": SERPER_HL,
        "num": num,
        "page": page
    }
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(url_search, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        search_data = response.json()
        places_from_search = normalize_places_response(search_data, source='search')
        
        if places_from_search and len(places_from_search) >= min_results:
            logger.info(f"Usando resultados de /search (places: {len(places_from_search)}, suficiente)")
            return places_from_search
        elif places_from_search:
            logger.info(f"Usando /places como complemento (search retornou {len(places_from_search)}, esperado: {min_results})")
            places_from_places = search_google_maps(query, num=num, page=page)
            combined = places_from_search.copy()
            existing_titles = {p.get('title') for p in places_from_search}
            for place in places_from_places:
                if place.get('title') not in existing_titles:
                    combined.append(place)
                    if len(combined) >= min_results:
                        break
            return combined[:min_results]
        else:
            logger.info("Usando /places como fallback (search não retornou places)")
            return search_google_maps(query, num=num, page=page)
            
    except requests.RequestException as e:
        logger.warning(f"Erro ao buscar via /search, usando /places como fallback: {e}")
        return search_google_maps(query, num=num, page=page)
    except Exception as e:
        logger.error(f"Erro inesperado na busca híbrida: {e}", exc_info=True)
        return search_google_maps(query, num=num, page=page)


def search_google_maps_paginated(query, max_results, max_pages=20):
    """
    Busca empresas no Google Maps via Serper com paginação automática.
    Usa page (1-based). gl/hl para Brasil.
    
    Args:
        query: Termo de busca (ex: "Advogado em São Paulo - SP")
        max_results: Quantidade máxima de resultados desejada
        max_pages: Limite máximo de páginas para evitar consumo excessivo (padrão: 20)
    
    Returns:
        list: Lista completa de lugares encontrados (pode ser menor que max_results se não houver mais resultados)
    """
    all_places = []
    page_num = 1  # Serper usa page 1-based
    results_per_page = 10
    max_results_safe = min(max_results, 200)
    
    logger.info(f"Iniciando busca paginada para '{query}': até {max_results_safe} resultados (máx. {max_pages} páginas)")
    
    while len(all_places) < max_results_safe and page_num <= max_pages:
        try:
            remaining_needed = max_results_safe - len(all_places)
            logger.info(f"Buscando página {page_num} para '{query}' (page: {page_num})...")
            places = search_google_hybrid(
                query, num=results_per_page, page=page_num,
                min_results=min(remaining_needed, results_per_page)
            )
            
            if not places:
                logger.info(f"Página {page_num} retornou 0 resultados. Sem mais resultados.")
                break
            
            all_places.extend(places)
            logger.info(f"Página {page_num} retornou {len(places)} resultados. Total: {len(all_places)}")
            
            if len(all_places) >= max_results_safe:
                logger.info(f"Quantidade atingida: {len(all_places)} (solicitado: {max_results_safe}).")
                break
            
            if len(places) < results_per_page:
                logger.info(f"Página {page_num} retornou < {results_per_page} resultados. Fim dos resultados.")
                break
            
            page_num += 1
                
        except Exception as e:
            logger.error(f"Erro ao buscar página {page_num} para '{query}': {e}. Usando resultados já obtidos.", exc_info=True)
            break
    
    logger.info(f"Busca paginada concluída para '{query}': {len(all_places)} resultados em {page_num} página(s)")
    return all_places[:max_results_safe]

def find_cnpj_by_name(company_name, location=None):
    """
    Busca 'CNPJ [Nome]' no Google via Serper e extrai via Regex.
    Se location for informado, inclui na query para desambiguar (evitar CNPJ de outra cidade).
    Usa gl/hl para Brasil. Sem page (só primeira página).
    """
    name = _normalize_company_name_for_cache(company_name)
    if not name:
        return None
    query = f"CNPJ {name}"
    if location and str(location).strip():
        query = f"{query} {str(location).strip()}"
    url = "https://google.serper.dev/search"
    payload = json.dumps({
        "q": query,
        "gl": SERPER_GL,
        "hl": SERPER_HL
    })
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
                cnpj_match = re.search(r'\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}', snippet)
                if cnpj_match:
                    return re.sub(r'\D', '', cnpj_match.group())
    except requests.RequestException as e:
        logger.error(f"Erro ao buscar CNPJ no Google via Serper: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar CNPJ: {e}", exc_info=True)
    return None