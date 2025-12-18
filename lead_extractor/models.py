from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone


class UserProfile(models.Model):
    supabase_user_id = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    credits = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.email} ({self.supabase_user_id})"


class Search(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='searches')
    niche = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    quantity_requested = models.IntegerField(validators=[MinValueValidator(1)])
    results_count = models.IntegerField(default=0)
    credits_used = models.IntegerField(default=0)
    search_data = models.JSONField(default=dict)  # Armazena toda a pesquisa (termos, filtros, etc)
    results_data = models.JSONField(default=dict)  # Armazena resultados completos
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

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
    name = models.CharField(max_length=255)
    address = models.TextField(null=True, blank=True)
    phone_maps = models.CharField(max_length=50, null=True, blank=True)
    cnpj = models.CharField(max_length=30, null=True, blank=True)
    cpf_owner = models.CharField(max_length=14, null=True, blank=True)  # Para busca por CPF
    
    # Vamos salvar o retorno do Viper inteiro num campo JSON
    # Assim não precisamos criar 50 colunas agora. O Postgres/Supabase é ÓTIMO com JSON.
    viper_data = models.JSONField(null=True, blank=True)
    
    last_seen_by_user = models.DateTimeField(auto_now=True)  # Para lógica de reutilização
    first_extracted_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'cnpj']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['cnpj']),
        ]

    def __str__(self):
        return self.name