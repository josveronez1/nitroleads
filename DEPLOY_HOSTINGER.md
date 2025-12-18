# Guia de Deploy - NitroLeads na Hostinger

Este guia vai te ajudar a fazer deploy do NitroLeads na Hostinger.

## Pré-requisitos

1. Conta na Hostinger com **VPS** ou **Cloud Hosting** (Django não funciona em hospedagem compartilhada tradicional)
2. Domínio configurado na Hostinger
3. Acesso SSH ao servidor
4. Python 3.9+ instalado no servidor

---

## Passo 1: Preparar o Projeto Localmente

### 1.1 Criar arquivo .env.production

Crie um arquivo `.env.production` com as variáveis de ambiente para produção:

```bash
# Django
SECRET_KEY=sua-chave-secreta-aqui-gerada-aleatoriamente
DEBUG=False
ALLOWED_HOSTS=seudominio.com,www.seudominio.com
CSRF_TRUSTED_ORIGINS=https://seudominio.com,https://www.seudominio.com

# Database (Supabase - já está configurado)
DATABASE_URL=postgresql://postgres.icarmyjhaxzupgxmtkno:7471357Jv@@@@aws-0-us-west-2.pooler.supabase.com:6543/postgres

# APIs
SERPER_API_KEY=38f602d2b5b26e482393cb26d902be6b415ce351
VIPER_API_KEY=ba5ebed96d4a3330af1aa91c98b2fee9556
VIPER_USER=viper@30787
VIPER_PASS=Pascotini#87

# Supabase Auth
SUPABASE_URL=https://icarmyjhaxzupgxmtkno.supabase.co
SUPABASE_KEY=sua-supabase-key-aqui
SUPABASE_JWT_SECRET=seu-jwt-secret-aqui

# Stripe (quando for implementar)
STRIPE_SECRET_KEY=sk_live_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx
BASE_URL=https://seudominio.com
```

**⚠️ IMPORTANTE:**
- Gere um novo `SECRET_KEY` para produção: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- Substitua `seudominio.com` pelo seu domínio real
- Use `DEBUG=False` em produção

---

## Passo 2: Conectar ao Servidor Hostinger via SSH

```bash
ssh usuario@seu-ip-ou-dominio
```

Se você não tem as credenciais SSH, acesse o painel da Hostinger → VPS/Cloud → SSH Access.

---

## Passo 3: Configurar o Servidor

### 3.1 Atualizar sistema

```bash
sudo apt update
sudo apt upgrade -y
```

### 3.2 Instalar Python e dependências

```bash
# Instalar Python 3.9+ e pip
sudo apt install python3 python3-pip python3-venv python3-dev -y

# Instalar PostgreSQL client (para conectar ao Supabase)
sudo apt install libpq-dev postgresql-client -y

# Instalar outras dependências
sudo apt install nginx supervisor git -y

# Instalar Playwright system dependencies (necessário para o auth_bot)
sudo apt install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2
```

---

## Passo 4: Criar Usuário e Estrutura de Diretórios

### 4.1 Criar usuário para a aplicação (opcional mas recomendado)

```bash
sudo adduser --disabled-password --gecos "" nitroleads
sudo su - nitroleads
```

### 4.2 Criar estrutura de diretórios

```bash
mkdir -p ~/apps/nitroleads
mkdir -p ~/logs/nitroleads
cd ~/apps/nitroleads
```

---

## Passo 5: Fazer Upload do Código

### Opção A: Via Git (Recomendado)

```bash
# No servidor
cd ~/apps/nitroleads
git clone https://github.com/seu-usuario/seu-repositorio.git .

# Ou se já tiver um repositório, faça:
git init
git remote add origin https://github.com/seu-usuario/seu-repositorio.git
git pull origin main
```

### Opção B: Via SCP (do seu computador local)

```bash
# Do seu computador local
scp -r /Users/josveronez/Documents/projects/LEAD_FUCKING_EXTRACTION_BABY/* usuario@seu-servidor:~/apps/nitroleads/
```

### Opção C: Via FTP/SFTP

Use um cliente FTP como FileZilla ou Cyberduck para fazer upload dos arquivos.

---

## Passo 6: Configurar Ambiente Python

```bash
cd ~/apps/nitroleads

# Criar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install --upgrade pip
pip install -r requirements.txt

# Instalar browsers do Playwright
playwright install chromium
```

---

## Passo 7: Configurar Variáveis de Ambiente

```bash
# Criar arquivo .env
nano .env
```

Cole o conteúdo do seu `.env.production` (criado no Passo 1.1) e salve (Ctrl+X, Y, Enter).

---

## Passo 8: Configurar Banco de Dados

```bash
# Ativar venv (se ainda não estiver ativo)
source venv/bin/activate

# Aplicar migrations
python manage.py migrate

# Criar superusuário (para acessar /admin)
python manage.py createsuperuser
```

---

## Passo 9: Coletar Arquivos Estáticos

```bash
python manage.py collectstatic --noinput
```

---

## Passo 10: Configurar Gunicorn

```bash
# Instalar Gunicorn
pip install gunicorn

# Testar se funciona
gunicorn lead_extraction.wsgi:application --bind 0.0.0.0:8000
```

Se funcionar, pare com Ctrl+C.

---

## Passo 11: Configurar Supervisor

