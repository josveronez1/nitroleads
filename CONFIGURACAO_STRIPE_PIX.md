# Configuração de Métodos de Pagamento no Stripe (PIX e Boleto)

## Métodos Disponíveis

- **Cartão de Crédito**: Sempre habilitado
- **Boleto**: Habilitado por padrão (requer conta Stripe no Brasil)
- **PIX**: Desabilitado por padrão (pode estar bloqueado na conta)

## Configuração do Boleto

### Requisitos para Boleto funcionar

1. **Conta Stripe no Brasil**
   - O boleto está disponível apenas para contas Stripe no Brasil
   - Verifique se sua conta está configurada para o Brasil no dashboard do Stripe

2. **Chaves de API de Produção**
   - Boleto funciona com chaves de **PRODUÇÃO** (começa com `sk_live_`)
   - Também funciona em modo teste (começa com `sk_test_`) para testes

3. **Habilitar Boleto na Conta Stripe**

   - Acesse https://dashboard.stripe.com
   - Vá em **Settings** > **Payment methods**
   - Procure por **Boleto** na lista de métodos de pagamento
   - Se não estiver habilitado, clique em **Enable** ou **Ativar**
   - Boleto geralmente está disponível automaticamente para contas brasileiras

4. **Configuração no .env**

   ```bash
   # Stripe - Boleto habilitado por padrão
   STRIPE_ENABLE_BOLETO=True
   STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxxx  # ou sk_test_ para testes
   ```

### Características do Boleto

- **Vencimento**: 3 dias após a emissão (configurável)
- **Processamento**: Pode levar até 2 dias úteis após o pagamento
- **Disponível**: Contas Stripe no Brasil

## Configuração do PIX

### Requisitos para PIX funcionar

### 1. Conta Stripe no Brasil
- O PIX está disponível apenas para contas Stripe no Brasil
- Verifique se sua conta está configurada para o Brasil no dashboard do Stripe

### 2. Chaves de API de Produção
- **IMPORTANTE**: PIX só funciona com chaves de **PRODUÇÃO**, não funciona em modo teste
- Verifique se está usando `STRIPE_SECRET_KEY` de produção (começa com `sk_live_`)
- Chaves de teste (começam com `sk_test_`) não suportam PIX

### 3. Habilitar PIX na Conta Stripe

#### Passo a passo:

1. **Acesse o Dashboard do Stripe**
   - Vá para https://dashboard.stripe.com
   - Faça login na sua conta

2. **Verifique a Região da Conta**
   - Vá em **Settings** > **Account details**
   - Confirme que o país está configurado como **Brasil**

3. **Habilitar PIX**
   - Vá em **Settings** > **Payment methods**
   - Procure por **PIX** na lista de métodos de pagamento
   - Se não estiver habilitado, clique em **Enable** ou **Ativar**
   - PIX geralmente está disponível automaticamente para contas brasileiras

4. **Verificar Status da Conta**
   - Vá em **Settings** > **Account details**
   - Verifique se a conta está **ativada** e **verificada**
   - Contas em modo teste podem não ter PIX disponível

### 4. Configuração no .env

Certifique-se de que o `.env` tem:

```bash
# Stripe - PRODUÇÃO (PIX só funciona em produção)
STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxxx
STRIPE_ENABLE_PIX=True

# Stripe Webhook Secret (para produção)
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
```

### 5. Testar PIX

Após configurar:

1. Acesse a página de compra de créditos
2. Selecione um pacote ou quantidade customizada
3. Clique em "Comprar"
4. No checkout do Stripe, você deve ver a opção **PIX** disponível
5. Se não aparecer, verifique os logs do servidor para erros

### 6. Troubleshooting

**PIX não aparece no checkout:**
- Verifique se está usando chave de **PRODUÇÃO** (sk_live_)
- Verifique se a conta Stripe está no Brasil
- Verifique se PIX está habilitado no dashboard
- Verifique os logs do servidor para erros do Stripe

**Erro ao criar checkout com PIX:**
- O código tem fallback automático: se PIX falhar, tenta apenas com cartão
- Verifique os logs para ver o erro específico do Stripe
- Erros comuns:
  - "PIX is not available" → Conta não está no Brasil ou PIX não habilitado
  - "Invalid payment method" → Chave de teste sendo usada (PIX não funciona em teste)

### 7. Verificar se PIX está funcionando

Execute este comando no servidor para verificar os logs:

```bash
tail -f ~/logs/nitroleads/gunicorn.log | grep -i "pix\|stripe"
```

Ou verifique os logs do Stripe no dashboard:
- Vá em **Developers** > **Logs**
- Procure por tentativas de criar checkout com PIX

### 8. Documentação Oficial

- [Stripe PIX Documentation](https://stripe.com/docs/payments/pix)
- [Stripe Brazil Setup](https://stripe.com/docs/payments/payment-methods/overview)

## Nota Importante

**PIX só funciona em PRODUÇÃO**. Se você estiver testando localmente ou em ambiente de desenvolvimento, use chaves de teste e o PIX não estará disponível. Para testar PIX, você precisa:

1. Usar chaves de produção
2. Ter uma conta Stripe brasileira verificada
3. Ter PIX habilitado no dashboard

