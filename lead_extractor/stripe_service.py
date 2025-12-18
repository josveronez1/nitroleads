import stripe
from decouple import config
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Configurar chave secreta do Stripe
stripe.api_key = config('STRIPE_SECRET_KEY', default='')

# Constantes de precificação
CREDIT_PRICE = 0.30  # R$0,30 por crédito
MIN_CREDITS = 10
MAX_CREDITS = 10000

# Configuração de pacotes de créditos (recalculados para R$0,30 por crédito)
CREDIT_PACKAGES = [
    {'id': 1, 'credits': 100, 'price_brl': 30.00, 'name': 'Pacote Básico'},  # 100 * 0.30
    {'id': 2, 'credits': 500, 'price_brl': 150.00, 'name': 'Pacote Intermediário'},  # 500 * 0.30
    {'id': 3, 'credits': 1000, 'price_brl': 300.00, 'name': 'Pacote Avançado'},  # 1000 * 0.30
    {'id': 4, 'credits': 2500, 'price_brl': 750.00, 'name': 'Pacote Premium'},  # 2500 * 0.30
]


def create_checkout_session(package_id, user_id, user_email):
    """
    Cria uma sessão de checkout do Stripe para compra de créditos.
    
    Args:
        package_id: ID do pacote de créditos
        user_id: ID do UserProfile
        user_email: Email do usuário
    
    Returns:
        dict: Sessão do Stripe ou None em caso de erro
    """
    try:
        # Buscar pacote
        package = next((p for p in CREDIT_PACKAGES if p['id'] == package_id), None)
        if not package:
            logger.error(f"Pacote {package_id} não encontrado")
            return None
        
        # Criar sessão de checkout
        # Nota: Você precisa criar os produtos e prices no dashboard do Stripe
        # e usar os price_id aqui. Por enquanto, vamos usar o modo de desenvolvimento
        
        # Usar variável de ambiente ou default para URL base
        base_url = config('BASE_URL', default='http://localhost:8000')
        success_url = f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/payment/cancel"
        
        session = stripe.checkout.Session.create(
            payment_method_types=['card', 'pix'],  # Suporta PIX e cartão
            line_items=[{
                'price_data': {
                    'currency': 'brl',
                    'product_data': {
                        'name': f"{package['name']} - {package['credits']} créditos",
                        'description': f"Compra de {package['credits']} créditos",
                    },
                    'unit_amount': int(package['price_brl'] * 100),  # Stripe usa centavos
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=user_email,
            payment_method_options={
                'pix': {
                    'expires_after_seconds': 3600,  # 1 hora para PIX (padrão Stripe é 24h, mas podemos ajustar)
                }
            },
            metadata={
                'user_id': str(user_id),
                'package_id': str(package_id),
                'credits': str(package['credits']),
            },
        )
        
        return session
        
    except stripe.error.StripeError as e:
        logger.error(f"Erro do Stripe: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao criar checkout session: {e}")
        return None


def create_custom_checkout_session(credits, user_id, user_email):
    """
    Cria uma sessão de checkout do Stripe para compra customizada de créditos.
    
    Args:
        credits: Quantidade de créditos a comprar
        user_id: ID do UserProfile
        user_email: Email do usuário
    
    Returns:
        dict: Sessão do Stripe ou None em caso de erro
    """
    try:
        # Validar quantidade de créditos
        if credits < MIN_CREDITS or credits > MAX_CREDITS:
            logger.error(f"Quantidade de créditos inválida: {credits} (deve estar entre {MIN_CREDITS} e {MAX_CREDITS})")
            return None
        
        # Calcular preço
        price_brl = credits * CREDIT_PRICE
        
        # Usar variável de ambiente ou default para URL base
        base_url = config('BASE_URL', default='http://localhost:8000')
        success_url = f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/payment/cancel"
        
        session = stripe.checkout.Session.create(
            payment_method_types=['card', 'pix'],  # Suporta PIX e cartão
            line_items=[{
                'price_data': {
                    'currency': 'brl',
                    'product_data': {
                        'name': f"Compra de {credits} créditos",
                        'description': f"Compra customizada de {credits} créditos (R$ {price_brl:.2f})",
                    },
                    'unit_amount': int(price_brl * 100),  # Stripe usa centavos
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=user_email,
            payment_method_options={
                'pix': {
                    'expires_after_seconds': 3600,  # 1 hora para PIX
                }
            },
            metadata={
                'user_id': str(user_id),
                'credits': str(credits),
                'custom': 'true',  # Marcar como compra customizada
            },
        )
        
        return session
        
    except stripe.error.StripeError as e:
        logger.error(f"Erro do Stripe: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao criar checkout session customizado: {e}")
        return None


def handle_webhook_event(event):
    """
    Processa eventos de webhook do Stripe.
    
    Args:
        event: Objeto de evento do Stripe
    
    Returns:
        bool: True se processado com sucesso, False caso contrário
    """
    try:
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            # Extrair metadata
            user_id = session['metadata'].get('user_id')
            package_id = session['metadata'].get('package_id')
            credits = int(session['metadata'].get('credits', 0))
            is_custom = session['metadata'].get('custom') == 'true'
            payment_intent_id = session.get('payment_intent')
            
            if not user_id or not credits:
                logger.error("Metadata incompleta no evento do Stripe")
                return False
            
            # Adicionar créditos ao usuário
            from .models import UserProfile
            from .credit_service import add_credits
            
            try:
                user_profile = UserProfile.objects.get(id=user_id)
                description = f"Compra customizada de {credits} créditos via Stripe" if is_custom else f"Compra de {credits} créditos via Stripe (Pacote {package_id})"
                success, new_balance, error = add_credits(
                    user_profile,
                    credits,
                    description=description,
                    stripe_payment_intent_id=payment_intent_id
                )
                
                if success:
                    logger.info(f"Créditos adicionados: {credits} ao usuário {user_profile.email}")
                    return True
                else:
                    logger.error(f"Erro ao adicionar créditos: {error}")
                    return False
                    
            except UserProfile.DoesNotExist:
                logger.error(f"Usuário {user_id} não encontrado")
                return False
                
        return False
        
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}")
        return False

