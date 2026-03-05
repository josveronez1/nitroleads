"""
Testes para lead_extractor.services.lead_sanitizer.
"""
from django.test import TestCase

from lead_extractor.services.lead_sanitizer import sanitize_lead_data


class LeadSanitizerTest(TestCase):
    """Testes de sanitização de dados de lead (ocultar QSA/telefones até enriquecimento)."""

    def test_empty_dict_unchanged(self):
        self.assertEqual(sanitize_lead_data({}), {})

    def test_no_viper_data_unchanged(self):
        data = {'name': 'Empresa', 'cnpj': '123'}
        self.assertEqual(sanitize_lead_data(data), data)

    def test_viper_data_without_enriched_hides_socios(self):
        data = {
            'viper_data': {
                'socios_qsa': [{'NOME': 'Fulano'}],
                'telefones': ['11999999999'],
                'emails': ['a@b.com'],
            }
        }
        out = sanitize_lead_data(data, has_enriched_access=False)
        self.assertNotIn('socios_qsa', out['viper_data'])
        self.assertNotIn('telefones', out['viper_data'])
        self.assertNotIn('emails', out['viper_data'])

    def test_viper_data_with_enriched_shows_socios(self):
        data = {
            'viper_data': {
                'socios_qsa': [{'NOME': 'Fulano'}],
                'telefones': ['11999999999'],
            }
        }
        out = sanitize_lead_data(data, has_enriched_access=True)
        self.assertEqual(out['viper_data']['socios_qsa'], [{'NOME': 'Fulano'}])
        self.assertEqual(out['viper_data']['telefones'], ['11999999999'])

    def test_show_partners_deprecated_acts_like_has_enriched(self):
        data = {'viper_data': {'socios_qsa': [{'NOME': 'X'}]}}
        out = sanitize_lead_data(data, show_partners=True)
        self.assertIn('socios_qsa', out['viper_data'])

    def test_enderecos_always_removed(self):
        data = {'viper_data': {'enderecos': [{'rua': 'X'}], 'socios_qsa': []}}
        out = sanitize_lead_data(data, has_enriched_access=True)
        self.assertNotIn('enderecos', out['viper_data'])

    def test_does_not_mutate_original(self):
        data = {'viper_data': {'socios_qsa': [{'NOME': 'Y'}]}}
        sanitize_lead_data(data, has_enriched_access=False)
        self.assertIn('socios_qsa', data['viper_data'])
