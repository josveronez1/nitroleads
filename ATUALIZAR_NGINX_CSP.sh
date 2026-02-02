#!/bin/bash
# Script para atualizar CSP no nginx
# Execute este script no servidor para aplicar as correções de CSP
# IMPORTANTE: Execute com sudo: sudo ./ATUALIZAR_NGINX_CSP.sh

echo "=== Atualizando CSP no Nginx ==="
echo "NOTA: Este script precisa ser executado com sudo para editar o nginx"

# Caminho do arquivo de configuração do nginx (ajuste se necessário)
NGINX_CONFIG="/etc/nginx/sites-available/nitroleads"
NGINX_CONFIG_ALT="/etc/nginx/conf.d/nitroleads.conf"

# Verificar qual arquivo existe
if [ -f "$NGINX_CONFIG" ]; then
    CONFIG_FILE="$NGINX_CONFIG"
elif [ -f "$NGINX_CONFIG_ALT" ]; then
    CONFIG_FILE="$NGINX_CONFIG_ALT"
else
    echo "ERRO: Arquivo de configuração do nginx não encontrado!"
    echo "Procure por arquivos em:"
    echo "  - /etc/nginx/sites-available/"
    echo "  - /etc/nginx/conf.d/"
    exit 1
fi

echo "Arquivo encontrado: $CONFIG_FILE"

# Verificar se está rodando com sudo
if [ "$EUID" -ne 0 ]; then 
    echo "ERRO: Este script precisa ser executado com sudo!"
    echo "Execute: sudo ./ATUALIZAR_NGINX_CSP.sh"
    exit 1
fi

# Fazer backup
BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP_FILE"
echo "Backup criado: $BACKUP_FILE"

# Nova linha CSP com cdn.jsdelivr.net, Mercado Pago SDK e domínios mlstatic/mercadolibre (Checkout Bricks)
NEW_CSP='add_header Content-Security-Policy "default-src '\''self'\''; script-src '\''self'\'' '\''unsafe-inline'\'' '\''unsafe-eval'\'' https://js.stripe.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://sdk.mercadopago.com https://http2.mlstatic.com https://cdn.tailwindcss.com https://esm.sh; style-src '\''self'\'' '\''unsafe-inline'\'' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; font-src '\''self'\'' https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com data:; img-src '\''self'\'' data: https:; connect-src '\''self'\'' https: wss:; frame-src https://js.stripe.com https://hooks.stripe.com https://www.mercadopago.com.br https://www.mercadolibre.com https://secure-fields.mercadopago.com; object-src '\''none'\''; base-uri '\''self'\''; form-action '\''self'\'';" always;'

# Remover TODAS as linhas CSP antigas (pode haver múltiplas)
sed -i '/add_header Content-Security-Policy/d' "$CONFIG_FILE"

# Adicionar nova linha CSP (antes da linha "Ocultar versão do Nginx" ou no final)
if grep -q "server_tokens off" "$CONFIG_FILE"; then
    sed -i "/server_tokens off/i\\$NEW_CSP" "$CONFIG_FILE"
else
    echo "" >> "$CONFIG_FILE"
    echo "$NEW_CSP" >> "$CONFIG_FILE"
fi

echo "CSP atualizado no arquivo de configuração"

# Testar configuração do nginx
echo ""
echo "Testando configuração do nginx..."
if sudo nginx -t; then
    echo ""
    echo "✓ Configuração válida!"
    echo ""
    read -p "Deseja recarregar o nginx agora? (s/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        sudo systemctl reload nginx
        echo "✓ Nginx recarregado com sucesso!"
    else
        echo "Execute manualmente: sudo systemctl reload nginx"
    fi
else
    echo ""
    echo "✗ ERRO na configuração do nginx!"
    echo "Revertendo alterações..."
    cp "$BACKUP_FILE" "$CONFIG_FILE"
    echo "Configuração restaurada do backup"
    exit 1
fi

echo ""
echo "=== Concluído ==="
echo "CSP atualizado para incluir cdn.jsdelivr.net e Mercado Pago SDK"

