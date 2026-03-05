import json
import logging
import re
import time
import requests
from decouple import config

from lead_extractor.models import ViperRequestQueue
from lead_extractor.services.viper_auth import get_auth_headers, run_auth_bot
from lead_extractor.viper_queue_service import enqueue_viper_request

logger = logging.getLogger(__name__)

VIPER_API_KEY = config('VIPER_API_KEY', default='')

# Campos de contato que devem ser removidos dos socios (nunca expor sem CPF enrichment pago)
SOCIOS_CONTACT_KEYS_TO_STRIP = {
    'telefones', 'emails', 'TELEFONE', 'telefones_fixos', 'telefones_moveis',
    'whatsapps', 'telefone', 'email', 'TELEFONES_FIXOS', 'TELEFONES_MOVEIS',
    'WHATSAPPS', 'EMAILS',
}

# Campos permitidos nos socios (nomes/cargos/CPF + cpf_data quando enriquecido por nós)
SOCIOS_ALLOWED_KEYS = {
    'NOME', 'CARGO', 'DOCUMENTO', 'CPF', 'cpf', 'nome', 'cargo', 'documento',
    'qualificacao', 'QUALIFICACAO', 'cpf_enriched', 'cpf_data'
}


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



def _normalize_cpf_api_response(data):
    """
    Normaliza a resposta da API Viper (CPF) para o formato esperado por get_unique_phones e templates.
    Retorna dict com telefones_fixos, telefones_moveis, whatsapps, emails, dados_gerais.
    """
    if not data or not isinstance(data, dict):
        return {}
    out = {}
    # Telefones fixos
    tf = data.get('telefones_fixos') or data.get('TELEFONES_FIXOS')
    if isinstance(tf, dict) and tf.get('TELEFONE'):
        out['telefones_fixos'] = [tf['TELEFONE']]
    elif isinstance(tf, list):
        out['telefones_fixos'] = [t for t in tf if t]
    else:
        out['telefones_fixos'] = []
    # Telefones móveis
    tm = data.get('telefones_moveis') or data.get('TELEFONES_MOVEIS')
    if isinstance(tm, dict) and tm.get('TELEFONE'):
        out['telefones_moveis'] = [tm['TELEFONE']]
    elif isinstance(tm, list):
        out['telefones_moveis'] = [t for t in tm if t]
    else:
        out['telefones_moveis'] = []
    out['whatsapps'] = data.get('whatsapps') or data.get('WHATSAPPS') or []
    if not isinstance(out['whatsapps'], list):
        out['whatsapps'] = []
    # Emails
    em = data.get('emails') or data.get('EMAILS')
    if isinstance(em, dict) and em.get('EMAIL'):
        out['emails'] = [em['EMAIL']]
    elif isinstance(em, list):
        out['emails'] = [e for e in em if e]
    else:
        out['emails'] = []
    out['dados_gerais'] = data.get('dados_gerais') or data.get('DADOS_GERAIS') or {}
    return out

def sanitize_socios_for_storage(data):
    """
    Remove dados de contato dos socios. Mantém apenas NOME, CARGO, DOCUMENTO (e variantes).
    Preserva cpf_enriched e cpf_data quando existem (dados do nosso enriquecimento pago).
    
    REGRA: Contatos só após o usuário pagar por "Buscar informações dos sócios".
    
    Args:
        data: Dict {'socios': [...]} ou lista [...] de socios
        
    Returns:
        Mesma estrutura com socios sanitizados
    """
    if data is None:
        return None
    
    # Normalizar para lista de socios
    if isinstance(data, list):
        socios_list = data
        return_list = True
    elif isinstance(data, dict) and 'socios' in data:
        socios_list = data.get('socios', [])
        if not isinstance(socios_list, list):
            socios_list = [socios_list] if socios_list else []
        return_list = False
    else:
        return data
    
    sanitized_socios = []
    for socio in socios_list:
        if not isinstance(socio, dict):
            sanitized_socios.append(socio)
            continue
        clean = {}
        for k, v in socio.items():
            if k in SOCIOS_CONTACT_KEYS_TO_STRIP:
                continue
            if k in SOCIOS_ALLOWED_KEYS:
                clean[k] = v
            elif k.upper() in ('NOME', 'CARGO', 'DOCUMENTO', 'CPF', 'QUALIFICACAO'):
                clean[k] = v
            # cpf_enriched e cpf_data são do nosso enriquecimento - preservar
            elif k in ('cpf_enriched', 'cpf_data'):
                clean[k] = v
        sanitized_socios.append(clean)
    
    if return_list:
        return sanitized_socios
    return {'socios': sanitized_socios}
