#!/bin/bash
# Corrige o Django Admin sem estilos.
# O WhiteNoise deve servir /static/. Remova ou comente o location /static/ do Nginx.
#
# Execute no servidor com: sudo ./CORRIGIR_NGINX_STATIC.sh

echo "=== Corrigir Django Admin (arquivos estáticos) ==="

for candidate in /etc/nginx/sites-available/nitroleads /etc/nginx/conf.d/nitroleads.conf; do
    [ -f "$candidate" ] && NGINX_CONFIG="$candidate" && break
done

if [ -z "$NGINX_CONFIG" ]; then
    echo "Nginx config não encontrado. Procure em /etc/nginx/sites-available/"
    exit 1
fi

echo "Config: $NGINX_CONFIG"
[ "$EUID" -ne 0 ] && echo "Execute com sudo!" && exit 1

# Backup
cp "$NGINX_CONFIG" "${NGINX_CONFIG}.bak.$(date +%Y%m%d)"
echo "Backup criado."

# Comentar as linhas do bloco location /static/
sed -i.bak '/location \/static\//,/}/{
    s/^/#/
}' "$NGINX_CONFIG" 2>/dev/null || true

echo ""
echo "1. Edite o arquivo: sudo nano $NGINX_CONFIG"
echo "2. Comente ou remova o bloco:"
echo "   location /static/ {"
echo "       alias /home/nitroleads/apps/nitroleads/staticfiles/;"
echo "   }"
echo ""
echo "3. Rode: sudo nginx -t && sudo systemctl reload nginx"
echo "4. Rode no app: python manage.py collectstatic --noinput"
echo "5. Reinicie: sudo supervisorctl restart nitroleads"
