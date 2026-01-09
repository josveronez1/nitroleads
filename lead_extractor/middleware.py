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
    # IMPORTANTE: Incluir tanto com quanto sem barra final para garantir funcionamento
    EXEMPT_URLS = [
        '/admin',
        '/admin/',
        '/login',
        '/login/',
        '/password-reset',  # Página de reset de senha (sem barra)
        '/password-reset/',  # Página de reset de senha (com barra)
        '/password-reset/confirm',  # Página de confirmação (sem barra)
        '/password-reset/confirm/',  # Página de confirmação (com barra)
        '/static',
        '/static/',
        '/media',
        '/media/',
        '/webhook/stripe',
        '/webhook/stripe/',
        '/webhook/github',
        '/webhook/github/',
        '/favicon.ico',  # Favicon não precisa de autenticação
    ]
    
    def process_request(self, request):
        # VERIFICAÇÃO ULTRA PRIORITÁRIA - ANTES DE QUALQUER OUTRA COISA
        # Isso deve ser a PRIMEIRA coisa que fazemos, antes até dos logs
        request_path = request.path
        full_path = request.get_full_path()
        
        # Permitir acesso à raiz SEM autenticação
        # A view root_redirect_view vai detectar o hash e redirecionar corretamente
        # Se não houver hash nem referer do Supabase, a view redireciona para login/dashboard
        if request_path == '/':
            referer = request.META.get('HTTP_REFERER', '')
            logger.info(f"[MIDDLEWARE] ✓✓✓ ACESSO À RAIZ PERMITIDO - SEM AUTENTICAÇÃO")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Path: {request_path}")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Referer: {referer}")
            logger.info(f"[MIDDLEWARE] ✓✓✓ A view root_redirect_view vai lidar com o redirecionamento")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Se houver hash de recovery, redirecionará para /password-reset/confirm/")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Se não houver, redirecionará para login ou dashboard")
            return None
        
        # Verificar se é URL de password-reset (check mais abrangente possível)
        is_password_reset = (
            request_path.startswith('/password-reset') or 
            full_path.startswith('/password-reset') or
            'password-reset' in request_path or
            'password-reset' in full_path
        )
        
        if is_password_reset:
            # Log apenas para debug
            logger.info(f"[MIDDLEWARE] ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓")
            logger.info(f"[MIDDLEWARE] ✓✓✓ URL DE PASSWORD-RESET DETECTADA - RETORNANDO None IMEDIATAMENTE")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Path: {request_path}")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Full path: {full_path}")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Method: {request.method}")
            logger.info(f"[MIDDLEWARE] ✓✓✓ Referer: {request.META.get('HTTP_REFERER', 'N/A')}")
            logger.info(f"[MIDDLEWARE] ✓✓✓ User-Agent: {request.META.get('HTTP_USER_AGENT', 'N/A')[:100]}")
            logger.info(f"[MIDDLEWARE] ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓")
            # RETORNAR None IMEDIATAMENTE - NÃO FAZER MAIS NADA
            return None
        
        # Log ANTES de qualquer verificação para capturar TODAS as URLs
        logger.info(f"[MIDDLEWARE] 📍 REQUISIÇÃO RECEBIDA - Path: {request_path} | Full: {full_path} | Method: {request.method}")
        
        # Se não for password-reset, continuar com logs normais
        logger.info(f"[MIDDLEWARE] ========================================")
        logger.info(f"[MIDDLEWARE] Processando requisição: {request_path}")
        logger.info(f"[MIDDLEWARE] Full path: {full_path}")
        logger.info(f"[MIDDLEWARE] Method: {request.method}")
        logger.info(f"[MIDDLEWARE] Query string: {request.GET.urlencode()}")
        logger.info(f"[MIDDLEWARE] ========================================")
        
        # Skip authentication for admin (usa auth do Django)
        if request_path.startswith('/admin'):
            logger.info(f"[MIDDLEWARE] ✓ URL admin detectada e isenta: {request_path}")
            return None
        
        # Skip authentication for login
        if request_path.startswith('/login'):
            logger.info(f"[MIDDLEWARE] ✓ URL login detectada e isenta: {request_path}")
            return None
        
        # Skip authentication for other exempt URLs
        for exempt_url in self.EXEMPT_URLS:
            if request_path.startswith(exempt_url):
                logger.info(f"[MIDDLEWARE] ✓ URL isenta detectada: {request_path} (isento: {exempt_url})")
                return None
        
        logger.info(f"[MIDDLEWARE] ✗ URL NÃO está na lista de isentas: {request_path}")
        
        # Tentar pegar o token do header Authorization
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            # Tentar pegar do cookie também
            auth_token = request.COOKIES.get('sb-access-token') or request.COOKIES.get('supabase-auth-token', '')
        else:
            auth_token = auth_header.replace('Bearer ', '')
        
        # Se não tem token, redirecionar para login
        # IMPORTANTE: NUNCA redirecionar se for password-reset (já verificamos, mas garantia extra)
        if not auth_token:
            # Se for requisição AJAX, retornar JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Não autenticado', 'redirect': '/login/'}, status=401)
            # Senão, redirecionar para login (MAS NUNCA se for password-reset)
            if 'password-reset' not in request_path and 'password-reset' not in full_path:
                login_url = reverse('login')
                return HttpResponseRedirect(f'{login_url}?next={request.path}')
            else:
                # Se for password-reset, permitir passar (não deveria chegar aqui, mas garantia)
                logger.warning(f"[MIDDLEWARE] ⚠️ Password-reset detectado sem token, mas permitindo passar: {request_path}")
                return None
        
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
            # Token inválido, redirecionar para login (MAS NUNCA se for password-reset)
            if 'password-reset' not in request_path and 'password-reset' not in full_path:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': 'Token inválido', 'redirect': '/login/'}, status=401)
                login_url = reverse('login')
                return HttpResponseRedirect(f'{login_url}?next={request.path}')
            else:
                # Se for password-reset, permitir passar mesmo com token inválido
                logger.info(f"[MIDDLEWARE] ⚠️ Password-reset com token inválido, mas permitindo passar: {request_path}")
                return None
        except Exception as e:
            logger.error(f"Error in SupabaseAuthMiddleware: {e}")
            # Erro ao processar token, redirecionar para login (MAS NUNCA se for password-reset)
            if 'password-reset' not in request_path and 'password-reset' not in full_path:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': 'Erro de autenticação', 'redirect': '/login/'}, status=401)
                login_url = reverse('login')
                return HttpResponseRedirect(f'{login_url}?next={request.path}')
            else:
                # Se for password-reset, permitir passar mesmo com erro
                logger.info(f"[MIDDLEWARE] ⚠️ Password-reset com erro no token, mas permitindo passar: {request_path}")
                return None
        
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
        cached_profile_id = cache.get(cache_key)
        if cached_profile_id:
            # Buscar do banco usando o ID do cache para garantir sincronização
            try:
                user_profile = UserProfile.objects.get(id=cached_profile_id)
                # Refresh para garantir que está sincronizado
                user_profile.refresh_from_db()
                return user_profile
            except UserProfile.DoesNotExist:
                # Cache inválido, limpar e continuar
                cache.delete(cache_key)
        
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
            
            # Armazenar apenas o ID no cache (não o objeto inteiro) para evitar problemas de serialização
            cache.set(cache_key, user_profile.id, USER_PROFILE_CACHE_TTL)
            return user_profile
                        
        except IntegrityError as e:
            logger.error(f"Erro de integridade ao criar/buscar UserProfile para user_id {user_id}: {e}", exc_info=True)
            # Se deu erro de integridade, tentar buscar novamente
            try:
                user_profile = UserProfile.objects.get(supabase_user_id=user_id)
                # Armazenar apenas o ID no cache mesmo em caso de erro de integridade (já existe)
                cache.set(cache_key, user_profile.id, USER_PROFILE_CACHE_TTL)
                return user_profile
            except UserProfile.DoesNotExist:
                logger.error(f"Não foi possível criar nem encontrar UserProfile para user_id {user_id}")
                return None
        except Exception as e:
            logger.error(f"Erro inesperado ao criar/buscar UserProfile para user_id {user_id}: {e}", exc_info=True)
            return None

