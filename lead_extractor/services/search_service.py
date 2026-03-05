"""
Orquestração de busca: filter_existing_leads, search_incremental, process_search_async.
"""
import logging
import re

from django.utils import timezone

from lead_extractor.models import Lead, Search, SearchLead, LeadAccess
from lead_extractor.credit_service import debit_credits
from lead_extractor.services.serper_service import (
    search_google_maps_paginated,
    search_google_hybrid,
    find_cnpj_by_name,
    _normalize_company_name_for_cache,
)
from lead_extractor.services.viper_api import (
    enrich_company_viper,
    get_partners_internal,
    search_cpf_viper,
    _normalize_cpf_api_response,
)
from lead_extractor.services.normalization import normalize_niche, normalize_location
from lead_extractor.services.cache_service import (
    get_cached_search,
    create_cached_search,
    get_existing_leads_from_db,
    get_leads_from_cache,
    get_cnpjs_from_user_last_3_searches,
)
from lead_extractor.services.lead_sanitizer import sanitize_lead_data

logger = logging.getLogger(__name__)


def filter_existing_leads(user_profile, new_places):
    """
    Retorna lugares do Google Maps e CNPJs globais existentes.
    NÃO faz buscas no Serper - apenas retorna dados para processamento posterior.

    Args:
        user_profile: Objeto UserProfile (não usado, mantido para compatibilidade)
        new_places: Lista de lugares retornados pelo Google Maps

    Returns:
        tuple: (filtered_places: list, existing_cnpjs: set)
    """
    if not new_places:
        return [], set()

    global_cnpjs = set(
        Lead.objects.exclude(cnpj__isnull=True)
        .exclude(cnpj='')
        .values_list('cnpj', flat=True)
    )

    return new_places, global_cnpjs


def search_incremental(search_term, user_profile, quantity, existing_cnpjs, location=None):
    """
    Busca incremental apenas os leads que ainda não foram encontrados.
    Usa paginação se necessário. Inclui cache de CNPJs para evitar buscas repetidas no Serper.

    Args:
        search_term: Termo de busca para Google Maps
        user_profile: UserProfile do usuário
        quantity: Quantidade adicional necessária
        existing_cnpjs: Set de CNPJs já existentes para evitar duplicatas
        location: Localização da pesquisa para desambiguar CNPJ por nome

    Returns:
        tuple: (lista de novos places, set atualizado de existing_cnpjs)
    """
    cnpj_cache = {}
    MAX_SERPER_CALLS = 50
    MAX_ITERATIONS_WITHOUT_NEW = 10
    serper_calls = 0
    iterations_without_new = 0

    max_results = min(quantity * 3, 50)
    places = search_google_maps_paginated(search_term, max_results, max_pages=5)

    filtered_places, global_cnpjs = filter_existing_leads(user_profile, places)
    existing_cnpjs.update(global_cnpjs)

    new_places = []
    for place in filtered_places:
        if serper_calls >= MAX_SERPER_CALLS:
            logger.warning(f"Limite de chamadas ao Serper atingido ({MAX_SERPER_CALLS}) na busca incremental. Parando busca.")
            break

        if iterations_without_new >= MAX_ITERATIONS_WITHOUT_NEW:
            logger.info(f"Limite de iterações sem novos leads atingido ({MAX_ITERATIONS_WITHOUT_NEW}) na busca incremental. Parando busca.")
            break

        company_name = place.get('title', '')
        name_key = _normalize_company_name_for_cache(company_name)

        if name_key in cnpj_cache:
            cnpj = cnpj_cache[name_key]
        else:
            cnpj = find_cnpj_by_name(company_name, location=location)
            serper_calls += 1
            cnpj_cache[name_key] = cnpj

        if cnpj and cnpj not in existing_cnpjs:
            new_places.append(place)
            existing_cnpjs.add(cnpj)
            iterations_without_new = 0
            if len(new_places) >= quantity:
                break
        else:
            iterations_without_new += 1

    logger.info(f"Busca incremental concluída: {len(new_places)} novos leads encontrados, {serper_calls} chamadas ao Serper")
    return new_places, existing_cnpjs


