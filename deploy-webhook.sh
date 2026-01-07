#!/bin/bash

# Script de Deploy via Webhook do GitHub
# Este script é executado quando o GitHub envia um webhook após push na branch main

cd /home/nitroleads/apps/nitroleads || exit 1
source venv/bin/activate

# Pull das mudanças
git pull origin main

# Aplicar migrações
python manage.py migrate --noinput

# Coletar arquivos estáticos
python manage.py collectstatic --noinput

# Reiniciar serviços
sudo supervisorctl restart nitroleads
sudo supervisorctl restart nitroleads-queue

# Log
mkdir -p ~/logs/nitroleads
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Deploy via webhook concluído" >> ~/logs/nitroleads/deploy.log

