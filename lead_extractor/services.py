import requests
import json
import re
import os
import subprocess
import logging
from datetime import timedelta
from django.utils import timezone
from decouple import config
from .models import Lead

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