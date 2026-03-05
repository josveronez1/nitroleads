"""
Serviço de cache de buscas e leads. CachedSearch, NormalizedNiche, deduplicação por usuário.
"""
import logging

from django.utils import timezone

from lead_extractor.models import (
    CachedSearch,
    Lead,
    LeadAccess,
    NormalizedNiche,
    NormalizedLocation,
    Search,
    SearchLead,
)
from lead_extractor.credit_service import debit_credits
from lead_extractor.services.normalization import normalize_niche
from lead_extractor.services.lead_sanitizer import sanitize_lead_data

logger = logging.getLogger(__name__)


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
    try:
        last_3_searches = Search.objects.filter(
            user=user_profile
        ).order_by('-created_at')[:3]

        if not last_3_searches.exists():
            return 0

        last_3_search_ids = set(last_3_searches.values_list('id', flat=True))

        deleted_count = LeadAccess.objects.filter(
            user=user_profile,
            search__isnull=False
        ).exclude(search_id__in=last_3_search_ids).delete()[0]

        logger.info(
            f"cleanup_old_search_accesses: deletados {deleted_count} LeadAccess de pesquisas antigas para usuário {user_profile.id}"
        )
        return deleted_count
    except Exception as e:
        logger.error(f"Erro ao limpar LeadAccess de pesquisas antigas: {e}", exc_info=True)
        return 0


def get_cnpjs_from_user_last_3_searches(user_profile, exclude_search_id=None):
    """
    Retorna set de CNPJs que o usuário já viu nas últimas 3 pesquisas.
    Usado para deduplicação: não retornar o mesmo lead se está nas últimas 3 buscas.

    Args:
        user_profile: UserProfile do usuário
        exclude_search_id: ID da busca atual (excluir da contagem)

    Returns:
        set: CNPJs a excluir da busca atual
    """
    last_searches = Search.objects.filter(
        user=user_profile
    ).exclude(
        id=exclude_search_id
    ).order_by('-created_at')[:3]

    if not last_searches:
        return set()

    search_ids = [s.id for s in last_searches]

    cnpjs_from_searchlead = set(
        SearchLead.objects.filter(search_id__in=search_ids)
        .values_list('lead__cnpj', flat=True)
    )
    cnpjs_from_leadaccess = set(
        LeadAccess.objects.filter(search_id__in=search_ids)
        .exclude(lead__cnpj__isnull=True)
        .exclude(lead__cnpj='')
        .values_list('lead__cnpj', flat=True)
    )

    return cnpjs_from_searchlead | cnpjs_from_leadaccess


def get_existing_leads_from_db(niche_normalized, location_normalized, quantity, user_profile, search_obj=None):
    """
    Busca leads existentes na base de dados global que correspondem à busca.
    Filtra leads que o usuário já tem acesso nas 3 últimas pesquisas.

    Args:
        niche_normalized: Nicho normalizado (ex: "advogado")
        location_normalized: Localização normalizada (ex: "sao paulo - sp")
        quantity: Quantidade desejada
        user_profile: UserProfile do usuário
        search_obj: Objeto Search (opcional, para vincular LeadAccess)

    Returns:
        tuple: (lista de leads encontrados, cached_search criado/atualizado)
    """
    if not niche_normalized or not location_normalized:
        return [], None

    try:
        cleanup_old_search_accesses(user_profile)

        exclude_cnpjs = get_cnpjs_from_user_last_3_searches(
            user_profile, exclude_search_id=search_obj.id if search_obj else None
        )

        cached_search = get_cached_search(niche_normalized, location_normalized)

        if cached_search:
            leads_query = Lead.objects.filter(
                cached_search=cached_search,
                cnpj__isnull=False
            ).exclude(cnpj='')
        else:
            return [], None

        available_leads = leads_query.exclude(
            cnpj__in=exclude_cnpjs
        ).order_by('-created_at')[:quantity * 3]

        results = []
        cnpjs_processed = set()

        for lead in available_leads:
            if len(results) >= quantity:
                break

            cnpj = lead.cnpj

            if cnpj in cnpjs_processed:
                continue
            cnpjs_processed.add(cnpj)

            skip_debit = bool(search_obj and search_obj.search_data.get('onboarding'))
            credits_to_set = 0 if skip_debit else 1
            lead_access, created = LeadAccess.objects.get_or_create(
                user=user_profile,
                lead=lead,
                defaults={
                    'search': search_obj,
                    'credits_paid': credits_to_set,
                }
            )

            if created and not skip_debit:
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Lead (base existente): {lead.name}"
                )
                if not success:
                    logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")

            if search_obj:
                SearchLead.objects.get_or_create(search=search_obj, lead=lead)

            sanitized_viper_data = sanitize_lead_data(
                {'viper_data': lead.viper_data or {}},
                show_partners=(lead_access.enriched_at is not None)
            ).get('viper_data', {})

            company_data = {
                'name': lead.name,
                'address': lead.address,
                'phone_maps': lead.phone_maps,
                'cnpj': cnpj,
                'viper_data': sanitized_viper_data
            }

            results.append(company_data)

        if results and cached_search:
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


