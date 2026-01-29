"""
Serviço de integração com Kiwify como gateway de pagamento.
Substitui o Stripe: checkout via link do produto + webhook para creditar.
"""
import logging
import urllib.parse
from decouple import config
import requests

logger = logging.getLogger(__name__)

# Configuração
KIWIFY_API_BASE = "https://public-api.kiwify.com/v1"
KIWIFY_CLIENT_ID = config("KIWIFY_CLIENT_ID", default="")
KIWIFY_CLIENT_SECRET = config("KIWIFY_CLIENT_SECRET", default="")
KIWIFY_ACCOUNT_ID = config("KIWIFY_ACCOUNT_ID", default="")
KIWIFY_WEBHOOK_SECRET = config("KIWIFY_WEBHOOK_SECRET", default="")
KIWIFY_ENABLED = config("KIWIFY_ENABLED", default=True, cast=bool)

# Pacotes de créditos (7 pacotes; preço mínimo R$ 0,26 por crédito)
CREDIT_PACKAGES = [
    {"id": 1, "credits": 50, "price_brl": 25.00, "price_per_credit": 0.50, "name": "Pacote Inicial"},
    {"id": 2, "credits": 100, "price_brl": 40.00, "price_per_credit": 0.40, "name": "Pacote Básico"},
    {"id": 3, "credits": 250, "price_brl": 75.00, "price_per_credit": 0.30, "name": "Pacote Intermediário"},
    {"id": 4, "credits": 500, "price_brl": 160.00, "price_per_credit": 0.32, "name": "Pacote Avançado"},
    {"id": 5, "credits": 1000, "price_brl": 280.00, "price_per_credit": 0.28, "name": "Pacote Premium"},
    {"id": 6, "credits": 2500, "price_brl": 650.00, "price_per_credit": 0.26, "name": "Pacote Enterprise"},
    {"id": 7, "credits": 5000, "price_brl": 1300.00, "price_per_credit": 0.26, "name": "Pacote Corporativo"},
]

# Mapeamento package_id (1-7) -> product_id (UUID) na Kiwify (da URL ao editar o produto)
KIWIFY_PRODUCT_MAP = {
    1: "81d5c7c0-fd44-11f0-bdbc-35f1143ee468",   # 50 Créditos
    2: "3fb792d0-fbd0-11f0-a2a0-c373ee20abd6",   # 100 Créditos
    3: "2a47ec20-fd46-11f0-b377-c79b6942532d",   # 250 Créditos
    4: "61d5db60-fbd0-11f0-b6e2-8f08df4b46ed",   # 500 Créditos
    5: "791453b0-fbd0-11f0-adfe-d9e365e09cfb",   # 1000 Créditos
    6: "a81f2c70-fbd0-11f0-a545-39764c49322b",   # 2500 Créditos
    7: "a95663e0-fd44-11f0-b8ae-d58151848312",   # 5000 Créditos
}

# Cache do token OAuth (expira em 24h)
_oauth_token_cache = {"token": None, "expires_at": 0}


def get_kiwify_token():
    """
    Obtém token OAuth da Kiwify (em cache até expirar).
    Returns:
        str: access_token ou None se falhar.
    """
    import time
    global _oauth_token_cache
    now = time.time()
    if _oauth_token_cache["token"] and now < _oauth_token_cache["expires_at"]:
        return _oauth_token_cache["token"]
    if not KIWIFY_CLIENT_ID or not KIWIFY_CLIENT_SECRET:
        logger.error("KIWIFY_CLIENT_ID ou KIWIFY_CLIENT_SECRET não configurados")
        return None
    try:
        r = requests.post(
            f"{KIWIFY_API_BASE}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": KIWIFY_CLIENT_ID,
                "client_secret": KIWIFY_CLIENT_SECRET,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 86400))
        _oauth_token_cache["token"] = token
        _oauth_token_cache["expires_at"] = now + expires_in - 60  # 1 min de margem
        return token
    except requests.RequestException as e:
        logger.error("Erro ao obter token Kiwify: %s", e)
        return None


