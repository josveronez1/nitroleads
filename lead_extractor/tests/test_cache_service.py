"""
Testes para lead_extractor.services.cache_service.
"""
from django.test import TestCase

from lead_extractor.models import (
    CachedSearch,
    NormalizedNiche,
    Search,
    UserProfile,
)
from lead_extractor.services.cache_service import (
    get_or_create_normalized_niche,
    get_cached_search,
    create_cached_search,
    get_cnpjs_from_user_last_3_searches,
    cleanup_old_search_accesses,
)


class CacheServiceTest(TestCase):
    """Testes do serviço de cache (niche, CachedSearch, deduplicação)."""

    def setUp(self):
        self.user = UserProfile.objects.create(
            supabase_user_id='test_user',
            email='test_cache@example.com',
            credits=100,
        )

    def test_get_or_create_normalized_niche_creates(self):
        obj = get_or_create_normalized_niche('Advogado')
        self.assertIsNotNone(obj)
        self.assertEqual(obj.name, 'advogado')
        self.assertEqual(obj.display_name, 'Advogado')
        self.assertTrue(obj.is_active)

    def test_get_or_create_normalized_niche_reuses(self):
        a1 = get_or_create_normalized_niche('Advogado')
        a2 = get_or_create_normalized_niche('advogado')
        self.assertEqual(a1.id, a2.id)
        self.assertEqual(NormalizedNiche.objects.count(), 1)

    def test_get_or_create_normalized_niche_empty_returns_none(self):
        self.assertIsNone(get_or_create_normalized_niche(''))
        self.assertIsNone(get_or_create_normalized_niche(None))

    def test_get_cached_search_none_when_empty_params(self):
        self.assertIsNone(get_cached_search('', 'São Paulo - SP'))
        self.assertIsNone(get_cached_search('advogado', None))

    def test_get_cached_search_returns_existing(self):
        create_cached_search('advogado', 'São Paulo - SP', 10)
        cached = get_cached_search('advogado', 'São Paulo - SP')
        self.assertIsNotNone(cached)
        self.assertEqual(cached.niche_normalized, 'advogado')
        self.assertEqual(cached.location_normalized, 'São Paulo - SP')
        self.assertEqual(cached.total_leads_cached, 10)

    def test_create_cached_search_creates_and_updates(self):
        c1 = create_cached_search('advogado', 'Rio - RJ', 5)
        self.assertEqual(c1.total_leads_cached, 5)
        c2 = create_cached_search('advogado', 'Rio - RJ', 20)
        self.assertEqual(c2.id, c1.id)
        c2.refresh_from_db()
        self.assertEqual(c2.total_leads_cached, 20)

    def test_get_cnpjs_from_user_last_3_searches_empty(self):
        result = get_cnpjs_from_user_last_3_searches(self.user)
        self.assertEqual(result, set())

    def test_get_cnpjs_from_user_last_3_searches_with_search(self):
        search = Search.objects.create(
            user=self.user,
            niche='advogado',
            location='São Paulo - SP',
            quantity_requested=10,
            status='completed',
        )
        # Sem SearchLead/LeadAccess ainda retorna set vazio de CNPJs
        result = get_cnpjs_from_user_last_3_searches(self.user)
        self.assertEqual(result, set())
        result_exclude = get_cnpjs_from_user_last_3_searches(
            self.user, exclude_search_id=search.id
        )
        self.assertEqual(result_exclude, set())

    def test_cleanup_old_search_accesses_no_searches(self):
        deleted = cleanup_old_search_accesses(self.user)
        self.assertEqual(deleted, 0)
