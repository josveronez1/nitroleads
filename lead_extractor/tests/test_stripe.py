"""
Testes básicos para funcionalidades do Stripe.
"""
from django.test import TestCase
from unittest.mock import patch, MagicMock
from lead_extractor.stripe_service import (
    create_checkout_session, create_custom_checkout_session,
    CREDIT_PACKAGES, CREDIT_PRICE, MIN_CREDITS, MAX_CREDITS
)


class StripeServiceTest(TestCase):
    """Testes básicos do serviço Stripe."""
    
    def test_credit_price_constant(self):
        """Testa que o preço por crédito é R$0,30."""
        self.assertEqual(CREDIT_PRICE, 0.30)
    
    def test_min_max_credits(self):
        """Testa limites de créditos."""
        self.assertGreater(MIN_CREDITS, 0)
        self.assertGreater(MAX_CREDITS, MIN_CREDITS)
    
    def test_credit_packages_pricing(self):
        """Testa que os pacotes estão com preço correto (R$0,30 por crédito)."""
        for package in CREDIT_PACKAGES:
            expected_price = package['credits'] * CREDIT_PRICE
            self.assertEqual(
                package['price_brl'],
                expected_price,
                f"Pacote {package['name']} tem preço incorreto"
            )
    
    @patch('lead_extractor.stripe_service.stripe.checkout.Session.create')
    def test_create_checkout_session_includes_pix_and_card(self, mock_create):
        """Testa que checkout session inclui PIX e cartão."""
        mock_session = MagicMock()
        mock_session.id = 'test_session_id'
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_create.return_value = mock_session
        
        result = create_checkout_session(1, 1, 'test@example.com')
        
        self.assertIsNotNone(result)
        # Verificar que payment_method_types inclui 'card' e 'pix'
        call_args = mock_create.call_args
        self.assertIn('card', call_args[1]['payment_method_types'])
        self.assertIn('pix', call_args[1]['payment_method_types'])
    
    @patch('lead_extractor.stripe_service.stripe.checkout.Session.create')
    def test_create_custom_checkout_session_validates_min_max(self, mock_create):
        """Testa validação de min/max créditos em checkout customizado."""
        # Testar com créditos abaixo do mínimo
        result = create_custom_checkout_session(MIN_CREDITS - 1, 1, 'test@example.com')
        self.assertIsNone(result)
        
        # Testar com créditos acima do máximo
        result = create_custom_checkout_session(MAX_CREDITS + 1, 1, 'test@example.com')
        self.assertIsNone(result)
        
        # Testar com créditos válidos
        mock_session = MagicMock()
        mock_session.id = 'test_session_id'
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_create.return_value = mock_session
        
        result = create_custom_checkout_session(100, 1, 'test@example.com')
        self.assertIsNotNone(result)