Supervisor vai manter o Gunicorn rodando automaticamente.

```bash
# Criar arquivo de configuração do Supervisor
sudo nano /etc/supervisor/conf.d/nitroleads.conf
```

Cole o seguinte conteúdo:

```ini
[program:nitroleads]
directory=/home/nitroleads/apps/nitroleads
command=/home/nitroleads/apps/nitroleads/venv/bin/gunicorn lead_extraction.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
user=nitroleads
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/home/nitroleads/logs/nitroleads/gunicorn.log
environment=PATH="/home/nitroleads/apps/nitroleads/venv/bin"
```

Salve e execute:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start nitroleads
sudo supervisorctl status nitroleads
```

---

## Passo 12: Configurar Nginx

### 12.1 Criar configuração do Nginx

```bash
sudo nano /etc/nginx/sites-available/nitroleads
```

Cole o seguinte (substitua `seudominio.com` pelo seu domínio):

```nginx
server {
    listen 80;
    server_name seudominio.com www.seudominio.com;

    # Redirecionar HTTP para HTTPS (descomente após configurar SSL)
    # return 301 https://$server_name$request_uri;

    # Para testar antes de configurar SSL, use esta configuração:
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    location /static/ {
        alias /home/nitroleads/apps/nitroleads/staticfiles/;
    }

    location /media/ {
        alias /home/nitroleads/apps/nitroleads/media/;
    }

    client_max_body_size 100M;
}
```

### 12.2 Habilitar site

```bash
sudo ln -s /etc/nginx/sites-available/nitroleads /etc/nginx/sites-enabled/
sudo nginx -t  # Testar configuração
sudo systemctl restart nginx
```

---

## Passo 13: Configurar SSL (HTTPS)

### 13.1 Instalar Certbot

```bash
sudo apt install certbot python3-certbot-nginx -y
```

### 13.2 Obter certificado SSL

```bash
sudo certbot --nginx -d seudominio.com -d www.seudominio.com
```

Siga as instruções. O Certbot vai:
- Obter o certificado SSL
- Configurar o Nginx automaticamente para HTTPS
- Configurar renovação automática

### 13.3 Atualizar Nginx para HTTPS

Depois que o SSL estiver configurado, edite o arquivo novamente:

```bash
sudo nano /etc/nginx/sites-available/nitroleads
```

Descomente a linha de redirecionamento HTTP → HTTPS e ajuste se necessário.

---

## Passo 14: Configurar Tarefas Automáticas (Cronjobs)

### 14. Processadores em Background

#### 14.1 Atualizar tokens do Viper periodicamente

```bash
crontab -e
```

Adicione (atualiza tokens do Viper a cada 6 horas):

```bash
0 */6 * * * cd /home/nitroleads/apps/nitroleads && /home/nitroleads/apps/nitroleads/venv/bin/python auth_bot.py >> /home/nitroleads/logs/nitroleads/auth_bot.log 2>&1
```

---

## Passo 15: Testar o Deploy

1. Acesse `http://seudominio.com` (ou `https://` se configurou SSL)
2. Verifique se a página de login aparece
3. Teste criar uma conta e fazer login
4. Teste fazer uma busca de leads
5. Acesse `/admin/` e faça login com o superusuário criado

---

## Comandos Úteis para Manutenção

### Ver logs do Gunicorn
```bash
sudo supervisorctl tail -f nitroleads
# ou
tail -f /home/nitroleads/logs/nitroleads/gunicorn.log
```

### Reiniciar aplicação
```bash
sudo supervisorctl restart nitroleads
```

### Ver status
```bash
sudo supervisorctl status nitroleads
```

### Atualizar código (se usar Git)
```bash
cd ~/apps/nitroleads
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo supervisorctl restart nitroleads
```

### Ver logs do Django
```bash
tail -f ~/apps/nitroleads/logs/django.log
```

---

## Solução de Problemas

### Erro 502 Bad Gateway
- Verifique se o Gunicorn está rodando: `sudo supervisorctl status nitroleads`
- Verifique os logs: `sudo supervisorctl tail nitroleads`
- Verifique se a porta 8000 está correta no Nginx

### Erro de permissões
```bash
sudo chown -R nitroleads:nitroleads ~/apps/nitroleads
sudo chmod -R 755 ~/apps/nitroleads
```

### Arquivos estáticos não aparecem
```bash
python manage.py collectstatic --noinput
sudo systemctl restart nginx
```

### Erro de conexão com banco
- Verifique se o `DATABASE_URL` está correto no `.env`
- Verifique se o Supabase permite conexões do IP do servidor

---

## Checklist Final

- [ ] Código no servidor
- [ ] Ambiente virtual criado e dependências instaladas
- [ ] Arquivo `.env` configurado
- [ ] Migrations aplicadas
- [ ] Superusuário criado
- [ ] Arquivos estáticos coletados
- [ ] Gunicorn configurado e rodando
- [ ] Supervisor configurado
- [ ] Nginx configurado
- [ ] SSL configurado (HTTPS)
- [ ] Domínio apontando para o servidor
- [ ] Testado funcionamento básico

---

## Próximos Passos

1. Configure backups automáticos do banco de dados
2. Configure monitoramento (opcional)
3. Configure Stripe quando for implementar pagamentos
4. Configure webhooks do Stripe com a URL de produção

---

Boa sorte com o deploy! 🚀



