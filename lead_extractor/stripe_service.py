import stripe
from decouple import config
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Configurar chave secreta do Stripe (será verificada antes de cada chamada)
STRIPE_SECRET_KEY = config('STRIPE_SECRET_KEY', default='')
stripe.api_key = STRIPE_SECRET_KEY

# Configurar se PIX está habilitado (padrão: True - PIX habilitado)
ENABLE_PIX = config('STRIPE_ENABLE_PIX', default=True, cast=bool)

# Constantes de precificação
MIN_CREDITS = 10
MAX_CREDITS = 10000
MIN_PRICE_PER_CREDIT = 0.26  # Preço mínimo por crédito (NUNCA menor que isso)
MAX_PRICE_PER_CREDIT = 1.00  # Preço máximo por crédito

# Pontos de referência para cálculo progressivo de preços
# Formato: (quantidade, preço_por_crédito)
PRICING_POINTS = [
    (10, 1.00),    # 10 créditos = R$ 1,00 por crédito (máximo)
    (100, 0.40),   # 100 créditos = R$ 0,40 por crédito
    (500, 0.32),   # 500 créditos = R$ 0,32 por crédito
    (1000, 0.28),  # 1000 créditos = R$ 0,28 por crédito
    (2500, 0.26),  # 2500 créditos = R$ 0,26 por crédito (mínimo)
]

# Configuração de pacotes de créditos com preços FIXOS
CREDIT_PACKAGES = [
    {'id': 1, 'credits': 100, 'price_brl': 40.00, 'price_per_credit': 0.40, 'name': 'Pacote Básico'},  # 100 * 0.40
    {'id': 2, 'credits': 500, 'price_brl': 160.00, 'price_per_credit': 0.32, 'name': 'Pacote Intermediário'},  # 500 * 0.32
    {'id': 3, 'credits': 1000, 'price_brl': 280.00, 'price_per_credit': 0.28, 'name': 'Pacote Avançado'},  # 1000 * 0.28
    {'id': 4, 'credits': 2500, 'price_brl': 650.00, 'price_per_credit': 0.26, 'name': 'Pacote Premium'},  # 2500 * 0.26
]


def calculate_price_per_credit(credits):
    """
    Calcula o preço por crédito baseado na quantidade usando interpolação linear
    entre os pontos de referência.
    
    Args:
        credits: Quantidade de créditos a comprar
        
    Returns:
        float: Preço por crédito (entre MIN_PRICE_PER_CREDIT e MAX_PRICE_PER_CREDIT)
    """
    # Garantir limites mínimos e máximos
    if credits < MIN_CREDITS:
        return MAX_PRICE_PER_CREDIT
    
    if credits >= PRICING_POINTS[-1][0]:  # 2500 ou mais
        return MIN_PRICE_PER_CREDIT
    
    # Encontrar o intervalo onde credits está
    for i in range(len(PRICING_POINTS) - 1):
        qty1, price1 = PRICING_POINTS[i]
        qty2, price2 = PRICING_POINTS[i + 1]
        
        if qty1 <= credits < qty2:
            # Interpolação linear
            price = price1 + (credits - qty1) * (price2 - price1) / (qty2 - qty1)
            # Garantir limites
            price = max(MIN_PRICE_PER_CREDIT, min(MAX_PRICE_PER_CREDIT, price))
            return round(price, 2)
    
    # Fallback (não deveria chegar aqui, mas garantia)
    return MIN_PRICE_PER_CREDIT


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
    # Verificar se a chave do Stripe está configurada
    if not STRIPE_SECRET_KEY or STRIPE_SECRET_KEY.strip() == '':
        logger.error("STRIPE_SECRET_KEY não está configurada no .env")
        return None
    
    # Atualizar a chave caso tenha mudado
    stripe.api_key = STRIPE_SECRET_KEY
    
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
        
        # Definir métodos de pagamento (PIX só se estiver habilitado)
        payment_method_types = ['card']
        payment_method_options = {}
        
        if ENABLE_PIX:
            payment_method_types.append('pix')
            payment_method_options['pix'] = {
                'expires_after_seconds': 3600,  # 1 hora para PIX
            }
        
        session = stripe.checkout.Session.create(
            payment_method_types=payment_method_types,
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
            payment_method_options=payment_method_options if payment_method_options else None,
            metadata={
                'user_id': str(user_id),
                'package_id': str(package_id),
                'credits': str(package['credits']),
            },
        )
        
        return session
        
    except stripe.error.StripeError as e:
        logger.error(f"Erro do Stripe ao criar checkout: {e}", exc_info=True)
        logger.error(f"Detalhes do erro Stripe: tipo={type(e).__name__}, mensagem={str(e)}")
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao criar checkout session: {e}", exc_info=True)
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
    # Verificar se a chave do Stripe está configurada
    if not STRIPE_SECRET_KEY or STRIPE_SECRET_KEY.strip() == '':
        logger.error("STRIPE_SECRET_KEY não está configurada no .env")
        return None
    
    # Atualizar a chave caso tenha mudado
    stripe.api_key = STRIPE_SECRET_KEY
    
    try:
        # Validar quantidade de créditos
        if credits < MIN_CREDITS or credits > MAX_CREDITS:
            logger.error(f"Quantidade de créditos inválida: {credits} (deve estar entre {MIN_CREDITS} e {MAX_CREDITS})")
            return None
        
        # Calcular preço usando função progressiva
        price_per_credit = calculate_price_per_credit(credits)
        price_brl = credits * price_per_credit
        
        # Usar variável de ambiente ou default para URL base
        base_url = config('BASE_URL', default='http://localhost:8000')
        success_url = f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/payment/cancel"
        
        # Definir métodos de pagamento (PIX só se estiver habilitado)
        payment_method_types = ['card']
        payment_method_options = {}
        
        if ENABLE_PIX:
            payment_method_types.append('pix')
            payment_method_options['pix'] = {
                'expires_after_seconds': 3600,  # 1 hora para PIX
            }
        
        session = stripe.checkout.Session.create(
            payment_method_types=payment_method_types,
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
            payment_method_options=payment_method_options if payment_method_options else None,
            metadata={
                'user_id': str(user_id),
                'credits': str(credits),
                'custom': 'true',  # Marcar como compra customizada
            },
        )
        
        return session
        
    except stripe.error.StripeError as e:
        logger.error(f"Erro do Stripe ao criar checkout customizado: {e}", exc_info=True)
        logger.error(f"Detalhes do erro Stripe: tipo={type(e).__name__}, mensagem={str(e)}")
        return None
    except Exception as e:
        logger.error(f"Erro inesperado ao criar checkout session customizado: {e}", exc_info=True)
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
        logger.info(f"Processando evento do tipo: {event.get('type')}")
        
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            logger.info(f"Checkout session completed. Session ID: {session.get('id')}")
            logger.info(f"Metadata da sessão: {session.get('metadata')}")
            
            # Extrair metadata
            user_id = session['metadata'].get('user_id')
            package_id = session['metadata'].get('package_id')
            credits_str = session['metadata'].get('credits', '0')
            credits = int(credits_str) if credits_str else 0
            is_custom = session['metadata'].get('custom') == 'true'
            payment_intent_id = session.get('payment_intent')
            
            logger.info(f"Extracted: user_id={user_id}, credits={credits}, is_custom={is_custom}")
            
            if not user_id or not credits:
                logger.error(f"Metadata incompleta no evento do Stripe: user_id={user_id}, credits={credits}")
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
                
        # Evento não processado (retorna True para não aparecer como erro no Stripe)
        logger.debug(f"Evento {event.get('type')} não precisa ser processado")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}")
        return False

