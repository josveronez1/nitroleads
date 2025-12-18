from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from django.shortcuts import redirect
from django.urls import path
from django.http import HttpResponseRedirect
from .models import UserProfile, Lead, Search, CreditTransaction, ViperRequestQueue
from .credit_service import add_credits


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('email', 'supabase_user_id', 'credits', 'created_at', 'add_credits_action')
    list_filter = ('created_at',)
    search_fields = ('email', 'supabase_user_id')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Informações do Usuário', {
            'fields': ('supabase_user_id', 'email', 'credits')
        }),
        ('Datas', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def add_credits_action(self, obj):
        if obj.id:
            url = f'/admin/lead_extractor/userprofile/{obj.id}/add-credits/'
            return format_html('<a class="button" href="{}">Adicionar Créditos</a>', url)
        return '-'
    add_credits_action.short_description = 'Ações'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/add-credits/',
                self.admin_site.admin_view(self.add_credits_view),
                name='lead_extractor_userprofile_add_credits',
            ),
        ]
        return custom_urls + urls
    
    def add_credits_view(self, request, object_id):
        user_profile = UserProfile.objects.get(pk=object_id)
        
        if request.method == 'POST':
            amount = int(request.POST.get('amount', 0))
            description = request.POST.get('description', 'Créditos adicionados manualmente pelo admin')
            
            if amount > 0:
                success, new_balance, error = add_credits(
                    user_profile,
                    amount,
                    description=description
                )
                
                if success:
                    self.message_user(
                        request,
                        f'{amount} créditos adicionados com sucesso! Novo saldo: {new_balance}',
                        messages.SUCCESS
                    )
                else:
                    self.message_user(
                        request,
                        f'Erro ao adicionar créditos: {error}',
                        messages.ERROR
                    )
                return HttpResponseRedirect(f'/admin/lead_extractor/userprofile/{object_id}/change/')
        
        context = {
            **self.admin_site.each_context(request),
            'title': f'Adicionar Créditos - {user_profile.email}',
            'user_profile': user_profile,
            'opts': self.model._meta,
            'has_view_permission': self.has_view_permission(request, user_profile),
        }
        
        from django.template.response import TemplateResponse
        return TemplateResponse(
            request,
            'admin/lead_extractor/userprofile/add_credits.html',
            context,
        )


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'cnpj', 'user', 'search', 'created_at')
    list_filter = ('created_at', 'user')
    search_fields = ('name', 'cnpj', 'cpf_owner')
    readonly_fields = ('created_at', 'first_extracted_at', 'last_seen_by_user')


@admin.register(Search)
class SearchAdmin(admin.ModelAdmin):
    list_display = ('niche', 'location', 'user', 'quantity_requested', 'results_count', 'credits_used', 'created_at')
    list_filter = ('created_at', 'user')
    search_fields = ('niche', 'location', 'user__email')
    readonly_fields = ('created_at',)


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'transaction_type', 'amount', 'created_at', 'stripe_payment_intent_id')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__email', 'stripe_payment_intent_id')
    readonly_fields = ('created_at',)


@admin.register(ViperRequestQueue)
class ViperRequestQueueAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'request_type', 'status', 'priority', 'created_at', 'completed_at')
    list_filter = ('status', 'request_type', 'created_at')
    search_fields = ('user__email',)
    readonly_fields = ('created_at', 'started_at', 'completed_at')
    ordering = ['-created_at']
