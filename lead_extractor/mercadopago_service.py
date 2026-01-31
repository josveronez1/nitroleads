"""
Serviço de integração com Mercado Pago como gateway de pagamento.
Checkout Bricks em modal + webhook para creditar.
"""
import logging
import time
import hmac
import hashlib
from decouple import config
import requests

logger = logging.getLogger(__name__)

# Configuração
MERCADOPAGO_ACCESS_TOKEN = config("MERCADOPAGO_ACCESS_TOKEN", default="")
MERCADOPAGO_WEBHOOK_SECRET = config("MERCADOPAGO_WEBHOOK_SECRET", default="")
BASE_URL = config("BASE_URL", default="http://localhost:8000").rstrip("/")

MP_API_BASE = "https://api.mercadopago.com"

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

# Limites para compra personalizada
CUSTOM_CREDITS_MIN = 10
CUSTOM_CREDITS_MAX = 50000
CUSTOM_PRICE_PER_CREDIT = 0.30


def _get_package_by_id(package_id):
    """Retorna o pacote pelo ID ou None."""
    return next((p for p in CREDIT_PACKAGES if p["id"] == package_id), None)


def _get_headers():
    """Headers para chamadas à API do Mercado Pago."""
    return {
        "Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def create_preference(user_profile, package_id=None, custom_credits=None):
    """
    Cria uma preferência de pagamento no Mercado Pago.

    Aceita pacote fixo (package_id) OU valor personalizado (custom_credits).

    Args:
        user_profile: UserProfile do usuário logado
        package_id: ID do pacote (1-7) para compra de pacote fixo
        custom_credits: Quantidade de créditos para compra personalizada

    Returns:
        dict: {"preference_id", "amount", "credits", "description"} ou None se falhar
    """
    if not MERCADOPAGO_ACCESS_TOKEN:
        logger.error("MERCADOPAGO_ACCESS_TOKEN não configurado")
        return None

    credits = None
    amount = None
    title = None

    if package_id is not None:
        pkg = _get_package_by_id(int(package_id))
        if not pkg:
            logger.error("Pacote %s não encontrado", package_id)
            return None
        credits = pkg["credits"]
        amount = float(pkg["price_brl"])
        title = f"{pkg['name']} - {credits} créditos NitroLeads"

    elif custom_credits is not None:
        custom_credits = int(custom_credits)
        if custom_credits < CUSTOM_CREDITS_MIN or custom_credits > CUSTOM_CREDITS_MAX:
            logger.error("Créditos personalizados fora do range: %s", custom_credits)
            return None
        credits = custom_credits
        amount = round(credits * CUSTOM_PRICE_PER_CREDIT, 2)
        title = f"{credits} créditos NitroLeads (personalizado)"

    else:
        logger.error("Nem package_id nem custom_credits fornecido")
        return None

    timestamp = int(time.time())
    external_reference = f"{user_profile.id}:{credits}:{timestamp}"

    notification_url = f"{BASE_URL}/webhook/mercadopago/"
    if MERCADOPAGO_WEBHOOK_SECRET:
        notification_url += "?source_news=webhooks"

    payload = {
        "items": [
            {
                "id": f"credits-{credits}",
                "title": title,
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": amount,
            }
        ],
        "payer": {"email": user_profile.email},
        "external_reference": external_reference,
        "notification_url": notification_url,
        "back_urls": {
            "success": f"{BASE_URL}/payment/success/",
            "pending": f"{BASE_URL}/payment/success/?status=pending",
            "failure": f"{BASE_URL}/payment/cancel/",
        },
        "auto_return": "approved",
        "statement_descriptor": "NITROLEADS",
    }

    try:
        r = requests.post(
            f"{MP_API_BASE}/checkout/preferences",
            headers=_get_headers(),
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        pref_id = data.get("id")
        if not pref_id:
            logger.error("Resposta MP sem preference id: %s", data)
            return None
        return {
            "preference_id": pref_id,
            "amount": amount,
            "credits": credits,
            "description": title,
            "external_reference": external_reference,
        }
    except requests.RequestException as e:
        logger.error("Erro ao criar preferência MP: %s", e)
        if hasattr(e, "response") and e.response is not None:
            try:
                err_body = e.response.json()
                logger.error("Resposta MP: %s", err_body)
            except Exception:
                pass
        return None


def validate_webhook_signature(body, headers, secret):
    """
    Valida a assinatura x-signature do webhook do Mercado Pago.

    Args:
        body: dict (JSON parseado) do corpo da requisição
        headers: dict com os headers (META ou similar)
        secret: MERCADOPAGO_WEBHOOK_SECRET

    Returns:
        bool: True se a assinatura é válida
    """
    if not secret:
        return True  # Se não configurado, aceitar (modo desenvolvimento)

    x_signature = headers.get("HTTP_X_SIGNATURE") or headers.get("x-signature", "")
    x_request_id = headers.get("HTTP_X_REQUEST_ID") or headers.get("x-request-id", "")

    if not x_signature:
        return False

    parts = {}
    for part in x_signature.split(","):
        kv = part.split("=", 1)
        if len(kv) == 2:
            parts[kv[0].strip()] = kv[1].strip()

    ts = parts.get("ts")
    received_hash = parts.get("v1")
    if not ts or not received_hash:
        return False

    data_obj = body if isinstance(body, dict) else {}
    data_id = str(data_obj.get("data", {}).get("id", ""))
    if not data_id:
        return False

    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    calculated_hash = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(calculated_hash, received_hash)


def handle_webhook(body, headers):
    """
    Processa o webhook do Mercado Pago (notificações de pagamento).

    Valida assinatura, busca detalhes do pagamento e credita se aprovado.

    Args:
        body: bytes ou str (JSON) do corpo
        headers: dict de headers (request.META)

    Returns:
        bool: True se processado com sucesso (ou já processado), False se erro
    """
    import json

    from .models import UserProfile, CreditTransaction
    from .credit_service import add_credits

    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        data = json.loads(body) if isinstance(body, str) else body
    except (ValueError, TypeError) as e:
        logger.error("Webhook MP: JSON inválido: %s", e)
        return False

    notif_type = data.get("type")
    if notif_type != "payment":
        logger.info("Webhook MP: type=%s ignorado", notif_type)
        return True

    payment_id = data.get("data", {}).get("id")
    if not payment_id:
        logger.error("Webhook MP: data.id ausente")
        return False

    if MERCADOPAGO_WEBHOOK_SECRET and not validate_webhook_signature(
        data, headers, MERCADOPAGO_WEBHOOK_SECRET
    ):
        logger.error("Webhook MP: assinatura inválida")
        return False

    if CreditTransaction.objects.filter(mp_payment_id=str(payment_id)).exists():
        logger.info("Webhook MP: payment_id=%s já processado", payment_id)
        return True

    try:
        r = requests.get(
            f"{MP_API_BASE}/v1/payments/{payment_id}",
            headers=_get_headers(),
            timeout=10,
        )
        r.raise_for_status()
        payment = r.json()
    except requests.RequestException as e:
        logger.error("Webhook MP: Erro ao buscar payment %s: %s", payment_id, e)
        return False

    status = payment.get("status")
    if status != "approved":
        logger.info("Webhook MP: payment_id=%s status=%s, ignorando", payment_id, status)
        return True

    ext_ref = payment.get("external_reference", "")
    if not ext_ref:
        logger.error("Webhook MP: external_reference ausente no payment %s", payment_id)
        return False

    parts = ext_ref.split(":")
    if len(parts) < 2:
        logger.error("Webhook MP: external_reference inválido: %s", ext_ref)
        return False

    try:
        user_id = int(parts[0])
        credits = int(parts[1])
    except (ValueError, IndexError):
        logger.error("Webhook MP: external_reference inválido: %s", ext_ref)
        return False

    try:
        user_profile = UserProfile.objects.get(id=user_id)
    except UserProfile.DoesNotExist:
        logger.error("Webhook MP: UserProfile id=%s não encontrado", user_id)
        return False

    success, new_balance, error = add_credits(
        user_profile,
        credits,
        description=f"Compra de {credits} créditos via Mercado Pago",
        mp_payment_id=str(payment_id),
        payment_gateway="mercadopago",
    )

    if success:
        logger.info(
            "Créditos adicionados: %s para %s (payment_id=%s)",
            credits,
            user_profile.email,
            payment_id,
        )
        return True

    logger.error("Webhook MP: falha ao creditar: %s", error)
    return False


def process_payment(form_data, amount, description, external_reference, payer_email, selected_payment_method=None):
    """
    Cria um pagamento no Mercado Pago a partir dos dados do Payment Brick.

    O Brick envia formData no onSubmit; esta função monta o payload e chama a API de pagamentos.

    Args:
        form_data: dict do Brick (formData) - estrutura varia por método (card, pix, etc)
        amount: float, valor da transação
        description: str, descrição do pagamento
        external_reference: str, ex: "user_id:credits:timestamp"
        payer_email: str, email do pagador
        selected_payment_method: str opcional do Brick (pix, credit_card, bolbradesco, etc)

    Returns:
        dict: Resposta da API MP com status, id, etc. Ou None se falhar.
    """
    import uuid

    if not MERCADOPAGO_ACCESS_TOKEN:
        logger.error("MERCADOPAGO_ACCESS_TOKEN não configurado")
        return None

    if not isinstance(form_data, dict):
        form_data = {}

    payment_method_id = (
        form_data.get("paymentMethodId")
        or form_data.get("payment_method_id")
        or (selected_payment_method if isinstance(selected_payment_method, str) else None)
        or "pix"
    )

    # Normalizar payment_method_id para PIX e boleto
    if selected_payment_method == "bank_transfer" or payment_method_id == "bank_transfer":
        payment_method_id = "pix"
    elif selected_payment_method == "ticket" or payment_method_id == "ticket":
        payment_method_id = "bolbradesco"

    amount_float = float(amount) if amount is not None else 0
    if amount_float <= 0:
        logger.error("Valor inválido: %s", amount)
        return None

    payload = {
        "transaction_amount": amount_float,
        "description": description or "Créditos NitroLeads",
        "payment_method_id": payment_method_id,
        "external_reference": external_reference or "",
        "payer": {
            "email": payer_email or "",
        },
    }

    # Cartão de crédito: token, installments, issuer_id, identification
    if "token" in form_data and form_data.get("token"):
        payload["token"] = form_data.get("token") or form_data.get("Token")
        payload["installments"] = int(
            form_data.get("installments") or form_data.get("Installments") or 1
        )
        issuer = form_data.get("issuerId") or form_data.get("issuer_id")
        if issuer is not None:
            payload["issuer_id"] = str(issuer)
        payer_obj = payload["payer"]
        p = form_data.get("payer") or {}
        ident = p.get("identification") or {}
        if isinstance(ident, dict):
            id_type = ident.get("type") or ident.get("identificationType") or "CPF"
            id_number = ident.get("number") or ident.get("identificationNumber") or ""
            if id_number:
                payer_obj["identification"] = {"type": id_type, "number": str(id_number).replace(".", "").replace("-", "")}

    # PIX e Boleto: payer.identification pode ser necessário
    elif payment_method_id in ("pix", "bolbradesco"):
        p = form_data.get("payer") or {}
        ident = p.get("identification") or {}
        if isinstance(ident, dict):
            id_type = ident.get("type") or ident.get("identificationType") or "CPF"
            id_number = ident.get("number") or ident.get("identificationNumber") or ""
            if id_number:
                payload["payer"]["identification"] = {"type": id_type, "number": str(id_number).replace(".", "").replace("-", "")}

    headers = {
        **_get_headers(),
        "X-Idempotency-Key": str(uuid.uuid4()),
    }

    try:
        r = requests.post(
            f"{MP_API_BASE}/v1/payments",
            headers=headers,
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.error("Erro ao criar pagamento MP: %s", e)
        if hasattr(e, "response") and e.response is not None:
            try:
                logger.error("Resposta MP: %s", e.response.text[:500])
            except Exception:
                pass
        return None
