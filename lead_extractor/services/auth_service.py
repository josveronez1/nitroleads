import logging

from decouple import config
from django.db import IntegrityError
import jwt

logger = logging.getLogger(__name__)

SESSION_USER_PROFILE_ID = 'user_profile_id'
SESSION_SUPABASE_USER_ID = 'supabase_user_id'
REMEMBER_ME_SESSION_AGE = 60 * 60 * 24 * 30


class SupabaseAuthError(Exception):
    """Erro base para falhas de autenticação via Supabase."""


class SupabaseAuthConfigurationError(SupabaseAuthError):
    """Erro de configuração para validação dos tokens do Supabase."""


def get_supabase_auth_settings():
    """Lê a configuração atual de autenticação do Supabase."""
    supabase_url = config('SUPABASE_URL', default='').rstrip('/')
    supabase_jwt_secret = config('SUPABASE_JWT_SECRET', default='')
    supabase_jwks_url = (
        f'{supabase_url}/auth/v1/.well-known/jwks.json' if supabase_url else ''
    )
    return {
        'supabase_url': supabase_url,
        'supabase_jwt_secret': supabase_jwt_secret,
        'supabase_jwks_url': supabase_jwks_url,
    }


def validate_supabase_token(auth_token):
    """Valida um access token do Supabase e retorna o payload decodificado."""
    if not auth_token:
        raise SupabaseAuthError('Token ausente.')

    settings = get_supabase_auth_settings()
    supabase_jwt_secret = settings['supabase_jwt_secret']
    supabase_jwks_url = settings['supabase_jwks_url']

    if not supabase_jwt_secret and not supabase_jwks_url:
        raise SupabaseAuthConfigurationError(
            'Configure SUPABASE_JWT_SECRET e/ou SUPABASE_URL no .env para habilitar autenticação.'
        )

    try:
        unverified_header = jwt.get_unverified_header(auth_token)
        alg = unverified_header.get('alg')

        if alg == 'HS256':
            if not supabase_jwt_secret:
                raise SupabaseAuthConfigurationError(
                    'SUPABASE_JWT_SECRET é necessário para tokens HS256.'
                )
            payload = jwt.decode(
                auth_token,
                supabase_jwt_secret,
                algorithms=['HS256'],
                audience='authenticated',
            )
        elif alg in ('RS256', 'ES256'):
            if not supabase_jwks_url:
                raise SupabaseAuthConfigurationError(
                    'SUPABASE_URL é necessário para verificar tokens com chave assimétrica.'
                )
            jwks_client = jwt.PyJWKClient(supabase_jwks_url, timeout=10)
            signing_key = jwks_client.get_signing_key_from_jwt(auth_token)
            payload = jwt.decode(
                auth_token,
                signing_key.key,
                algorithms=[alg],
                audience='authenticated',
            )
        else:
            raise SupabaseAuthError(f'Algoritmo JWT não suportado: {alg}')
    except SupabaseAuthConfigurationError:
        raise
    except (jwt.PyJWTError, ValueError) as exc:
        raise SupabaseAuthError(str(exc)) from exc

    user_id = payload.get('sub')
    if not user_id:
        raise SupabaseAuthError('JWT sem subject (sub).')

    return payload


def extract_email_from_payload(payload):
    """Extrai email do payload do Supabase, com fallback previsível."""
    user_id = payload.get('sub', '')
    email = (
        payload.get('email', '')
        or payload.get('user_metadata', {}).get('email', '')
        or payload.get('user', {}).get('email', '')
    )
    if email:
        return email

    placeholder = f"user_{user_id[:8]}@temp.com"
    logger.warning(
        "Email não encontrado no JWT para user_id %s, usando placeholder",
        user_id,
    )
    return placeholder


def resolve_user_profile(payload):
    """Busca ou cria o UserProfile a partir do payload JWT."""
    from lead_extractor.models import UserProfile

    user_id = payload.get('sub')
    email = extract_email_from_payload(payload)
    placeholder_email = f"user_{user_id[:8]}@temp.com"

    try:
        user_profile, created = UserProfile.objects.get_or_create(
            supabase_user_id=user_id,
            defaults={'email': email},
        )

        if created:
            logger.info("UserProfile criado para %s (user_id: %s)", email, user_id)
        elif user_profile.email != email and email != placeholder_email:
            user_profile.email = email
            user_profile.save(update_fields=['email'])
            logger.info("Email atualizado para UserProfile (user_id: %s)", user_id)

        return user_profile
    except IntegrityError as exc:
        logger.error(
            "Erro de integridade ao criar/buscar UserProfile para user_id %s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        try:
            return UserProfile.objects.get(supabase_user_id=user_id)
        except UserProfile.DoesNotExist as missing_exc:
            raise SupabaseAuthError(
                'Não foi possível criar nem encontrar o perfil do usuário.'
            ) from missing_exc
    except Exception as exc:
        logger.error(
            "Erro inesperado ao criar/buscar UserProfile para user_id %s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise SupabaseAuthError('Erro ao acessar perfil de usuário.') from exc


def authenticate_supabase_token(auth_token):
    """Valida o token e resolve o UserProfile correspondente."""
    payload = validate_supabase_token(auth_token)
    user_profile = resolve_user_profile(payload)
    return payload, user_profile


def start_user_session(request, user_profile, remember_me=False):
    """Inicia a sessão do Django para o usuário autenticado."""
    request.session.cycle_key()
    request.session[SESSION_USER_PROFILE_ID] = user_profile.id
    request.session[SESSION_SUPABASE_USER_ID] = user_profile.supabase_user_id
    request.session.set_expiry(
        REMEMBER_ME_SESSION_AGE if remember_me else 0
    )
    request.session.modified = True


def get_user_profile_from_session(request):
    """Resolve o UserProfile da sessão atual, se existir."""
    from lead_extractor.models import UserProfile

    user_profile_id = request.session.get(SESSION_USER_PROFILE_ID)
    if not user_profile_id:
        return None

    try:
        return UserProfile.objects.get(id=user_profile_id)
    except UserProfile.DoesNotExist:
        request.session.pop(SESSION_USER_PROFILE_ID, None)
        request.session.pop(SESSION_SUPABASE_USER_ID, None)
        request.session.modified = True
        return None


def clear_user_session(request):
    """Encerra a sessão autenticada do Django."""
    request.session.flush()
