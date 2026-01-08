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
def has_unenriched_partners(viper_data):
    """Verifica se há sócios com CPF que ainda não foram enriquecidos"""
    if not viper_data or not viper_data.get('socios_qsa') or not viper_data.get('socios_qsa', {}).get('socios'):
        return False
    for socio in viper_data['socios_qsa']['socios']:
        if socio.get('DOCUMENTO') and not socio.get('cpf_enriched'):
            return True
    return False