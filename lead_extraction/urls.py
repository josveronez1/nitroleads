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
from django.urls import path
from lead_extractor.views import (
    login_view, logout_view, dashboard, export_leads_csv, simple_search, 
    search_by_cpf, search_by_cnpj, search_history,
    purchase_credits, create_checkout, create_custom_checkout, stripe_webhook, payment_success,
    viper_queue_status, get_viper_result
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('', dashboard, name='dashboard'),
    path('export/', export_leads_csv, name='export_csv'),
    path('export/<int:search_id>/', export_leads_csv, name='export_csv_search'),
    path('simple-search/', simple_search, name='simple_search'),
    path('search/cpf/', search_by_cpf, name='search_by_cpf'),
    path('search/cnpj/', search_by_cnpj, name='search_by_cnpj'),
    path('history/', search_history, name='search_history'),
    path('purchase/', purchase_credits, name='purchase_credits'),
    path('checkout/create/', create_checkout, name='create_checkout'),
    path('checkout/create-custom/', create_custom_checkout, name='create_custom_checkout'),
    path('webhook/stripe/', stripe_webhook, name='stripe_webhook'),
    path('payment/success/', payment_success, name='payment_success'),
    path('api/viper-queue/<int:queue_id>/status/', viper_queue_status, name='viper_queue_status'),
    path('api/viper-queue/<int:queue_id>/result/', get_viper_result, name='get_viper_result'),
]
