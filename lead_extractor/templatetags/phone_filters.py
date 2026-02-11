from django import template
import re

register = template.Library()

@register.filter
def format_phone(value):
    """
    Formata números de telefone e adiciona ícones.
    Entrada: 55999998888 ou 5533334444
    Saída: HTML com ícone e formato (XX) XXXXX-XXXX
    """
    if not value:
        return ""
    
    # Remove tudo que não é número
    nums = re.sub(r'\D', '', str(value))
    
    # Se começar com 55 (Brasil), remove para formatar melhor o DDD
    if len(nums) > 10 and nums.startswith('55'):
        nums = nums[2:]
        
    icon = '<i class="fas fa-phone me-1"></i>' # Padrão fixo
    formatted = nums
    
    # Lógica para formatar
    if len(nums) == 11: # Celular (DDD + 9 dígitos)
        icon = '<i class="fas fa-mobile-alt me-1"></i>'
        formatted = f"({nums[:2]}) {nums[2:7]}-{nums[7:]}"
    elif len(nums) == 10: # Fixo (DDD + 8 dígitos)
        icon = '<i class="fas fa-phone me-1"></i>'
        formatted = f"({nums[:2]}) {nums[2:6]}-{nums[6:]}"
        
    from django.utils.safestring import mark_safe
    return mark_safe(f"{icon} {formatted}")

@register.filter
def get_emails(viper_data):
    """Extrai lista de emails do JSON do Viper"""
    if not viper_data:
        return []
    return viper_data.get('emails', [])

@register.filter
def get_phones(viper_data):
    """Extrai lista de telefones do JSON do Viper"""
    if not viper_data:
        return []
    # Remove duplicados e strings vazias
    phones = viper_data.get('telefones', [])
    return list(set([p for p in phones if p]))


@register.filter
def slice_list(value, arg):
    """Retorna os primeiros N itens da lista (ex: {{ list|slice_list:2 }})"""
    try:
        n = int(arg)
        if isinstance(value, list):
            return value[:n]
        return value if value else []
    except (TypeError, ValueError):
        return value


@register.filter
def slice_list_rest(value, arg):
    """Retorna os itens da lista a partir do índice N (ex: {{ list|slice_list_rest:2 }})"""
    try:
        n = int(arg)
        if isinstance(value, list):
            return value[n:]
        return []
    except (TypeError, ValueError):
        return []

@register.filter
def has_unenriched_partners(viper_data):
    """Verifica se há sócios com CPF que ainda não foram enriquecidos"""
    if not viper_data or not viper_data.get('socios_qsa') or not viper_data.get('socios_qsa', {}).get('socios'):
        return False
    for socio in viper_data['socios_qsa']['socios']:
        if socio.get('DOCUMENTO') and not socio.get('cpf_enriched'):
            return True
    return False

@register.filter
def get_unique_phones(cpf_data):
    """
    Retorna telefones únicos, priorizando WhatsApp quando há duplicatas.
    Retorna lista de dicts: [{'phone': '123', 'type': 'whatsapp'}, ...]
    """
    if not cpf_data:
        return []
    
    # Normalizar números (remover caracteres não numéricos)
    def normalize_phone(phone):
        if not phone:
            return None
        return re.sub(r'\D', '', str(phone))
    
    # Coletar todos os telefones com seus tipos
    phones_dict = {}  # {numero_normalizado: {'phone': original, 'type': tipo}}
    
    # Processar WhatsApp primeiro (maior prioridade)
    for phone in cpf_data.get('whatsapps', []):
        normalized = normalize_phone(phone)
        if normalized:
            phones_dict[normalized] = {'phone': phone, 'type': 'whatsapp'}
    
    # Processar móveis (menor prioridade que WhatsApp)
    for phone in cpf_data.get('telefones_moveis', []):
        normalized = normalize_phone(phone)
        if normalized and normalized not in phones_dict:
            phones_dict[normalized] = {'phone': phone, 'type': 'movel'}
    
    # Processar fixos (menor prioridade)
    for phone in cpf_data.get('telefones_fixos', []):
        normalized = normalize_phone(phone)
        if normalized and normalized not in phones_dict:
            phones_dict[normalized] = {'phone': phone, 'type': 'fixo'}
    
    return list(phones_dict.values())