import re
import unicodedata
import logging

from lead_extractor.models import NormalizedLocation

logger = logging.getLogger(__name__)


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