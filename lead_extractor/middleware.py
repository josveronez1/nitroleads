from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
import logging

from .services.auth_service import get_user_profile_from_session

logger = logging.getLogger(__name__)

class SupabaseAuthMiddleware(MiddlewareMixin):
    """
    Middleware para autenticação via sessão Django.
    Redireciona para login se não autenticado.
    """

    EXEMPT_URL_PREFIXES = [
        '/admin/',
        '/login/',
        '/auth/session/',
        '/static/',
        '/media/',
        '/webhook/mercadopago',   # Webhook do Mercado Pago (com ou sem / final)
        '/lp',                    # Landing page (pública)
        '/password-reset',
    ]

    EXEMPT_EXACT_URLS = {
        '/',
    }

    def _is_exempt_path(self, path):
        if path in self.EXEMPT_EXACT_URLS:
            return True
        return any(path.startswith(url) for url in self.EXEMPT_URL_PREFIXES)

    def _handle_unauthenticated(self, request):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Não autenticado', 'redirect': '/login/'}, status=401)
        login_url = reverse('login')
        return HttpResponseRedirect(f'{login_url}?next={request.path}')

    def process_request(self, request):
        request.user_profile = None
        request.supabase_user_id = None

        if request.path.startswith('/admin'):
            return None

        try:
            user_profile = get_user_profile_from_session(request)
        except Exception as exc:
            logger.error("Erro ao resolver sessão autenticada: %s", exc, exc_info=True)
            return self._handle_unauthenticated(request)

        if user_profile:
            request.user_profile = user_profile
            request.supabase_user_id = request.session.get(
                'supabase_user_id',
                user_profile.supabase_user_id,
            )

        if self._is_exempt_path(request.path):
            return None

        if not user_profile:
            return self._handle_unauthenticated(request)

        if not getattr(user_profile, 'onboarding_completed', True):
            onboarding_exempt = (
                request.path.startswith('/onboarding/') or
                request.path.startswith('/api/') or
                request.path.rstrip('/') == '/logout' or
                request.path.startswith('/login') or
                request.path.startswith('/static/') or
                request.path.startswith('/media/') or
                request.path.startswith('/password-reset') or
                request.path == '/favicon.ico'
            )
            if not onboarding_exempt:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': 'Onboarding pendente', 'redirect': '/onboarding/'}, status=200)
                return HttpResponseRedirect(reverse('onboarding'))

        return None


class CSPMiddleware(MiddlewareMixin):
    """
    Middleware para adicionar Content Security Policy (CSP) headers.
    Permite conexões com cdn.jsdelivr.net para source maps.
    """
    
    def process_response(self, request, response):
        # Remover TODOS os headers CSP existentes (do nginx ou outro middleware)
        # Verificar todas as variações possíveis do nome do header
        headers_to_remove = [
            'Content-Security-Policy',
            'content-security-policy',
            'CONTENT-SECURITY-POLICY',
        ]
        
        for header_name in headers_to_remove:
            if header_name in response:
                del response[header_name]
        
        # Construir diretiva CSP completa
        # Permitir: self, *.supabase.co, Mercado Pago SDK/API e domínios mlstatic/mercadolibre (Checkout Bricks)
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://sdk.mercadopago.com https://http2.mlstatic.com https://cdn.tailwindcss.com https://esm.sh https://connect.facebook.net",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com data:",
            "img-src 'self' data: https:",
            "connect-src 'self' https: wss: https://www.facebook.com https://connect.facebook.net",
            "frame-src 'self' https://www.mercadopago.com.br https://www.mercadolibre.com https://secure-fields.mercadopago.com https://js.stripe.com https://hooks.stripe.com",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'self'",
            "upgrade-insecure-requests",
        ]
        
        csp_header = "; ".join(csp_directives)
        
        # Forçar sobrescrita do header CSP
        # Usar del para garantir remoção completa antes de adicionar o novo
        # Django HttpResponse usa case-insensitive headers, mas vamos garantir todas as variações
        if hasattr(response, '_headers'):
            # Para Django < 3.2
            response._headers.pop('content-security-policy', None)
        else:
            # Para Django >= 3.2 (usa headers case-insensitive)
            if 'Content-Security-Policy' in response.headers:
                del response.headers['Content-Security-Policy']
            if 'content-security-policy' in response.headers:
                del response.headers['content-security-policy']
        
        # Adicionar o header correto (Django vai normalizar para Content-Security-Policy)
        response['Content-Security-Policy'] = csp_header
        
        return response

