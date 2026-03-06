"""
Pacote de serviços do lead_extractor.
Re-exports para manter compatibilidade: from lead_extractor.services import ...
"""
from .search_service import (
    process_search_async,
    filter_existing_leads,
    search_incremental,
)
from .serper_service import search_google_maps, find_cnpj_by_name
from .viper_api import (
    enrich_company_viper,
    get_partners_internal,
    get_partners_internal_queued,
    wait_for_partners_processing,
    search_cpf_viper,
    search_cnpj_viper,
    sanitize_socios_for_storage,
)
from .normalization import normalize_niche, normalize_location
from .cache_service import (
    get_cached_search,
    create_cached_search,
    get_leads_from_cache,
    get_cnpjs_from_user_last_3_searches,
)
from .lead_sanitizer import sanitize_lead_data
from .auth_service import (
    authenticate_supabase_token,
    clear_user_session,
    get_user_profile_from_session,
    start_user_session,
)

__all__ = [
    'process_search_async',
    'filter_existing_leads',
    'search_incremental',
    'search_google_maps',
    'find_cnpj_by_name',
    'enrich_company_viper',
    'get_partners_internal',
    'get_partners_internal_queued',
    'wait_for_partners_processing',
    'search_cpf_viper',
    'search_cnpj_viper',
    'sanitize_socios_for_storage',
    'normalize_niche',
    'normalize_location',
    'get_cached_search',
    'create_cached_search',
    'get_leads_from_cache',
    'get_cnpjs_from_user_last_3_searches',
    'sanitize_lead_data',
    'authenticate_supabase_token',
    'clear_user_session',
    'get_user_profile_from_session',
    'start_user_session',
]
