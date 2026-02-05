# Corrigir Django Admin sem estilos

O admin do Django aparece sem CSS/JS porque os arquivos estáticos não estão sendo carregados. Escolha uma das soluções abaixo.

---

## Solução 1: Deixar o WhiteNoise servir (recomendado)

O WhiteNoise já está configurado no Django. O Nginx não precisa servir `/static/` — basta enviar essas requisições para o Gunicorn e o WhiteNoise atende.

**Edite a configuração do Nginx** (ex.: `/etc/nginx/sites-available/nitroleads`):

1. **Remova ou comente** o bloco `location /static/`:

```nginx
# location /static/ {
#     alias /home/nitroleads/apps/nitroleads/staticfiles/;
# }
```

2. **Garanta que** o `location /` faça proxy para o Gunicorn (incluindo `/static/`):

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_redirect off;
}
```

3. **Recarregue o Nginx**:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## Solução 2: Manter o Nginx servindo `/static/`

Se quiser que o Nginx continue servindo os estáticos:

1. **No servidor, execute**:
```bash
cd /home/nitroleads/apps/nitroleads
source venv/bin/activate
python manage.py collectstatic --noinput
```

2. **Confirme que os arquivos existem**:
```bash
ls -la /home/nitroleads/apps/nitroleads/staticfiles/admin/css/
```
Deve listar arquivos como `base.css` ou `base.xxxxx.css`.

3. **Verifique o Nginx**:
   - Ordem dos blocos: `location /static/` e `location /media/` devem vir **antes** de `location /`
   - Caminho exato do `alias`: deve terminar com `/`
   - Exemplo correto:
   ```nginx
   location /static/ {
       alias /home/nitroleads/apps/nitroleads/staticfiles/;
   }
   ```

4. **Ajuste permissões** se precisar:
```bash
sudo chown -R nitroleads:nitroleads /home/nitroleads/apps/nitroleads/staticfiles
```

---

## Solução 3: Fallback se CompressedManifest causar 404

Se ainda houver 404 após as etapas acima, pode ser o `CompressedManifestStaticFilesStorage`. Dá para testar sem compressão/manifest.

**Em `lead_extraction/settings.py`**, em produção, altere temporariamente:

```python
# De:
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Para (apenas para teste):
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
    # Ou remova a linha para usar o storage padrão
```

Depois rode `collectstatic` de novo e reinicie o Gunicorn.

---

## Checklist rápido

- [ ] `collectstatic` executado no servidor
- [ ] Diretório `staticfiles/` existente e com arquivos
- [ ] Nginx: ou remove `location /static/` (Solução 1), ou configura corretamente (Solução 2)
- [ ] `sudo nginx -t` sem erros
- [ ] `sudo systemctl reload nginx`
- [ ] `sudo supervisorctl restart nitroleads`

---

## Verificar se funcionou

1. Acesse `https://nitroleads.online/admin/`
2. Abra o DevTools (F12) → aba Network
3. Recarregue a página
4. Veja se as requisições para `/static/admin/...` retornam **200** e não **404**
