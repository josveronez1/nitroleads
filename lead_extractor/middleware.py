from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
from django.db import IntegrityError
from django.core.cache import cache
from supabase import create_client, Client
from jose import jwt, JWTError
from decouple import config
import logging

logger = logging.getLogger(__name__)

SUPABASE_URL = config('SUPABASE_URL', default='')
SUPABASE_KEY = config('SUPABASE_KEY', default='')
SUPABASE_JWT_SECRET = config('SUPABASE_JWT_SECRET', default='')

# TTL do cache de UserProfile (5 minutos)
USER_PROFILE_CACHE_TTL = 300


class SupabaseAuthMiddleware(MiddlewareMixin):
    """
    Middleware para autenticação via Supabase JWT.
    Redireciona para login se não autenticado.
    """
    
    # URLs que não precisam de autenticação
    EXEMPT_URLS = [
        '/admin/',
        '/login/',
        '/static/',
        '/media/',
        '/webhook/stripe/',  # Webhook do Stripe não precisa de autenticação
        '/webhook/github/',  # Webhook do GitHub não precisa de autenticação
    ]
    
    def process_request(self, request):
        # Skip authentication for exempt URLs
        if any(request.path.startswith(url) for url in self.EXEMPT_URLS):
            return None
        
        # Skip authentication for admin (usa auth do Django)
        if request.path.startswith('/admin'):
            return None
        
        # Tentar pegar o token do header Authorization
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            # Tentar pegar do cookie também
            auth_token = request.COOKIES.get('sb-access-token') or request.COOKIES.get('supabase-auth-token', '')
        else:
            auth_token = auth_header.replace('Bearer ', '')
        
        # Se não tem token, redirecionar para login
        if not auth_token:
            # Se for requisição AJAX, retornar JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Não autenticado', 'redirect': '/login/'}, status=401)
            # Senão, redirecionar para login
            login_url = reverse('login')
            return HttpResponseRedirect(f'{login_url}?next={request.path}')
        
        # Se não tem JWT_SECRET configurado, redirecionar para login
        if not SUPABASE_JWT_SECRET:
            logger.error("SUPABASE_JWT_SECRET não configurado. Configure no .env para habilitar autenticação.")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Autenticação não configurada', 'redirect': '/login/'}, status=500)
            login_url = reverse('login')
            return HttpResponseRedirect(login_url)
        
        try:
            # Verificar e decodificar o JWT
            payload = jwt.decode(
                auth_token,
                SUPABASE_JWT_SECRET,
                algorithms=['HS256'],
                audience='authenticated'
            )
            
            # Pegar o user_id do payload
            user_id = payload.get('sub')
            
            if not user_id:
                request.user_profile = None
                return None
            
            # Buscar ou criar UserProfile com cache
            user_profile = self._get_user_profile_cached(user_id, payload)
            
            if not user_profile:
                # Erro ao buscar/criar UserProfile
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': 'Erro ao acessar perfil de usuário'}, status=500)
                login_url = reverse('login')
                return HttpResponseRedirect(login_url)
            
            request.user_profile = user_profile
            request.supabase_user_id = user_id
            
        except JWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            # Token inválido, redirecionar para login
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Token inválido', 'redirect': '/login/'}, status=401)
            login_url = reverse('login')
            return HttpResponseRedirect(f'{login_url}?next={request.path}')
        except Exception as e:
            logger.error(f"Error in SupabaseAuthMiddleware: {e}")
            # Erro ao processar token, redirecionar para login
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Erro de autenticação', 'redirect': '/login/'}, status=401)
            login_url = reverse('login')
            return HttpResponseRedirect(f'{login_url}?next={request.path}')
        
        return None
    
    def _get_user_profile_cached(self, user_id, payload):
        """
        Busca ou cria UserProfile com cache em memória.
        Cache baseado em user_id com TTL de 5 minutos.
        
        Args:
            user_id: ID do usuário do Supabase
            payload: Payload do JWT decodificado
        
        Returns:
            UserProfile ou None em caso de erro
        """
        from .models import UserProfile
        
        # Chave do cache baseada no user_id
        cache_key = f'user_profile_{user_id}'
        
        # Tentar buscar do cache primeiro
        user_profile = cache.get(cache_key)
        if user_profile:
            return user_profile
        
        # Extrair email do payload JWT
        email = payload.get('email', '') or payload.get('user_metadata', {}).get('email', '') or payload.get('user', {}).get('email', '')
        
        # Se ainda não tem email, usar um placeholder temporário
        if not email:
            email = f"user_{user_id[:8]}@temp.com"
            logger.warning(f"Email não encontrado no JWT para user_id {user_id}, usando placeholder")
        
        # Buscar ou criar UserProfile (sem cache para garantir consistência)
        try:
            user_profile, created = UserProfile.objects.get_or_create(
                supabase_user_id=user_id,
                defaults={'email': email}
            )
            
            if created:
                logger.info(f"UserProfile criado para {email} (user_id: {user_id})")
            else:
                # Se já existe, atualizar email se necessário (caso tenha mudado)
                if user_profile.email != email and email != f"user_{user_id[:8]}@temp.com":
                    user_profile.email = email
                    user_profile.save(update_fields=['email'])
                    logger.info(f"Email atualizado para UserProfile (user_id: {user_id})")
            
            # Armazenar no cache
            cache.set(cache_key, user_profile, USER_PROFILE_CACHE_TTL)
            return user_profile
                        
        except IntegrityError as e:
            logger.error(f"Erro de integridade ao criar/buscar UserProfile para user_id {user_id}: {e}", exc_info=True)
            # Se deu erro de integridade, tentar buscar novamente
            try:
                user_profile = UserProfile.objects.get(supabase_user_id=user_id)
                # Armazenar no cache mesmo em caso de erro de integridade (já existe)
                cache.set(cache_key, user_profile, USER_PROFILE_CACHE_TTL)
                return user_profile
            except UserProfile.DoesNotExist:
                logger.error(f"Não foi possível criar nem encontrar UserProfile para user_id {user_id}")
                return None
        except Exception as e:
            logger.error(f"Erro inesperado ao criar/buscar UserProfile para user_id {user_id}: {e}", exc_info=True)
            return None

