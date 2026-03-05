"""
Testes para lead_extractor.services.viper_api (funções que não chamam API externa).
"""
from django.test import SimpleTestCase

from lead_extractor.services.viper_api import (
    sanitize_socios_for_storage,
    _normalize_cpf_api_response,
)


class SanitizeSociosForStorageTest(SimpleTestCase):
    """Testes de sanitize_socios_for_storage: remove contatos dos sócios, mantém nome/cargo/doc."""

    def test_none_returns_none(self):
        self.assertIsNone(sanitize_socios_for_storage(None))

    def test_dict_with_socios_strips_contact_keys(self):
        data = {
            'socios': [
                {'NOME': 'Fulano', 'CARGO': 'Sócio', 'telefones': ['11999'], 'email': 'x@y.com'}
            ]
        }
        out = sanitize_socios_for_storage(data)
        self.assertIn('socios', out)
        self.assertEqual(len(out['socios']), 1)
        self.assertEqual(out['socios'][0]['NOME'], 'Fulano')
        self.assertEqual(out['socios'][0]['CARGO'], 'Sócio')
        self.assertNotIn('telefones', out['socios'][0])
        self.assertNotIn('email', out['socios'][0])

    def test_dict_with_socios_preserves_cpf_enriched_and_cpf_data(self):
        data = {
            'socios': [
                {'NOME': 'A', 'cpf_enriched': True, 'cpf_data': {'telefones_fixos': ['11999']}}
            ]
        }
        out = sanitize_socios_for_storage(data)
        self.assertTrue(out['socios'][0]['cpf_enriched'])
        self.assertEqual(out['socios'][0]['cpf_data'], {'telefones_fixos': ['11999']})

    def test_list_input_returns_list(self):
        data = [{'NOME': 'X', 'telefones': []}]
        out = sanitize_socios_for_storage(data)
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), 1)
        self.assertNotIn('telefones', out[0])

    def test_other_dict_unchanged(self):
        data = {'other': 'value'}
        self.assertEqual(sanitize_socios_for_storage(data), data)


class NormalizeCpfApiResponseTest(SimpleTestCase):
    """Testes de _normalize_cpf_api_response: normaliza resposta da API Viper (CPF)."""

    def test_empty_or_none(self):
        self.assertEqual(_normalize_cpf_api_response(None), {})
        self.assertEqual(_normalize_cpf_api_response({}), {})

    def test_not_dict(self):
        self.assertEqual(_normalize_cpf_api_response([]), {})

    def test_telefones_fixos_dict_with_telefone(self):
        data = {'telefones_fixos': {'TELEFONE': '11999999999'}}
        out = _normalize_cpf_api_response(data)
        self.assertEqual(out['telefones_fixos'], ['11999999999'])
        self.assertEqual(out['telefones_moveis'], [])
        self.assertEqual(out['whatsapps'], [])
        self.assertEqual(out['emails'], [])
        self.assertEqual(out['dados_gerais'], {})

    def test_telefones_moveis_list(self):
        data = {'telefones_moveis': ['11988888888']}
        out = _normalize_cpf_api_response(data)
        self.assertEqual(out['telefones_moveis'], ['11988888888'])

    def test_emails_dict_with_email(self):
        data = {'emails': {'EMAIL': 'a@b.com'}}
        out = _normalize_cpf_api_response(data)
        self.assertEqual(out['emails'], ['a@b.com'])

    def test_uppercase_keys(self):
        data = {'TELEFONES_FIXOS': {'TELEFONE': '1133334444'}, 'WHATSAPPS': ['11999']}
        out = _normalize_cpf_api_response(data)
        self.assertEqual(out['telefones_fixos'], ['1133334444'])
        self.assertEqual(out['whatsapps'], ['11999'])
