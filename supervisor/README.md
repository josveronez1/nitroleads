# Configuração do Supervisor para NitroLeads

Este diretório contém os arquivos de configuração do Supervisor prontos para uso.

## Arquivos

- `nitroleads.conf` - Configuração do Gunicorn (servidor web)
- `nitroleads-queue.conf` - Configuração do processador de fila do Viper

## Instalação no Servidor

### 1. Copiar arquivos para o Supervisor

```bash
# No servidor VPS
sudo cp /home/nitroleads/apps/nitroleads/supervisor/*.conf /etc/supervisor/conf.d/
```

### 2. Criar diretórios de logs (se não existirem)

```bash
mkdir -p /home/nitroleads/logs/nitroleads
chown nitroleads:nitroleads /home/nitroleads/logs/nitroleads
```

### 3. Recarregar Supervisor

```bash
sudo supervisorctl reread
sudo supervisorctl update
```

### 4. Verificar status

```bash
sudo supervisorctl status
```

Deve mostrar:
```
nitroleads                       RUNNING   pid 12345, uptime 0:01:00
nitroleads-queue                 RUNNING   pid 12346, uptime 0:01:00
```

## Dependências do Sistema para Playwright

O `nitroleads-queue` usa Playwright para autenticação no Viper. Execute no servidor:

```bash
# Instalar dependências do Playwright
sudo apt-get update
sudo apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2

# Instalar browsers do Playwright
su - nitroleads
cd ~/apps/nitroleads
source venv/bin/activate
python -m playwright install chromium
```

## Comandos Úteis

```bash
# Ver status
sudo supervisorctl status

# Reiniciar todos
sudo supervisorctl restart all

# Reiniciar apenas a fila
sudo supervisorctl restart nitroleads-queue

# Ver logs em tempo real
sudo supervisorctl tail -f nitroleads-queue

# Ver logs do Gunicorn
sudo supervisorctl tail -f nitroleads

# Parar tudo
sudo supervisorctl stop all

# Iniciar tudo
sudo supervisorctl start all
```

## Troubleshooting

### Erro: "libatk-1.0.so.0: cannot open shared object file"

1. Verifique se as dependências do sistema estão instaladas (seção acima)
2. Verifique se `LD_LIBRARY_PATH` está configurado no arquivo `.conf`
3. Reinicie o supervisor: `sudo supervisorctl restart nitroleads-queue`

### Erro: "No module named 'playwright'"

```bash
su - nitroleads
cd ~/apps/nitroleads
source venv/bin/activate
pip install playwright
python -m playwright install chromium
```

### Erro: "viper_tokens.json não encontrado"

Execute manualmente o auth_bot para gerar os tokens iniciais:

```bash
su - nitroleads
cd ~/apps/nitroleads
source venv/bin/activate
python auth_bot.py
```

### Verificar se tokens estão sendo gerados

```bash
cat /home/nitroleads/apps/nitroleads/viper_tokens.json
```

Deve mostrar algo como:
```json
{
  "Authorization": "Bearer eyJ...",
  "Cookie": "...",
  "User-Agent": "...",
  "captured_at": "2026-01-08 10:00:00"
}
```

