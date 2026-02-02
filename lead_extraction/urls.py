"""
URL configuration for lead_extraction project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path
from lead_extractor.views import (
    login_view, logout_view, dashboard, export_leads_csv, simple_search, 
    search_by_cpf, search_by_cnpj, search_history, delete_search,
    purchase_credits, create_checkout, process_payment_view, mercadopago_webhook, api_payment_status, payment_success, payment_cancel,
    viper_queue_status, get_viper_result,     api_autocomplete_niches, api_autocomplete_locations,
    api_search_status, api_search_leads, api_partners_status, enrich_leads, search_partners, search_cpf_batch, github_webhook,
    password_reset_view, password_reset_confirm_view, root_redirect_view, serve_favicon,
    lp_index, lp_static,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('password-reset/', password_reset_view, name='password_reset'),
    path('password-reset/confirm/', password_reset_confirm_view, name='password_reset_confirm'),
    path('', root_redirect_view, name='root'),  # Raiz detecta hash e redireciona ou vai para dashboard
    path('dashboard/', dashboard, name='dashboard'),  # Dashboard agora em /dashboard/
    path('export/', export_leads_csv, name='export_csv'),
    path('export/<int:search_id>/', export_leads_csv, name='export_csv_search'),
    path('simple-search/', simple_search, name='simple_search'),
    path('search/cpf/', search_by_cpf, name='search_by_cpf'),
    path('search/cnpj/', search_by_cnpj, name='search_by_cnpj'),
    path('history/', search_history, name='search_history'),
    path('search/<int:search_id>/delete/', delete_search, name='delete_search'),
    path('purchase/', purchase_credits, name='purchase_credits'),
    path('checkout/create/', create_checkout, name='create_checkout'),
    path('checkout/process-payment/', process_payment_view, name='process_payment'),
    re_path(r'^webhook/mercadopago/?$', mercadopago_webhook, name='mercadopago_webhook'),
    path('payment/success/', payment_success, name='payment_success'),
    path('payment/cancel/', payment_cancel, name='payment_cancel'),
    path('api/viper-queue/<int:queue_id>/status/', viper_queue_status, name='viper_queue_status'),
    path('api/viper-queue/<int:queue_id>/result/', get_viper_result, name='get_viper_result'),
    path('api/autocomplete/niches/', api_autocomplete_niches, name='api_autocomplete_niches'),
    path('api/autocomplete/locations/', api_autocomplete_locations, name='api_autocomplete_locations'),
    path('api/search/<int:search_id>/status/', api_search_status, name='api_search_status'),
    path('api/search/<int:search_id>/leads/', api_search_leads, name='api_search_leads'),
    path('api/search/<int:search_id>/partners-status/', api_partners_status, name='api_partners_status'),
    path('search/<int:search_id>/enrich/', enrich_leads, name='enrich_leads'),
    path('search/<int:search_id>/partners/', search_partners, name='search_partners'),
    path('search/cpf/batch/', search_cpf_batch, name='search_cpf_batch'),
    path('api/payment-status/', api_payment_status, name='api_payment_status'),
    path('webhook/github/', github_webhook, name='github_webhook'),
    path('favicon.ico', serve_favicon, name='favicon'),
    re_path(r'^lp/?$', lp_index, name='lp_index'),
    re_path(r'^lp/(?P<path>.*)$', lp_static, name='lp_static'),
]
