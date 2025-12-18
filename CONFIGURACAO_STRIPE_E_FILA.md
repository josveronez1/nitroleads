# Configuração do Stripe e Processador de Fila

## 1. Configurar Stripe

### 1.1 Obter chaves do Stripe

1. Acesse: https://dashboard.stripe.com/
2. Faça login ou crie uma conta
3. Certifique-se de estar no **modo de teste** (Test mode) inicialmente
4. Vá em **Developers > API keys**

Você precisará de:
- **Publishable key** (chave pública) - `pk_test_...` ou `pk_live_...`
- **Secret key** (chave secreta) - `sk_test_...` ou `sk_live_...`
- **Webhook signing secret** - será obtido após configurar o webhook

### 1.2 Configurar Webhook no Stripe

1. No dashboard do Stripe, vá em **Developers > Webhooks**
2. Clique em **Add endpoint**
3. Configure:
   - **Endpoint URL**: `https://nitroleads.online/webhook/stripe/`
   - **Events to send**: Selecione `checkout.session.completed`
   - Clique em **Add endpoint**

4. **Copie o Signing secret** que aparece após criar (começa com `whsec_...`)

### 1.3 Adicionar variáveis ao .env no servidor

No servidor VPS, edite o arquivo `.env`:

```bash
# No servidor VPS
su - nitroleads
cd ~/apps/nitroleads
nano .env
```

Adicione/atualize estas linhas:

```bash
# Stripe Configuration
STRIPE_SECRET_KEY=sk_test_... # ou sk_live_... em produção
STRIPE_PUBLIC_KEY=pk_test_... # ou pk_live_... em produção (opcional, se usar no frontend)
STRIPE_WEBHOOK_SECRET=whsec_... # Secret do webhook
BASE_URL=https://nitroleads.online
```

**Importante:**
- Use `sk_test_` e `pk_test_` para desenvolvimento/testes
- Use `sk_live_` e `pk_live_` para produção (após testar)
- O `STRIPE_PUBLIC_KEY` é opcional se você não usar Stripe.js no frontend diretamente

### 1.4 Testar Stripe em modo de desenvolvimento

1. Certifique-se de estar usando as chaves de teste (`sk_test_...`)
2. Acesse a página de compra de créditos
3. Use o cartão de teste: `4242 4242 4242 4242`
4. Use qualquer data futura, qualquer CVC e qualquer CEP
5. Para PIX de teste, o Stripe gera um QR Code que você pode testar

### 1.5 Configurar para produção (quando estiver pronto)

1. No dashboard do Stripe, mude para **Live mode**
2. Copie as chaves de produção (`sk_live_...`, `pk_live_...`)
3. Configure novo webhook para modo live com URL de produção
4. Atualize o `.env` no servidor com as chaves de produção
5. Reinicie o Gunicorn: `supervisorctl restart nitroleads`

---

## 2. Configurar Processador de Fila do Viper

### 2.1 Opção 1: Usando Supervisor (Recomendado)

O Supervisor garante que o processador rode continuamente e reinicie automaticamente em caso de falha.

#### Passo 1: Criar arquivo de configuração do Supervisor

```bash
# No servidor VPS, como root ou com sudo
sudo nano /etc/supervisor/conf.d/nitroleads-queue.conf
```

Adicione o seguinte conteúdo:

```ini
[program:nitroleads-queue]
command=/home/nitroleads/apps/nitroleads/venv/bin/python /home/nitroleads/apps/nitroleads/manage.py process_viper_queue
directory=/home/nitroleads/apps/nitroleads
user=nitroleads
autostart=true
autorestart=true
stderr_logfile=/home/nitroleads/logs/nitroleads/viper_queue_error.log
stdout_logfile=/home/nitroleads/logs/nitroleads/viper_queue.log
stopwaitsecs=600
killasgroup=true
priority=998
environment=DJANGO_SETTINGS_MODULE="lead_extraction.settings"
```

#### Passo 2: Aplicar configuração

```bash
# Ler novas configurações
sudo supervisorctl reread

# Aplicar mudanças
sudo supervisorctl update

# Iniciar o processador
sudo supervisorctl start nitroleads-queue

# Verificar status
sudo supervisorctl status nitroleads-queue
```

#### Passo 3: Verificar se está funcionando

```bash
# Ver logs
tail -f /home/nitroleads/logs/nitroleads/viper_queue.log

# Ver status
sudo supervisorctl status nitroleads-queue
# Deve mostrar: nitroleads-queue RUNNING pid XXXX
```

### 2.2 Opção 2: Usando Cron (Alternativa)

Se preferir usar cron ao invés de supervisor:

```bash
# No servidor VPS
su - nitroleads
crontab -e
```

