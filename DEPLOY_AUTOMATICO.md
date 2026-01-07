# Guia de Configuração - Deploy Automático via GitHub Webhook

Este guia explica como configurar o deploy automático que será executado sempre que você fizer push na branch `main` do repositório GitHub.

---

## 📋 Pré-requisitos

- Repositório Git configurado no servidor
- Acesso SSH ao servidor VPS
- Repositório GitHub configurado

---

## 🔧 Passo 1: Gerar Secret para o Webhook

### No seu computador local:

```bash
# Gerar uma string aleatória para usar como secret
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Anote essa string** - você vai usar ela nos próximos passos.

---

## 🔧 Passo 2: Configurar no Servidor VPS

### 2.1 Conectar ao servidor

```bash
ssh nitroleads@seu-servidor
```

### 2.2 Adicionar secret ao arquivo .env

```bash
cd ~/apps/nitroleads
nano .env
```

Adicione a linha (substitua pela string que você gerou):

```bash
GITHUB_WEBHOOK_SECRET=sua-string-secreta-aqui
```

Salve o arquivo (Ctrl+X, Y, Enter).

### 2.3 Fazer upload do script de deploy

**Opção A: Se você já fez upload dos arquivos via Git:**

```bash
cd ~/apps/nitroleads
git pull origin main
```

**Opção B: Upload manual do script:**

```bash
# Copiar o script deploy-webhook.sh para o servidor
# Você pode fazer isso via scp do seu computador local:
# scp deploy-webhook.sh nitroleads@seu-servidor:~/apps/nitroleads/
```

### 2.4 Tornar o script executável

```bash
cd ~/apps/nitroleads
chmod +x deploy-webhook.sh
```

### 2.5 Testar o script manualmente (opcional)

```bash
# Testar se o script funciona
./deploy-webhook.sh
```

Se houver algum erro, corrija antes de continuar.

### 2.6 Reiniciar a aplicação Django

```bash
sudo supervisorctl restart nitroleads
```

### 2.7 Verificar se o endpoint está funcionando

```bash
# Testar o endpoint (deve retornar erro 405 - método não permitido para GET)
curl http://localhost:8000/webhook/github/
```

---

## 🔧 Passo 3: Configurar Webhook no GitHub

### 3.1 Acessar configurações do repositório

1. Acesse: `https://github.com/seu-usuario/seu-repositorio/settings/hooks`
2. Ou vá em: **Settings** → **Webhooks** → **Add webhook**

### 3.2 Configurar o webhook

Preencha os campos:

- **Payload URL**: `https://nitroleads.online/webhook/github/`
  - ⚠️ Substitua `nitroleads.online` pelo seu domínio real
  
- **Content type**: `application/json`

- **Secret**: Cole a mesma string secreta que você gerou no Passo 1

- **Which events would you like to trigger this webhook?**
  - Selecione: **Just the push event**
  - Ou selecione: **Let me select individual events** e marque apenas **Pushes**

- **Active**: ✅ Marque como ativo

### 3.3 Salvar

Clique em **Add webhook**

---

## 🔧 Passo 4: Testar o Deploy Automático

### 4.1 Fazer um teste no repositório

```bash
# No seu computador local
cd /Users/josveronez/Documents/projects/LEAD_FUCKING_EXTRACTION_BABY

# Fazer uma pequena mudança (criar um arquivo de teste)
echo "# Teste de deploy automático" >> test-deploy.txt

# Commit e push
git add test-deploy.txt
git commit -m "Teste: deploy automático via webhook"
git push origin main
```

### 4.2 Verificar no GitHub

1. Volte para a página de webhooks do GitHub
2. Clique no webhook que você criou
3. Role até **Recent Deliveries**
4. Você deve ver uma requisição recente
5. Clique nela para ver os detalhes:
   - Se for **200**, o deploy foi acionado com sucesso
   - Se for **401**, o secret está incorreto
   - Se for **404**, a URL está incorreta

### 4.3 Verificar no servidor

```bash
# No servidor, verificar logs do deploy
tail -f ~/logs/nitroleads/deploy.log

# Ou verificar logs do Django
tail -f ~/apps/nitroleads/logs/django.log
```

### 4.4 Verificar se o deploy aconteceu

```bash
# Verificar commit atual
cd ~/apps/nitroleads
git log -1 --oneline

# Verificar se os serviços reiniciaram
sudo supervisorctl status
```

---

## 🔍 Troubleshooting

### Erro 401 - Invalid signature

**Problema**: O secret no `.env` não confere com o do GitHub.

**Solução**:
1. Verifique se o secret no `.env` está correto
2. Verifique se o secret no GitHub está correto
3. Reinicie o Django: `sudo supervisorctl restart nitroleads`

### Erro 404 - Not found

**Problema**: A URL do webhook está incorreta.

**Solução**:
1. Verifique a URL no GitHub
2. Verifique se a rota está configurada em `urls.py`
3. Teste a URL manualmente: `curl http://localhost:8000/webhook/github/`

### Deploy não executa

**Problema**: O script não está sendo executado.

**Solução**:
1. Verifique se o script existe: `ls -la ~/apps/nitroleads/deploy-webhook.sh`
2. Verifique permissões: `chmod +x ~/apps/nitroleads/deploy-webhook.sh`
3. Teste manualmente: `./deploy-webhook.sh`
4. Verifique logs: `tail -f ~/logs/nitroleads/deploy.log`

### Erro de permissões

**Problema**: O script não consegue executar comandos sudo.

**Solução**:
1. Configure sudo sem senha para o usuário nitroleads:
```bash
sudo visudo
# Adicione a linha:
nitroleads ALL=(ALL) NOPASSWD: /usr/bin/supervisorctl
```

### Webhook não aparece no GitHub

**Problema**: O GitHub não consegue acessar sua URL.

**Solução**:
1. Verifique se seu servidor está acessível publicamente
2. Verifique se o Nginx está configurado corretamente
3. Teste a URL: `curl https://nitroleads.online/webhook/github/`

---

## 📝 Checklist Final

- [ ] Secret gerado e anotado
- [ ] Secret adicionado ao `.env` no servidor
- [ ] Script `deploy-webhook.sh` no servidor e executável
- [ ] Django reiniciado após adicionar a view
- [ ] Webhook configurado no GitHub com URL correta
- [ ] Secret configurado no GitHub (mesmo do `.env`)
- [ ] Teste feito e funcionando
- [ ] Logs verificados

---

## 🎉 Pronto!

Agora, sempre que você fizer `git push origin main`, o deploy será executado automaticamente no servidor em poucos segundos!

Para verificar se o deploy está funcionando, você pode:
- Verificar os logs: `tail -f ~/logs/nitroleads/deploy.log`
- Verificar os deliveries do webhook no GitHub
- Verificar a última atualização no servidor: `cd ~/apps/nitroleads && git log -1`

