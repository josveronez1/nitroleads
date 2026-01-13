# Instruções para Corrigir CSP no Nginx

## Problema
O nginx está adicionando um CSP que não inclui `cdn.jsdelivr.net`, causando erros no console.

## Solução Rápida (Recomendada)

Execute no servidor com **sudo**:

```bash
sudo ./ATUALIZAR_NGINX_CSP.sh
```

## Solução Manual

Se o script não funcionar, edite manualmente o arquivo do nginx:

1. **Localizar o arquivo de configuração:**
   ```bash
   sudo find /etc/nginx -name "*nitroleads*" -type f
   ```
   
   Geralmente está em:
   - `/etc/nginx/sites-available/nitroleads`
   - `/etc/nginx/conf.d/nitroleads.conf`

2. **Fazer backup:**
   ```bash
   sudo cp /etc/nginx/sites-available/nitroleads /etc/nginx/sites-available/nitroleads.backup
   ```

3. **Editar o arquivo:**
   ```bash
   sudo nano /etc/nginx/sites-available/nitroleads
   ```

4. **Localizar a linha com `add_header Content-Security-Policy`** e substituir por:

   ```nginx
   add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://js.stripe.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com data:; img-src 'self' data: https:; connect-src 'self' https://api.stripe.com https://*.supabase.co https://cdn.jsdelivr.net; frame-src https://js.stripe.com https://hooks.stripe.com; object-src 'none'; base-uri 'self'; form-action 'self';" always;
   ```

   **IMPORTANTE:** A parte importante é adicionar `https://cdn.jsdelivr.net` na diretiva `connect-src`.

5. **Testar configuração:**
   ```bash
   sudo nginx -t
   ```

6. **Recarregar nginx:**
   ```bash
   sudo systemctl reload nginx
   ```

## Alternativa: Remover CSP do Nginx

Se preferir, você pode **remover completamente** a linha do CSP do nginx e deixar apenas o Django gerenciar:

1. Edite o arquivo do nginx
2. Comente ou remova a linha: `add_header Content-Security-Policy ...`
3. Recarregue o nginx

O middleware Django já está configurado para adicionar o CSP correto.

## Verificar se Funcionou

Após aplicar as mudanças:

1. Limpe o cache do navegador (Ctrl+Shift+R ou Cmd+Shift+R)
2. Abra o console do navegador (F12)
3. Verifique se os erros de CSP desapareceram
4. Verifique os headers da resposta:
   - Abra DevTools > Network
   - Recarregue a página
   - Clique em qualquer requisição
   - Vá em "Headers" > "Response Headers"
   - Procure por "Content-Security-Policy"
   - Deve incluir `https://cdn.jsdelivr.net` em `connect-src`

## Troubleshooting

**Se ainda aparecer erro:**
1. Verifique se o nginx foi recarregado: `sudo systemctl status nginx`
2. Verifique se há múltiplas linhas CSP no arquivo (deve ter apenas uma)
3. Verifique se o Django está rodando com as mudanças mais recentes
4. Limpe o cache do navegador completamente