Adicione as seguintes linhas (processa a fila a cada 10 segundos):

```bash
* * * * * cd /home/nitroleads/apps/nitroleads && /home/nitroleads/apps/nitroleads/venv/bin/python manage.py process_viper_queue --once >> /home/nitroleads/logs/nitroleads/viper_queue.log 2>&1
* * * * * sleep 10 && cd /home/nitroleads/apps/nitroleads && /home/nitroleads/apps/nitroleads/venv/bin/python manage.py process_viper_queue --once >> /home/nitroleads/logs/nitroleads/viper_queue.log 2>&1
* * * * * sleep 20 && cd /home/nitroleads/apps/nitroleads && /home/nitroleads/apps/nitroleads/venv/bin/python manage.py process_viper_queue --once >> /home/nitroleads/logs/nitroleads/viper_queue.log 2>&1
* * * * * sleep 30 && cd /home/nitroleads/apps/nitroleads && /home/nitroleads/apps/nitroleads/venv/bin/python manage.py process_viper_queue --once >> /home/nitroleads/logs/nitroleads/viper_queue.log 2>&1
* * * * * sleep 40 && cd /home/nitroleads/apps/nitroleads && /home/nitroleads/apps/nitroleads/venv/bin/python manage.py process_viper_queue --once >> /home/nitroleads/logs/nitroleads/viper_queue.log 2>&1
* * * * * sleep 50 && cd /home/nitroleads/apps/nitroleads && /home/nitroleads/apps/nitroleads/venv/bin/python manage.py process_viper_queue --once >> /home/nitroleads/logs/nitroleads/viper_queue.log 2>&1
```

**Nota:** A Opção 1 (Supervisor) é **recomendada** porque:
- Roda continuamente (mais eficiente)
- Reinicia automaticamente em caso de falha
- Melhor gerenciamento de logs
- Menos sobrecarga no sistema

---

## 3. Verificar se está tudo funcionando

### 3.1 Testar Stripe

1. Acesse: https://nitroleads.online/purchase/
2. Tente comprar créditos usando cartão de teste
3. Verifique se os créditos foram adicionados após o pagamento

### 3.2 Testar Fila do Viper

1. Faça uma busca no dashboard que requeira dados de sócios
2. Verifique os logs do processador:
   ```bash
   tail -f /home/nitroleads/logs/nitroleads/viper_queue.log
   ```
3. Verifique se os dados dos sócios aparecem na página após o processamento

### 3.3 Comandos úteis

```bash
# Ver status do processador (Supervisor)
sudo supervisorctl status nitroleads-queue

# Reiniciar processador
sudo supervisorctl restart nitroleads-queue

# Parar processador
sudo supervisorctl stop nitroleads-queue

# Ver logs em tempo real
tail -f /home/nitroleads/logs/nitroleads/viper_queue.log

# Ver logs de erro
tail -f /home/nitroleads/logs/nitroleads/viper_queue_error.log

# Testar processador manualmente (uma vez)
cd /home/nitroleads/apps/nitroleads
source venv/bin/activate
python manage.py process_viper_queue --once
```

---

## 4. Troubleshooting

### Problema: Stripe não processa pagamentos

**Solução:**
1. Verifique se as chaves estão corretas no `.env`
2. Verifique se está usando chaves de teste em ambiente de teste
3. Verifique os logs do Django: `tail -f /home/nitroleads/logs/nitroleads/gunicorn.log`
4. Verifique se o webhook está configurado corretamente no Stripe

### Problema: Fila não processa requisições

**Solução:**
1. Verifique se o processador está rodando: `sudo supervisorctl status nitroleads-queue`
2. Verifique os logs: `tail -f /home/nitroleads/logs/nitroleads/viper_queue.log`
3. Verifique se há requisições na fila no Django admin
4. Teste manualmente: `python manage.py process_viper_queue --once`

### Problema: Tokens do Viper expiram muito rápido

**Solução:**
1. Verifique se o cron do auth_bot está rodando: `crontab -l`
2. Reduza o intervalo do cron (ex: a cada 3 horas ao invés de 4)
3. Verifique os logs do auth_bot: `tail -f /home/nitroleads/logs/nitroleads/auth_bot.log`

---

## Checklist Final

- [ ] Chaves do Stripe configuradas no `.env` (teste ou produção)
- [ ] Webhook configurado no Stripe
- [ ] `BASE_URL` configurado no `.env`
- [ ] Processador de fila configurado (Supervisor ou Cron)
- [ ] Processador de fila está rodando (`sudo supervisorctl status nitroleads-queue`)
- [ ] Testado pagamento com Stripe (modo teste)
- [ ] Testado busca que usa fila do Viper
- [ ] Logs sendo gerados corretamente

