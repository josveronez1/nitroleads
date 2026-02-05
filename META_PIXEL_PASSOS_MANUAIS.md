# Meta Pixel – O que fazer manualmente

A implementação do Meta Pixel já está no código. Siga estes passos no **servidor** e na **LP**.

---

## 1. Variáveis de ambiente no servidor

No servidor (onde a aplicação roda), garanta que o `.env` (ou o sistema que você usa para env vars) tenha:

```bash
META_PIXEL_ID=768323565823880
```

O **Token de Acesso** não vai no frontend. Guarde-o só se for usar Conversions API no backend no futuro (por exemplo em `META_PIXEL_ACCESS_TOKEN`). Para PageView, Lead, CompleteRegistration e InitiateCheckout, só o ID acima é necessário.

---

## 2. Rebuild da Landing Page (LP)

O evento **Lead** no botão "QUERO ME LIBERTAR AGORA" foi adicionado no código React da LP. Para que isso suba para produção:

```bash
cd lp/Landing-Page---NitroLeads
npm install
npm run build
```

Isso gera/atualiza o `dist/` que o Django serve em `/lp`. Faça o deploy desse build (ou rode o build no servidor se a LP for construída lá).

---

## 3. Nginx (CSP para o Meta Pixel)

O **Django** já envia o CSP com os domínios do Facebook. Se no servidor o **Nginx** também definir `Content-Security-Policy`, ele precisa liberar o Meta Pixel, senão o browser pode bloquear o script.

### Opção A – Usar o script (recomendado)

No servidor, com o projeto atualizado (incluindo o `ATUALIZAR_NGINX_CSP.sh`):

```bash
sudo ./ATUALIZAR_NGINX_CSP.sh
```

O script faz backup, coloca a CSP com `https://connect.facebook.net` (script-src) e `https://www.facebook.com` / `https://connect.facebook.net` (connect-src), testa e pergunta se quer recarregar o nginx.

### Opção B – Só Django com CSP

Se você **remover** a linha `add_header Content-Security-Policy ...` do Nginx e deixar só o Django definir o CSP, não precisa alterar o Nginx: o middleware já inclui os domínios do Facebook.

---

## 4. Recarregar a aplicação

Depois de definir `META_PIXEL_ID` e (se usar) atualizar o Nginx:

- Recarregar o Nginx (se usou o script ou editou à mão):  
  `sudo systemctl reload nginx`
- Reiniciar o app Django (gunicorn/uWSGI/systemd, etc.), para carregar o novo `.env` e o código do pixel.

---

## Resumo rápido

| O quê | Onde | Comando / ação |
|-------|------|-----------------|
| Pixel ID | Servidor | `META_PIXEL_ID=768323565823880` no `.env` (ou env vars do processo) |
| LP com evento Lead | Build da LP | `cd lp/Landing-Page---NitroLeads && npm run build` e deploy do `dist/` |
| CSP no Nginx | Servidor | `sudo ./ATUALIZAR_NGINX_CSP.sh` (ou remover CSP do Nginx) |
| Aplicar mudanças | Servidor | `sudo systemctl reload nginx` (se alterou Nginx) + reiniciar app Django |

---

## Eventos implementados

| Evento | Onde | Gatilho |
|--------|------|--------|
| **PageView** | LP e plataforma | Carregamento da página (snippet do pixel) |
| **Lead** | LP | Clique em "QUERO ME LIBERTAR AGORA" |
| **CompleteRegistration** | Plataforma | Sucesso no cadastro ("Criar Conta") |
| **InitiateCheckout** | Plataforma | Clique em "Comprar Agora" ou "Comprar Valor Personalizado" |

Token de acesso: use apenas no backend (ex.: Conversions API); não é necessário para esses eventos no frontend.
