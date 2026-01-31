# Configuração do Mercado Pago - NitroLeads

Este documento descreve os passos manuais para configurar a integração com o Mercado Pago na plataforma de desenvolvedores.

## 1. Criar aplicação e acessar credenciais

1. Acesse **Mercado Pago Developers**: https://www.mercadopago.com.br/developers/panel/app
2. Clique em **Entrar** (canto superior direito) e faça login com sua conta Mercado Pago
3. Clique em **Suas integrações** (canto superior direito)
4. **Criar aplicação (se ainda não tiver):** Clique em "Criar aplicação" ou selecione uma existente. Dê um nome (ex.: "NitroLeads") e salve
5. No menu **à esquerda**, abra:
   - **Testes > Credenciais de teste** — para desenvolvimento
   - **Produção > Credenciais de produção** — para pagamentos reais (só aparece após ativar produção)

### Chaves necessárias

| Onde usar              | Nome no painel         | Variável no .env              |
|------------------------|------------------------|-------------------------------|
| Frontend (navegador)   | **Public Key**         | `MERCADOPAGO_PUBLIC_KEY`      |
| Backend (servidor)     | **Access Token**       | `MERCADOPAGO_ACCESS_TOKEN`    |
| Backend (webhook)      | **Assinatura secreta** | `MERCADOPAGO_WEBHOOK_SECRET`  |

- **Credenciais de teste:** Disponíveis assim que a aplicação é criada
- **Credenciais de produção:** Após ativar produção (passo 2)

## 2. Ativar credenciais de produção (para pagamentos reais)

1. Em [Suas integrações](https://www.mercadopago.com.br/developers/panel/app), selecione sua aplicação
2. No menu à esquerda, vá em **Produção > Credenciais de produção**
3. Preencha:
   - **Indústria:** ramo do seu negócio
   - **Website (obrigatório):** URL do site (ex.: `https://nitroleads.online`)
   - Aceite Declaração de Privacidade e Termos e condições
   - Resolva o reCAPTCHA e clique em **Ativar credenciais de produção**
4. Anote a **Public Key** e o **Access Token** de produção e configure no `.env` em produção

## 3. Configurar Webhooks (notificações de pagamento)

1. Em **Suas integrações**, selecione a aplicação
2. No menu à esquerda: **Webhooks > Configurar notificações**
3. **URL modo produção:**
   - Informe: `https://nitroleads.online/webhook/mercadopago/`
   - Para testes locais, use um túnel (ngrok) e configure em "URL modo teste"
4. **Eventos:** Marque o evento **Pagamentos** (tópico `payment`)
5. Clique em **Salvar**
6. Após salvar, copie a **assinatura secreta** e configure como `MERCADOPAGO_WEBHOOK_SECRET` no `.env`
7. (Opcional) Use **Simular** no painel para testar se a URL responde 200

## 4. Variáveis no .env

```env
MERCADOPAGO_ACCESS_TOKEN=seu-access-token
MERCADOPAGO_PUBLIC_KEY=sua-public-key
MERCADOPAGO_WEBHOOK_SECRET=assinatura-secreta
BASE_URL=https://nitroleads.online
```

## Referências

- [Credenciais - Documentação MP](https://www.mercadopago.com.br/developers/pt/docs/your-integrations/credentials)
- [Webhooks - Documentação MP](https://www.mercadopago.com.br/developers/pt/docs/your-integrations/notifications/webhooks)
- [Checkout Bricks](https://www.mercadopago.com.br/developers/pt/docs/checkout-bricks/landing)