def get_checkout_url(package_id, user_email):
    """
    Monta a URL de checkout Kiwify para o pacote, com email na query (obrigatório para associar pagamento ao usuário).
    Args:
        package_id: ID do pacote (1-7).
        user_email: Email do usuário logado (será passado na query).
    Returns:
        str: URL para redirecionar o usuário, ou None se falhar.
    """
    if not KIWIFY_ENABLED or not KIWIFY_ACCOUNT_ID:
        logger.error("Kiwify não habilitado ou KIWIFY_ACCOUNT_ID ausente")
        return None
    product_id = KIWIFY_PRODUCT_MAP.get(package_id)
    if not product_id:
        logger.error("Pacote %s não encontrado em KIWIFY_PRODUCT_MAP", package_id)
        return None
    token = get_kiwify_token()
    if not token:
        return None
    try:
        r = requests.get(
            f"{KIWIFY_API_BASE}/products/{product_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "x-kiwify-account-id": KIWIFY_ACCOUNT_ID,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        links = data.get("links") or []
        if not links:
            logger.error("Produto %s sem links de checkout", product_id)
            return None
        # Prefer checkout link (is_sales_page=False); first link is often the sales page
        checkout_link = next(
            (lnk for lnk in links if lnk.get("is_sales_page") is False),
            links[0],
        )
        slug = checkout_link.get("id")
        if not slug:
            logger.error("Produto %s link sem id (slug)", product_id)
            return None
        base = f"https://pay.kiwify.com.br/{slug}"
        params = {"email": user_email, "region": "br"}
        return f"{base}?{urllib.parse.urlencode(params)}"
    except requests.RequestException as e:
        logger.error("Erro ao buscar produto Kiwify %s: %s", product_id, e)
        return None


def _product_id_to_credits(product_id):
    """Mapeia product_id (UUID) da Kiwify para quantidade de créditos."""
    for pkg_id, uuid in KIWIFY_PRODUCT_MAP.items():
        if uuid == product_id:
            pkg = next((p for p in CREDIT_PACKAGES if p["id"] == pkg_id), None)
            return pkg["credits"] if pkg else None
    return None


def handle_webhook_event(request_body, request_headers=None):
    """
    Processa o payload do webhook Kiwify (compra_aprovada / pix_gerado).
    Usa order_id para idempotência; Customer.email para UserProfile; Product.product_id para créditos.
    Args:
        request_body: bytes ou str (JSON).
        request_headers: dict opcional (para validar token se a Kiwify enviar).
    Returns:
        bool: True se processado com sucesso (ou já processado), False se erro.
    """
    import json
    from .models import UserProfile
    from .credit_service import add_credits
    from .models import CreditTransaction

    request_headers = request_headers or {}
    try:
        if isinstance(request_body, bytes):
            request_body = request_body.decode("utf-8")
        data = json.loads(request_body)
    except (ValueError, TypeError) as e:
        logger.error("Webhook Kiwify: JSON inválido: %s", e)
        return False

    order_id = data.get("order_id")
    order_status = data.get("order_status")
    if not order_id:
        logger.error("Webhook Kiwify: order_id ausente")
        return False
    if order_status != "paid":
        logger.info("Webhook Kiwify: order_id=%s status=%s, ignorando", order_id, order_status)
        return True  # 200 para não reenviar

    # Idempotência
    if CreditTransaction.objects.filter(kiwify_sale_id=order_id).exists():
        logger.info("Webhook Kiwify: order_id=%s já processado", order_id)
        return True

    product = data.get("Product") or {}
    customer = data.get("Customer") or {}
    product_id = product.get("product_id")
    customer_email = customer.get("email")
    if not product_id or not customer_email:
        logger.error("Webhook Kiwify: Product.product_id ou Customer.email ausente")
        return False

    credits = _product_id_to_credits(product_id)
    if not credits:
        logger.error("Webhook Kiwify: product_id %s não mapeado para créditos", product_id)
        return False

    try:
        user_profile = UserProfile.objects.get(email=customer_email)
    except UserProfile.DoesNotExist:
        logger.error("Webhook Kiwify: UserProfile não encontrado para email=%s", customer_email)
        return False

    success, new_balance, error = add_credits(
        user_profile,
        credits,
        description=f"Compra de {credits} créditos via Kiwify (order_id={order_id})",
        kiwify_sale_id=order_id,
        payment_gateway="kiwify",
    )
    if success:
        logger.info("Créditos adicionados: %s para %s (order_id=%s)", credits, user_profile.email, order_id)
        return True
    logger.error("Webhook Kiwify: falha ao creditar: %s", error)
    return False