def process_search_async(search_id):
    """
    Processa uma busca de forma assíncrona em background.
    Esta função roda em uma thread separada.

    Args:
        search_id: ID do objeto Search a processar
    """
    try:
        search_obj = Search.objects.get(id=search_id)
        user_profile = search_obj.user

        search_obj.status = 'processing'
        search_obj.processing_started_at = timezone.now()
        search_obj.save(update_fields=['status', 'processing_started_at'])

        niche = search_obj.niche
        location = search_obj.location
        quantity = search_obj.quantity_requested
        is_onboarding = search_obj.search_data.get('onboarding') is True
        if is_onboarding:
            quantity = min(quantity, 5)
        search_term = f"{niche} em {location}"

        niche_normalized = normalize_niche(niche)
        location_normalized = normalize_location(location)

        credits_used = 0
        leads_processed = 0
        existing_cnpjs = get_cnpjs_from_user_last_3_searches(user_profile, exclude_search_id=search_id)
        results = []
        cached_search = None

        if niche_normalized and location_normalized:
            existing_leads, cached_search = get_existing_leads_from_db(
                niche_normalized, location_normalized, quantity, user_profile, search_obj
            )

            if existing_leads:
                for company_data in existing_leads:
                    cnpj = company_data.get('cnpj')
                    if cnpj:
                        lead_access = LeadAccess.objects.filter(
                            user=user_profile,
                            lead__cnpj=cnpj,
                            search=search_obj
                        ).first()

                        if lead_access and lead_access.credits_paid > 0:
                            credits_used += 1

                        existing_cnpjs.add(cnpj)

                    leads_processed += 1
                    results.append(company_data)

                logger.info(f"Leads existentes encontrados: {leads_processed} leads retornados da base (solicitado: {quantity})")
                search_obj.results_count = SearchLead.objects.filter(search=search_obj).count()
                search_obj.credits_used = credits_used
                search_obj.save(update_fields=['results_count', 'credits_used'])

        if cached_search:
            search_obj.cached_search = cached_search
            search_obj.save(update_fields=['cached_search'])

        if leads_processed >= quantity:
            logger.info(f"Leads suficientes encontrados na base ({leads_processed}). Não fazendo busca no Serper.")
        else:
            additional_needed = quantity - leads_processed
            logger.info(f"Leads insuficientes na base ({leads_processed}/{quantity}). Buscando {additional_needed} leads adicionais no Serper.")
            cnpj_cache = {}
            serper_cnpj_calls = 0
            places = []
            processed_cnpjs_in_search = set()

            use_cache = False
            if cached_search and cached_search.total_leads_cached >= additional_needed:
                use_cache = True
                logger.info("Usando cache do CachedSearch para buscar leads adicionais.")

            if use_cache:
                cached_results = get_leads_from_cache(
                    cached_search, user_profile, additional_needed, search_obj,
                    extra_exclude_cnpjs=existing_cnpjs
                )

                for company_data in cached_results:
                    cnpj = company_data.get('cnpj')
                    if cnpj:
                        lead_access = LeadAccess.objects.filter(
                            user=user_profile,
                            lead__cnpj=cnpj,
                            search=search_obj
                        ).first()

                        if lead_access and lead_access.credits_paid > 0:
                            credits_used += 1

                        existing_cnpjs.add(cnpj)

                    leads_processed += 1
                    results.append(company_data)

                    if leads_processed >= quantity:
                        break

                num_from_cache = len(cached_results)
                logger.info(f"Cache usado: {num_from_cache} leads adicionais do cache (total: {leads_processed}/{quantity})")
                search_obj.results_count = SearchLead.objects.filter(search=search_obj).count()
                search_obj.credits_used = credits_used
                search_obj.save(update_fields=['results_count', 'credits_used'])

            if leads_processed < quantity:
                processed_cnpjs_in_search = set()
                for r in results:
                    c = r.get('cnpj')
                    if c:
                        processed_cnpjs_in_search.add(c)

                additional_needed = quantity - leads_processed
                places = search_google_maps_paginated(search_term, additional_needed)
                filtered_places, existing_cnpjs_set = filter_existing_leads(user_profile, places)
                existing_cnpjs.update(existing_cnpjs_set)

                results_per_page = 10
                pages_searched = (len(places) + results_per_page - 1) // results_per_page if places else 0
                api_calls_made = pages_searched

                search_obj.search_data.update({
                    'total_places_found': len(places),
                    'filtered_places': len(filtered_places),
                    'pages_searched': pages_searched,
                    'api_calls_made': api_calls_made,
                })
                search_obj.save(update_fields=['search_data'])

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

                    name_key = _normalize_company_name_for_cache(company_data['name'])
                    if name_key in cnpj_cache:
                        cnpj = cnpj_cache[name_key]
                    else:
                        cnpj = find_cnpj_by_name(company_data['name'], location=location)
                        serper_cnpj_calls += 1
                        cnpj_cache[name_key] = cnpj

                    if not cnpj:
                        logger.info(f"Lead '{company_data['name']}' não tem CNPJ, pulando e buscando mais leads...")
                        continue

                    if cnpj in processed_cnpjs_in_search:
                        continue
                    if cnpj in existing_cnpjs:
                        continue

                    company_data['cnpj'] = cnpj
                    public_data = enrich_company_viper(cnpj)
                    if public_data:
                        company_data['viper_data'].update(public_data)

                    existing_lead = Lead.objects.filter(cnpj=cnpj).first()

                    if existing_lead:
                        lead_obj = existing_lead
                        if public_data:
                            if not lead_obj.viper_data:
                                lead_obj.viper_data = {}
                            lead_obj.viper_data.update(public_data)
                            lead_obj.save(update_fields=['viper_data'])
                    else:
                        lead_obj = Lead.objects.create(
                            cached_search=cached_search,
                            name=company_data['name'],
                            address=company_data['address'],
                            phone_maps=company_data['phone_maps'],
                            cnpj=cnpj,
                            viper_data=company_data['viper_data']
                        )

                    credits_paid_val = 0 if is_onboarding else 1
                    lead_access, created = LeadAccess.objects.get_or_create(
                        user=user_profile,
                        lead=lead_obj,
                        defaults={
                            'search': search_obj,
                            'credits_paid': credits_paid_val,
                        }
                    )

                    if created and not is_onboarding:
                        success, new_balance, error = debit_credits(
                            user_profile,
                            1,
                            description=f"Lead: {company_data['name']}"
                        )
                        if not success:
                            logger.error(f"Débito de crédito falhou: {error}. Parando busca.")
                            break
                        credits_used += 1

                    SearchLead.objects.get_or_create(search=search_obj, lead=lead_obj)
                    sanitized_viper_data = sanitize_lead_data(
                        {'viper_data': lead_obj.viper_data or {}},
                        show_partners=(lead_access.enriched_at is not None)
                    ).get('viper_data', {})
                    company_data['viper_data'] = sanitized_viper_data
                    leads_processed += 1
                    processed_cnpjs_in_search.add(cnpj)
                    results.append(company_data)

                    if leads_processed % 5 == 0:
                        search_obj.results_count = SearchLead.objects.filter(search=search_obj).count()
                        search_obj.credits_used = credits_used
                        search_obj.save(update_fields=['results_count', 'credits_used'])

                    if not cached_search:
                        cached_search = create_cached_search(niche_normalized, location_normalized, 0)
                        search_obj.cached_search = cached_search
                        search_obj.save(update_fields=['cached_search'])

                    if lead_obj.cached_search != cached_search:
                        lead_obj.cached_search = cached_search
                        lead_obj.save(update_fields=['cached_search'])

                if serper_cnpj_calls or pages_searched:
                    logger.info(f"Serper: {pages_searched} páginas + {serper_cnpj_calls} find_cnpj (cache: {len(cnpj_cache)} nomes)")

            if cached_search:
                total_leads = Lead.objects.filter(
                    cached_search=cached_search,
                    cnpj__isnull=False
                ).exclude(cnpj='').values('cnpj').distinct().count()

                if cached_search.total_leads_cached != total_leads:
                    cached_search.total_leads_cached = total_leads
                    cached_search.save(update_fields=['total_leads_cached', 'last_updated'])

        if cached_search and niche_normalized and location_normalized:
            total_leads = Lead.objects.filter(
                cached_search=cached_search,
                cnpj__isnull=False
            ).exclude(cnpj='').values('cnpj').distinct().count()

            if cached_search.total_leads_cached != total_leads:
                cached_search.total_leads_cached = total_leads
                cached_search.save(update_fields=['total_leads_cached', 'last_updated'])

        if leads_processed < quantity:
            additional_needed = quantity - leads_processed
            logger.info(f"Faltam {additional_needed} leads, iniciando busca incremental...")

            results_per_page = 10
            pages_from_paginated = (len(places) + results_per_page - 1) // results_per_page if places else 0
            start_page = 1 + pages_from_paginated
            incremental_iteration = 0
            max_incremental_iterations = 20
            max_api_requests = 50
            consecutive_empty_iterations = 0
            max_consecutive_empty = 5
            api_requests_made = 0

            while leads_processed < quantity and incremental_iteration < max_incremental_iterations:
                if api_requests_made >= max_api_requests:
                    logger.warning(f"Limite de requisições à API atingido ({max_api_requests}). Parando busca incremental.")
                    break

                pages_per_iteration = 5
                incremental_places_batch = []
                for i in range(pages_per_iteration):
                    if leads_processed >= quantity or api_requests_made >= max_api_requests:
                        break
                    page_num = start_page + incremental_iteration * pages_per_iteration + i
                    logger.info(f"Busca incremental (iteração {incremental_iteration + 1}, page: {page_num})...")
                    places_page = search_google_hybrid(search_term, num=results_per_page, page=page_num)
                    api_requests_made += 1

                    if not places_page:
                        logger.info(f"Não há mais resultados na página {page_num}.")
                        break
                    incremental_places_batch.extend(places_page)
                    if len(places_page) < results_per_page:
                        break

                if not incremental_places_batch:
                    consecutive_empty_iterations += 1
                    logger.info(f"Nenhum resultado nesta iteração. Vazias: {consecutive_empty_iterations}/{max_consecutive_empty}")
                    if consecutive_empty_iterations >= max_consecutive_empty:
                        logger.warning(f"Parando busca incremental: {max_consecutive_empty} iterações sem resultados.")
                        break
                    incremental_iteration += 1
                    continue

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

                    name_key = _normalize_company_name_for_cache(company_data['name'])
                    if name_key in cnpj_cache:
                        cnpj = cnpj_cache[name_key]
                    else:
                        cnpj = find_cnpj_by_name(company_data['name'], location=location)
                        serper_cnpj_calls += 1
                        cnpj_cache[name_key] = cnpj

                    if not cnpj:
                        leads_without_cnpj += 1
                        continue
                    if cnpj in processed_cnpjs_in_search:
                        leads_duplicated += 1
                        continue
                    if cnpj in existing_cnpjs:
                        leads_duplicated += 1
                        continue

                    company_data['cnpj'] = cnpj
                    public_data = enrich_company_viper(cnpj)
                    if public_data:
                        company_data['viper_data'].update(public_data)

                    existing_lead = Lead.objects.filter(cnpj=cnpj).first()

                    if existing_lead:
                        lead_obj = existing_lead
                        if public_data:
                            if not lead_obj.viper_data:
                                lead_obj.viper_data = {}
                            lead_obj.viper_data.update(public_data)
                            lead_obj.save(update_fields=['viper_data'])
                    else:
                        lead_obj = Lead.objects.create(
                            name=company_data['name'],
                            address=company_data['address'],
                            phone_maps=company_data['phone_maps'],
                            cnpj=cnpj,
                            viper_data=company_data['viper_data']
                        )

                    credits_paid_val = 0 if is_onboarding else 1
                    lead_access, created = LeadAccess.objects.get_or_create(
                        user=user_profile,
                        lead=lead_obj,
                        defaults={
                            'search': search_obj,
                            'credits_paid': credits_paid_val,
                        }
                    )

                    if created and not is_onboarding:
                        success, new_balance, error = debit_credits(
                            user_profile,
                            1,
                            description=f"Lead: {company_data['name']}"
                        )
                        if not success:
                            logger.error(f"Débito de crédito falhou: {error}. Parando busca incremental.")
                            break
                        credits_used += 1

                    SearchLead.objects.get_or_create(search=search_obj, lead=lead_obj)
                    sanitized_viper_data = sanitize_lead_data(
                        {'viper_data': lead_obj.viper_data or {}},
                        show_partners=(lead_access.enriched_at is not None)
                    ).get('viper_data', {})
                    company_data['viper_data'] = sanitized_viper_data
                    leads_processed += 1
                    processed_cnpjs_in_search.add(cnpj)
                    existing_cnpjs.add(cnpj)
                    leads_found_in_batch += 1
                    results.append(company_data)

                    if leads_processed % 5 == 0:
                        search_obj.results_count = SearchLead.objects.filter(search=search_obj).count()
                        search_obj.credits_used = credits_used
                        search_obj.save(update_fields=['results_count', 'credits_used'])

                if leads_found_in_batch > 0:
                    consecutive_empty_iterations = 0
                    logger.info(f"Busca incremental: {leads_found_in_batch} leads válidos, {leads_without_cnpj} sem CNPJ, {leads_duplicated} duplicados. Total: {leads_processed}/{quantity} (requisições: {api_requests_made}/{max_api_requests})")
                else:
                    consecutive_empty_iterations += 1
                    logger.info(f"Busca incremental: nenhum lead válido encontrado ({leads_without_cnpj} sem CNPJ, {leads_duplicated} duplicados). Iterações vazias: {consecutive_empty_iterations}/{max_consecutive_empty}")

                    if consecutive_empty_iterations >= max_consecutive_empty:
                        logger.warning(f"Parando busca incremental: {max_consecutive_empty} iterações consecutivas sem encontrar leads válidos.")
                        break

                incremental_iteration += 1
                if leads_processed >= quantity:
                    break

            if leads_processed < quantity:
                logger.info(f"Busca incremental concluída: {leads_processed}/{quantity} leads. Requisições Serper: {api_requests_made} places + {serper_cnpj_calls} find_cnpj (cache: {len(cnpj_cache)} nomes)")

        if is_onboarding:
            first_two = list(
                SearchLead.objects.filter(search=search_obj).order_by('id').select_related('lead')[:2]
            )
            for search_lead in first_two:
                lead_obj = search_lead.lead
                if not lead_obj or not lead_obj.cnpj:
                    continue
                result = get_partners_internal(lead_obj.cnpj, retry=True)
                if result is None:
                    continue
                if isinstance(result, list):
                    normalized_result = {'socios': result}
                elif isinstance(result, dict) and 'socios' in result:
                    normalized_result = result
                elif isinstance(result, dict):
                    normalized_result = {'socios': [result]} if result else {'socios': []}
                else:
                    normalized_result = {'socios': []}
                if not lead_obj.viper_data:
                    lead_obj.viper_data = {}
                lead_obj.viper_data['socios_qsa'] = normalized_result
                for socio in normalized_result.get('socios') or []:
                    if not isinstance(socio, dict):
                        continue
                    cpf = socio.get('DOCUMENTO') or socio.get('CPF') or socio.get('documento') or socio.get('cpf')
                    cpf_clean = re.sub(r'\D', '', str(cpf)) if cpf else ''
                    if len(cpf_clean) != 11:
                        continue
                    cpf_data_raw = search_cpf_viper(cpf_clean)
                    if cpf_data_raw:
                        socio['cpf_data'] = _normalize_cpf_api_response(cpf_data_raw)
                        socio['cpf_enriched'] = True
                lead_obj.save(update_fields=['viper_data'])
                logger.info(f"Onboarding: QSA completo (com telefones dos sócios) salvo no lead {lead_obj.id} (CNPJ {lead_obj.cnpj})")

        search_obj.results_count = SearchLead.objects.filter(search=search_obj).count()
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

    except Search.DoesNotExist:
        logger.error(f"Search {search_id} não encontrado")
    except Exception as e:
        logger.error(f"Erro ao processar busca {search_id}: {e}", exc_info=True)
        try:
            search_obj = Search.objects.get(id=search_id)
            search_obj.status = 'failed'
            search_obj.save(update_fields=['status'])
        except Exception:
            pass
