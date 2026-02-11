from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone


class UserProfile(models.Model):
    supabase_user_id = models.CharField(max_length=255, unique=True, db_index=True)
    email = models.EmailField(db_index=True)
    credits = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Onboarding (primeiro login)
    onboarding_completed = models.BooleanField(default=False)
    onboarding_role = models.CharField(max_length=20, null=True, blank=True)  # owner | manager | sdr
    onboarding_pain_points = models.JSONField(default=list)  # e.g. ["mining_phones", "finding_decision_maker", "copy_paste_crm"]

    class Meta:
        indexes = [
            models.Index(fields=['supabase_user_id']),  # Índice explícito para buscas frequentes no middleware
        ]

    def __str__(self):
        return f"{self.email} ({self.supabase_user_id})"


class NormalizedNiche(models.Model):
    """
    Lista de nichos normalizados para padronização de pesquisas.
    """
    name = models.CharField(max_length=255, unique=True, db_index=True)  # Nome normalizado (lowercase, sem acentos)
    display_name = models.CharField(max_length=255, db_index=True)  # Nome para exibição (usado em autocomplete)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_name']
        indexes = [
            models.Index(fields=['display_name', 'is_active']),  # Para autocomplete otimizado
        ]

    def __str__(self):
        return self.display_name


class NormalizedLocation(models.Model):
    """
    Lista de cidades normalizadas com UF para padronização de pesquisas.
    """
    city = models.CharField(max_length=255, db_index=True)
    state = models.CharField(max_length=2, db_index=True)  # UF (2 caracteres)
    display_name = models.CharField(max_length=255, db_index=True)  # Formato: "Cidade - UF" (usado em autocomplete)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['city', 'state']]
        ordering = ['state', 'city']
        indexes = [
            models.Index(fields=['city', 'state']),
            models.Index(fields=['display_name', 'is_active']),  # Para autocomplete otimizado
        ]

    def __str__(self):
        return self.display_name


class CachedSearch(models.Model):
    """
    Cache global de pesquisas normalizadas para reutilização.
    Dados nunca expiram - base histórica permanente.
    """
    niche_normalized = models.CharField(max_length=255)
    location_normalized = models.CharField(max_length=255)  # Formato: "Cidade - UF"
    total_leads_cached = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # DEPRECATED: Mantido para migração, não usado mais
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['niche_normalized', 'location_normalized']]
        ordering = ['-last_updated']
        indexes = [
            models.Index(fields=['niche_normalized', 'location_normalized']),
        ]

    def __str__(self):
        return f"{self.niche_normalized} em {self.location_normalized} ({self.total_leads_cached} leads)"


class Search(models.Model):
    STATUS_CHOICES = [
        ('processing', 'Processando'),
        ('completed', 'Completo'),
        ('failed', 'Falhou'),
    ]
    
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='searches')
    niche = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    quantity_requested = models.IntegerField(validators=[MinValueValidator(1)])
    results_count = models.IntegerField(default=0)
    credits_used = models.IntegerField(default=0)
    search_data = models.JSONField(default=dict)  # Armazena toda a pesquisa (termos, filtros, etc)
    results_data = models.JSONField(default=dict)  # Armazena resultados completos
    cached_search = models.ForeignKey(CachedSearch, null=True, blank=True, on_delete=models.SET_NULL, related_name='user_searches')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')
    processing_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.niche} em {self.location} - {self.user.email}"

    def get_leads_for_display(self, user_profile):
        """
        Retorna leads desta busca para exibição (usa SearchLead para listagem consistente).
        Cada item é dict com 'lead' e 'lead_access' (para enriched_at).
        """
        search_leads = SearchLead.objects.filter(search=self).select_related('lead').order_by('id')
        if not search_leads:
            # Fallback: buscas antigas sem SearchLead (usar LeadAccess)
            lead_accesses = LeadAccess.objects.filter(search=self, user=user_profile).select_related('lead')
            return [{'lead': la.lead, 'lead_access': la} for la in lead_accesses]
        lead_ids = [sl.lead_id for sl in search_leads]
        la_map = {la.lead_id: la for la in LeadAccess.objects.filter(
            user=user_profile, lead_id__in=lead_ids
        )}
        return [
            {'lead': sl.lead, 'lead_access': la_map.get(sl.lead_id)}
            for sl in search_leads
        ]


class CreditTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('purchase', 'Compra'),
        ('usage', 'Uso'),
        ('refund', 'Reembolso'),
    ]
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='credit_transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.IntegerField()  # Positivo para compra, negativo para uso
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)  # histórico Stripe
    kiwify_sale_id = models.CharField(max_length=255, null=True, blank=True)  # histórico Kiwify
    mp_payment_id = models.CharField(max_length=255, null=True, blank=True)  # Mercado Pago
    payment_gateway = models.CharField(
        max_length=20,
        choices=[
            ('mercadopago', 'Mercado Pago'),
            ('kiwify', 'Kiwify'),
            ('stripe', 'Stripe'),
        ],
        default='mercadopago',
    )
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} créditos - {self.user.email}"


