"""
Testes básicos para sistema de fila do Viper.
"""
from django.test import TestCase
from django.utils import timezone
from lead_extractor.models import UserProfile, ViperRequestQueue
from lead_extractor.viper_queue_service import (
    enqueue_viper_request, get_queue_status,
    get_user_queue_count, process_next_request,
    mark_request_completed, mark_request_failed
)


class ViperQueueTest(TestCase):
    """Testes básicos da fila do Viper."""
    
    def setUp(self):
        """Setup para testes."""
        self.user_profile = UserProfile.objects.create(
            supabase_user_id='test_user_id',
            email='test@example.com',
            credits=100
        )
    
    def test_enqueue_request(self):
        """Testa adicionar requisição à fila."""
        queue_item = enqueue_viper_request(
            user_profile=self.user_profile,
            request_type='partners',
            request_data={'cnpj': '12345678901234'},
            priority=0
        )
        
        self.assertIsNotNone(queue_item)
        self.assertEqual(queue_item.status, 'pending')
        self.assertEqual(queue_item.request_type, 'partners')
        self.assertEqual(queue_item.user, self.user_profile)
    
    def test_get_queue_status(self):
        """Testa obter status da fila."""
        # Adicionar algumas requisições
        enqueue_viper_request(
            user_profile=self.user_profile,
            request_type='partners',
            request_data={'cnpj': '12345678901234'},
            priority=0
        )
        
        status = get_queue_status(self.user_profile)
        
        self.assertIn('pending', status)
        self.assertIn('processing', status)
        self.assertIn('total_waiting', status)
        self.assertEqual(status['pending'], 1)
    
    def test_get_user_queue_count(self):
        """Testa contar requisições do usuário."""
        # Adicionar requisições
        enqueue_viper_request(
            user_profile=self.user_profile,
            request_type='partners',
            request_data={'cnpj': '12345678901234'},
            priority=0
        )
        
        count = get_user_queue_count(self.user_profile)
        self.assertEqual(count, 1)
    
    def test_process_next_request(self):
        """Testa processar próximo item da fila."""
        # Adicionar requisição
        queue_item = enqueue_viper_request(
            user_profile=self.user_profile,
            request_type='partners',
            request_data={'cnpj': '12345678901234'},
            priority=0
        )
        
        # Processar
        processed = process_next_request()
        
        self.assertIsNotNone(processed)
        self.assertEqual(processed.id, queue_item.id)
        self.assertEqual(processed.status, 'processing')
        
        # Refresh do banco
        processed.refresh_from_db()
        self.assertIsNotNone(processed.started_at)
    
    def test_mark_request_completed(self):
        """Testa marcar requisição como completa."""
        queue_item = enqueue_viper_request(
            user_profile=self.user_profile,
            request_type='partners',
            request_data={'cnpj': '12345678901234'},
            priority=0
        )
        
        result_data = {'test': 'data'}
        mark_request_completed(queue_item, result_data)
        
        queue_item.refresh_from_db()
        self.assertEqual(queue_item.status, 'completed')
        self.assertEqual(queue_item.result_data, result_data)
        self.assertIsNotNone(queue_item.completed_at)
    
    def test_mark_request_failed(self):
        """Testa marcar requisição como falhada."""
        queue_item = enqueue_viper_request(
            user_profile=self.user_profile,
            request_type='partners',
            request_data={'cnpj': '12345678901234'},
            priority=0
        )
        
        error_message = 'Test error'
        mark_request_failed(queue_item, error_message)
        
        queue_item.refresh_from_db()
        self.assertEqual(queue_item.status, 'failed')
        self.assertEqual(queue_item.error_message, error_message)
        self.assertIsNotNone(queue_item.completed_at)

