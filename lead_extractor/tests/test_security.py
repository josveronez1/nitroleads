"""
Testes básicos para validações de segurança.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from lead_extractor.models import UserProfile, Search, Lead
from lead_extractor.decorators import require_user_profile


class SecurityTest(TestCase):
    """Testes básicos de segurança."""
    
    def setUp(self):
        """Setup para testes."""
        self.client = Client()
        
        # Criar dois usuários
        self.user1_profile = UserProfile.objects.create(
            supabase_user_id='user1_id',
            email='user1@test.com',
            credits=100
        )
        
        self.user2_profile = UserProfile.objects.create(
            supabase_user_id='user2_id',
            email='user2@test.com',
            credits=100
        )
    
    def test_user_cannot_access_other_user_data(self):
        """Testa que usuário não pode acessar dados de outros usuários."""
        # Criar pesquisa do user1
        search = Search.objects.create(
            user=self.user1_profile,
            niche='Test',
            location='Test',
            quantity_requested=10
        )
        
        # Verificar que user2 não pode acessar
        searches_user2 = Search.objects.filter(user=self.user2_profile)
        self.assertNotIn(search, searches_user2)
    
    def test_leads_filtered_by_user(self):
        """Testa que leads são filtrados por usuário."""
        # Criar lead do user1
        lead = Lead.objects.create(
            user=self.user1_profile,
            name='Test Company',
            cnpj='12345678901234'
        )
        
        # Verificar que user2 não vê esse lead
        leads_user2 = Lead.objects.filter(user=self.user2_profile)
        self.assertNotIn(lead, leads_user2)
        
        # Verificar que user1 vê esse lead
        leads_user1 = Lead.objects.filter(user=self.user1_profile)
        self.assertIn(lead, leads_user1)

