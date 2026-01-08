from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone


class UserProfile(models.Model):
    supabase_user_id = models.CharField(max_length=255, unique=True, db_index=True)
    email = models.EmailField(db_index=True)
    credits = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    """
    niche_normalized = models.CharField(max_length=255)
    location_normalized = models.CharField(max_length=255)  # Formato: "Cidade - UF"
    total_leads_cached = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()  # Calculado: last_updated + 90 dias
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['niche_normalized', 'location_normalized']]
        ordering = ['-last_updated']
        indexes = [
            models.Index(fields=['niche_normalized', 'location_normalized']),
            models.Index(fields=['expires_at']),
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


class CreditTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('purchase', 'Compra'),
        ('usage', 'Uso'),
        ('refund', 'Reembolso'),
    ]
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='credit_transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.IntegerField()  # Positivo para compra, negativo para uso
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} créditos - {self.user.email}"


class Lead(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='leads', null=True, blank=True)
    search = models.ForeignKey(Search, null=True, blank=True, on_delete=models.SET_NULL, related_name='leads')
    cached_search = models.ForeignKey(CachedSearch, null=True, blank=True, on_delete=models.SET_NULL, related_name='cached_leads')
    name = models.CharField(max_length=255)
    address = models.TextField(null=True, blank=True)
    phone_maps = models.CharField(max_length=50, null=True, blank=True)
    cnpj = models.CharField(max_length=30, null=True, blank=True, db_index=True)
    cpf_owner = models.CharField(max_length=14, null=True, blank=True)  # Para busca por CPF
    
    # Vamos salvar o retorno do Viper inteiro num campo JSON
    # Assim não precisamos criar 50 colunas agora. O Postgres/Supabase é ÓTIMO com JSON.
    viper_data = models.JSONField(null=True, blank=True)
    
    last_seen_by_user = models.DateTimeField(auto_now=True, db_index=True)  # Para lógica de reutilização
    first_extracted_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'cnpj']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['cnpj']),
            models.Index(fields=['cached_search', 'cnpj']),  # Para get_leads_from_cache otimizado
            # ForeignKey já cria índice automaticamente, mas índices compostos ajudam em queries específicas
        ]

    def __str__(self):
        return self.name


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