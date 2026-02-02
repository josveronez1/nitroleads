#!/bin/bash
# Build da landing page para servir em /lp
set -e
cd "$(dirname "$0")/Landing-Page---NitroLeads"
echo "[LP] Instalando dependências..."
npm install
echo "[LP] Gerando build..."
npm run build
echo "[LP] Build concluído. Arquivos em lp/Landing-Page---NitroLeads/dist/"
echo "[LP] A LP estará disponível em /lp"
