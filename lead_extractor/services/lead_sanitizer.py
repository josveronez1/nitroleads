"""
Sanitização de dados de leads. Remove dados sensíveis até enriquecimento pago.
"""
import copy
import logging

logger = logging.getLogger(__name__)


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
    sanitized = copy.deepcopy(lead_data)

    if show_partners and not has_enriched_access:
        has_enriched_access = True

    if 'viper_data' in sanitized and sanitized['viper_data']:
        viper_data = sanitized['viper_data'].copy()

        if not has_enriched_access:
            viper_data.pop('telefones', None)
            viper_data.pop('emails', None)

        if not has_enriched_access:
            viper_data.pop('socios_qsa', None)

        viper_data.pop('enderecos', None)
        sanitized['viper_data'] = viper_data

    return sanitized
