"""
Testes para lead_extractor.services.normalization.
"""
from django.test import TestCase

from lead_extractor.models import NormalizedLocation
from lead_extractor.services.normalization import (
    remove_accents,
    normalize_niche,
    normalize_location,
)


class NormalizationTest(TestCase):
    """Testes de normalização (remove_accents, normalize_niche, normalize_location)."""

    def test_remove_accents_empty(self):
        self.assertEqual(remove_accents(''), '')

    def test_remove_accents_plain(self):
        self.assertEqual(remove_accents('abc'), 'abc')

    def test_remove_accents_with_accents(self):
        self.assertEqual(remove_accents('São Paulo'), 'Sao Paulo')
        self.assertEqual(remove_accents('Açúcar'), 'Acucar')
        self.assertEqual(remove_accents('José'), 'Jose')

    def test_normalize_niche_empty(self):
        self.assertEqual(normalize_niche(''), '')
        self.assertEqual(normalize_niche(None), '')

    def test_normalize_niche_lowercase_and_trim(self):
        self.assertEqual(normalize_niche('advogado'), 'advogado')
        self.assertEqual(normalize_niche('  advogado  '), 'advogado')
        self.assertEqual(normalize_niche('ADVOGADO'), 'advogado')

    def test_normalize_niche_removes_accents(self):
        self.assertEqual(normalize_niche('Advogado'), 'advogado')
        self.assertEqual(normalize_niche('Restaurante'), 'restaurante')

    def test_normalize_niche_collapses_spaces(self):
        self.assertEqual(normalize_niche('advogado   trabalhista'), 'advogado trabalhista')

    def test_normalize_location_empty_or_none(self):
        self.assertIsNone(normalize_location(''))
        self.assertIsNone(normalize_location(None))

    def test_normalize_location_invalid_format_returns_none(self):
        # Formato sem " - UF" retorna None (comportamento atual)
        self.assertIsNone(normalize_location('São Paulo'))
        self.assertIsNone(normalize_location('só cidade'))

    def test_normalize_location_valid_format_creates_display_name(self):
        # "Cidade - UF" sem registro no banco retorna formato capitalizado
        result = normalize_location('santa maria - RS')
        self.assertEqual(result, 'Santa Maria - RS')

    def test_normalize_location_uses_db_when_exists(self):
        NormalizedLocation.objects.create(
            city='Santa Maria',
            state='RS',
            display_name='Santa Maria - RS',
            is_active=True,
        )
        result = normalize_location('santa maria - RS')
        self.assertEqual(result, 'Santa Maria - RS')
