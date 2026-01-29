"""
Testes básicos para funcionalidades do Kiwify.
"""
from django.test import TestCase
from unittest.mock import patch, MagicMock
from lead_extractor.kiwify_service import (
    CREDIT_PACKAGES,
    KIWIFY_PRODUCT_MAP,
    _product_id_to_credits,
    handle_webhook_event,
)


class KiwifyServiceTest(TestCase):
    """Testes básicos do serviço Kiwify."""

    def test_credit_packages_count(self):
        """Testa que há 7 pacotes."""
        self.assertEqual(len(CREDIT_PACKAGES), 7)

    def test_credit_packages_min_price_per_credit(self):
        """Testa que nenhum pacote tem preço por crédito menor que R$ 0,26."""
        for package in CREDIT_PACKAGES:
            self.assertGreaterEqual(
                package['price_per_credit'],
                0.26,
                f"Pacote {package['name']} tem preço por crédito abaixo do mínimo",
            )

    def test_credit_packages_pricing_consistency(self):
        """Testa que price_brl = credits * price_per_credit."""
        for package in CREDIT_PACKAGES:
            expected = round(package['credits'] * package['price_per_credit'], 2)
            self.assertEqual(
                package['price_brl'],
                expected,
                f"Pacote {package['name']} preço inconsistente",
            )

    def test_kiwify_product_map_has_all_packages(self):
        """Testa que KIWIFY_PRODUCT_MAP tem os 7 package_ids."""
        for i in range(1, 8):
            self.assertIn(i, KIWIFY_PRODUCT_MAP)
            self.assertTrue(KIWIFY_PRODUCT_MAP[i])

    def test_product_id_to_credits(self):
        """Testa mapeamento product_id -> créditos."""
        uuid_50 = KIWIFY_PRODUCT_MAP[1]
        self.assertEqual(_product_id_to_credits(uuid_50), 50)
        uuid_5000 = KIWIFY_PRODUCT_MAP[7]
        self.assertEqual(_product_id_to_credits(uuid_5000), 5000)
        self.assertIsNone(_product_id_to_credits("unknown-uuid"))

    @patch('lead_extractor.kiwify_service.add_credits')
    @patch('lead_extractor.models.CreditTransaction')
    def test_handle_webhook_event_paid(self, mock_ct, mock_add_credits):
        """Testa que webhook com order_status paid e UserProfile existente credita."""
        from lead_extractor.models import UserProfile
        user = UserProfile.objects.create(
            supabase_user_id='test-uuid',
            email='johndoe@example.com',
            credits=0,
        )
        mock_ct.objects.filter.return_value.exists.return_value = False
        mock_add_credits.return_value = (True, 100, None)

        payload = {
            'order_id': 'test-order-123',
            'order_status': 'paid',
            'Product': {'product_id': KIWIFY_PRODUCT_MAP[2]},
            'Customer': {'email': 'johndoe@example.com'},
        }
        import json
        body = json.dumps(payload)
        result = handle_webhook_event(body)
        self.assertTrue(result)
        mock_add_credits.assert_called_once()
        call_kw = mock_add_credits.call_args[1]
        self.assertEqual(call_kw['kiwify_sale_id'], 'test-order-123')
        self.assertEqual(call_kw['payment_gateway'], 'kiwify')
        self.assertEqual(call_kw['amount'], 100)
