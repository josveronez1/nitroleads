# Configuração Kiwify (Pagamentos)

O NitroLeads usa a Kiwify como gateway de pagamento (PIX, Boleto, Cartão). Este documento descreve o mapeamento de pacotes e a configuração do webhook.

## Mapeamento package_id → product_id (Kiwify)

O UUID do produto é o que aparece na URL ao editar o produto no dashboard Kiwify (`.../products/edit/<UUID>`).

| package_id | Créditos | Nome                  | UUID do produto (Kiwify)     |
|------------|----------|-----------------------|------------------------------|
| 1          | 50       | Pacote Inicial        | 81d5c7c0-fd44-11f0-bdbc-35f1143ee468 |
| 2          | 100      | Pacote Básico         | 3fb792d0-fbd0-11f0-a2a0-c373ee20abd6 |
| 3          | 250      | Pacote Intermediário  | 2a47ec20-fd46-11f0-b377-c79b6942532d |
| 4          | 500      | Pacote Avançado       | 61d5db60-fbd0-11f0-b6e2-8f08df4b46ed |
| 5          | 1000     | Pacote Premium        | 791453b0-fbd0-11f0-adfe-d9e365e09cfb |
| 6          | 2500     | Pacote Enterprise     | a81f2c70-fbd0-11f0-a545-39764c49322b |
| 7          | 5000     | Pacote Corporativo    | a95663e0-fd44-11f0-b8ae-d58151848312 |

O mapeamento em código está em `lead_extractor/kiwify_service.py` (`KIWIFY_PRODUCT_MAP`).

## Variáveis de ambiente (.env)

- `KIWIFY_CLIENT_ID` – da API Key (Apps → API → Criar API Key)
- `KIWIFY_CLIENT_SECRET` – da mesma API Key
- `KIWIFY_ACCOUNT_ID` – x-kiwify-account-id (dashboard)
- `KIWIFY_WEBHOOK_SECRET` – token exibido ao criar o webhook
- `KIWIFY_ENABLED` – `true` para habilitar (opcional, default true)

## Webhook na Kiwify

1. Apps → Webhooks → Criar webhook
2. **URL do Webhook**: `https://<SEU_DOMINIO>/webhook/kiwify/`
3. **Token**: copiar e colocar em `KIWIFY_WEBHOOK_SECRET`
4. **Produtos**: "Todos que sou produtor" (ou os produtos desejados)
5. **Eventos**: marcar **Compra aprovada** (e opcionalmente **Pix gerado**)

Em desenvolvimento local, use ngrok: `ngrok http 8000` e URL `https://<subdominio>.ngrok.io/webhook/kiwify/`.

## Associação usuário ↔ pagamento

O crédito é atribuído ao usuário pelo **email**: no checkout enviamos `?email=<email_do_usuario>` na URL da Kiwify; no webhook usamos `Customer.email` para buscar o `UserProfile` e creditar. Por isso o email na URL do checkout é obrigatório.