def get_leads_from_cache(cached_search, user_profile, quantity, search_obj=None, extra_exclude_cnpjs=None):
    """
    Busca leads globais de um CachedSearch e cria LeadAccess para rastrear acesso.
    Retorna leads com dados sanitizados.
    extra_exclude_cnpjs: CNPJs já usados nesta busca (ex.: da base).

    Args:
        cached_search: Objeto CachedSearch
        user_profile: UserProfile do usuário
        quantity: Quantidade desejada
        search_obj: Objeto Search (opcional)
        extra_exclude_cnpjs: set ou iterable de CNPJs a excluir

    Returns:
        list: Lista de leads do cache (formato dict como no dashboard)
    """
    if not cached_search:
        return []

    try:
        exclude_cnpjs = set(get_cnpjs_from_user_last_3_searches(
            user_profile, exclude_search_id=search_obj.id if search_obj else None
        ))
        if extra_exclude_cnpjs:
            exclude_cnpjs.update(extra_exclude_cnpjs)
        accessed_cnpjs = set(
            LeadAccess.objects.filter(user=user_profile)
            .values_list('lead__cnpj', flat=True)
        )

        cached_leads_new = Lead.objects.filter(
            cached_search=cached_search,
            cnpj__isnull=False
        ).exclude(cnpj='').exclude(cnpj__in=exclude_cnpjs).order_by('-created_at')[:quantity * 3]

        results = []
        cnpjs_processed = set()

        for lead in cached_leads_new:
            if len(results) >= quantity:
                break

            cnpj = lead.cnpj

            if cnpj in cnpjs_processed:
                continue
            cnpjs_processed.add(cnpj)

            skip_debit = bool(search_obj and search_obj.search_data.get('onboarding'))
            credits_to_set = 0 if skip_debit else 1
            lead_access, created = LeadAccess.objects.get_or_create(
                user=user_profile,
                lead=lead,
                defaults={
                    'search': search_obj,
                    'credits_paid': credits_to_set,
                }
            )

            if created and not skip_debit:
                success, new_balance, error = debit_credits(
                    user_profile,
                    1,
                    description=f"Lead (cache): {lead.name}"
                )
                if not success:
                    logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")

            if search_obj:
                SearchLead.objects.get_or_create(search=search_obj, lead=lead)

            sanitized_viper_data = sanitize_lead_data(
                {'viper_data': lead.viper_data or {}},
                show_partners=(lead_access.enriched_at is not None)
            ).get('viper_data', {})

            company_data = {
                'name': lead.name,
                'address': lead.address,
                'phone_maps': lead.phone_maps,
                'cnpj': cnpj,
                'viper_data': sanitized_viper_data
            }

            results.append(company_data)

        if len(results) < quantity:
            additional_needed = quantity - len(results)
            cached_leads_accessed = Lead.objects.filter(
                cached_search=cached_search,
                cnpj__isnull=False,
                cnpj__in=accessed_cnpjs
            ).exclude(cnpj='').exclude(cnpj__in=cnpjs_processed).exclude(cnpj__in=exclude_cnpjs).order_by('-created_at')[:additional_needed * 2]

            for lead in cached_leads_accessed:
                if len(results) >= quantity:
                    break

                cnpj = lead.cnpj

                if cnpj in cnpjs_processed:
                    continue
                cnpjs_processed.add(cnpj)

                lead_access = LeadAccess.objects.filter(
                    user=user_profile,
                    lead=lead
                ).first()

                if not lead_access:
                    lead_access = LeadAccess.objects.create(
                        user=user_profile,
                        lead=lead,
                        search=search_obj,
                        credits_paid=0
                    )

                if search_obj:
                    SearchLead.objects.get_or_create(search=search_obj, lead=lead)

                sanitized_viper_data = sanitize_lead_data(
                    {'viper_data': lead.viper_data or {}},
                    show_partners=(lead_access.enriched_at is not None)
                ).get('viper_data', {})

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