class Lead(models.Model):
    """
    Lead global e permanente. Não está vinculado a um usuário específico.
    Acesso de usuários é rastreado via LeadAccess.
    """
    user = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, related_name='legacy_leads', null=True, blank=True, help_text='DEPRECATED: Usar LeadAccess. Mantido para migração.')
    search = models.ForeignKey(Search, null=True, blank=True, on_delete=models.SET_NULL, related_name='legacy_leads', help_text='DEPRECATED: Usar LeadAccess.search. Mantido para migração.')
    cached_search = models.ForeignKey(CachedSearch, null=True, blank=True, on_delete=models.SET_NULL, related_name='cached_leads')
    name = models.CharField(max_length=255)
    address = models.TextField(null=True, blank=True)
    phone_maps = models.CharField(max_length=50, null=True, blank=True)
    cnpj = models.CharField(max_length=30, null=True, blank=True, db_index=True)
    cpf_owner = models.CharField(max_length=14, null=True, blank=True)  # Para busca por CPF
    
    # Vamos salvar o retorno do Viper inteiro num campo JSON
    # Assim não precisamos criar 50 colunas agora. O Postgres/Supabase é ÓTIMO com JSON.
    viper_data = models.JSONField(null=True, blank=True)
    
    first_extracted_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['cnpj']),
            models.Index(fields=['cached_search', 'cnpj']),  # Para get_leads_from_cache otimizado
        ]

    def __str__(self):
        return self.name


class LeadAccess(models.Model):
    """
    Rastreia quais usuários pagaram créditos para acessar quais leads.
    Permite compartilhamento de leads entre usuários mantendo histórico de acesso.
    """
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='lead_accesses')
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='accesses')
    search = models.ForeignKey(Search, null=True, blank=True, on_delete=models.SET_NULL, related_name='lead_accesses')
    credits_paid = models.IntegerField(default=1)  # Créditos pagos para acessar este lead
    accessed_at = models.DateTimeField(auto_now_add=True)
    enriched_at = models.DateTimeField(null=True, blank=True)  # Quando usuário pagou para enriquecer
    
    class Meta:
        unique_together = [['user', 'lead']]  # Um usuário só pode ter um acesso por lead
        indexes = [
            models.Index(fields=['user', 'accessed_at']),
            models.Index(fields=['lead', 'user']),
            models.Index(fields=['search', 'user']),
        ]
    
    def __str__(self):
        return f"{self.user.email} -> {self.lead.name} ({self.accessed_at})"


class SearchLead(models.Model):
    """
    Tabela de junção: quais leads pertencem a qual busca.
    Usada para listagem consistente e deduplicação (últimas 3 buscas).
    """
    search = models.ForeignKey(Search, on_delete=models.CASCADE, related_name='search_leads')
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='search_leads')

    class Meta:
        unique_together = [['search', 'lead']]
        indexes = [
            models.Index(fields=['search']),
            models.Index(fields=['lead']),
        ]

    def __str__(self):
        return f"Search {self.search_id} - Lead {self.lead_id}"


class ViperRequestQueue(models.Model):
    """
    Fila de requisições para API interna do Viper.
    Garante que apenas uma requisição seja processada por vez.
    """
    REQUEST_TYPES = [
        ('partners', 'Sócios/QSA'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('processing', 'Processando'),
        ('completed', 'Completo'),
        ('failed', 'Falhou'),
    ]
    
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='viper_requests')
    lead = models.ForeignKey('Lead', on_delete=models.CASCADE, null=True, blank=True, related_name='viper_queue_requests', help_text='Lead associado a esta requisição (opcional)')
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    request_data = models.JSONField(default=dict)  # Ex: {'cnpj': '12345678901234'}
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    result_data = models.JSONField(null=True, blank=True)  # Resultado da API
    error_message = models.TextField(null=True, blank=True)
    priority = models.IntegerField(default=0)  # Maior = maior prioridade
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-priority', 'created_at']  # Ordena por prioridade (maior primeiro) e depois por data
        indexes = [
            models.Index(fields=['status', 'priority', 'created_at']),  # Para buscar próximo item
            models.Index(fields=['user', 'status']),  # Para buscar requisições do usuário
            models.Index(fields=['user', 'request_type', 'status']),  # Para buscar duplicatas (otimiza find_existing_request)
            # Nota: Índice funcional para request_data->>'cnpj' será criado via migration customizada
        ]

    def __str__(self):
        return f"{self.get_request_type_display()} - {self.user.email} - {self.get_status_display()}"