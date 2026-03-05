"""
Testes unitários para lead_extractor.services.serper_service (sem chamadas HTTP).
"""
from django.test import SimpleTestCase

from lead_extractor.services.serper_service import (
    _normalize_company_name_for_cache,
    normalize_places_response,
)


class SerperServiceTest(SimpleTestCase):
    """Testes de funções que não dependem de API externa."""

    def test_normalize_company_name_empty(self):
        self.assertEqual(_normalize_company_name_for_cache(''), '')
        self.assertEqual(_normalize_company_name_for_cache(None), '')

    def test_normalize_company_name_not_string(self):
        self.assertEqual(_normalize_company_name_for_cache(123), '')

    def test_normalize_company_name_strip_and_collapse(self):
        self.assertEqual(_normalize_company_name_for_cache('  Empresa  XYZ  '), 'Empresa XYZ')

    def test_normalize_places_response_search_places_key(self):
        data = {'places': [{'title': 'A', 'address': 'Rua 1'}]}
        out = normalize_places_response(data, source='search')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['title'], 'A')
        self.assertEqual(out[0]['address'], 'Rua 1')
        self.assertEqual(out[0]['phoneNumber'], '')

    def test_normalize_places_response_search_local_pack_places(self):
        data = {'localPack': {'places': [{'name': 'B', 'formattedAddress': 'Av 2'}]}}
        out = normalize_places_response(data, source='search')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['title'], 'B')
        self.assertEqual(out[0]['address'], 'Av 2')
        self.assertEqual(out[0]['phoneNumber'], '')

    def test_normalize_places_response_places_source_list(self):
        data = [{'title': 'C', 'phone': '11999999999'}]
        out = normalize_places_response(data, source='places')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['title'], 'C')
        self.assertEqual(out[0]['phoneNumber'], '11999999999')

    def test_normalize_places_response_places_source_dict(self):
        data = {'places': [{'title': 'D'}]}
        out = normalize_places_response(data, source='places')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['title'], 'D')

    def test_normalize_places_response_empty(self):
        self.assertEqual(normalize_places_response({}, source='search'), [])
        self.assertEqual(normalize_places_response({'localPack': {}}, source='search'), [])
