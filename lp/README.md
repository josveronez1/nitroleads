# Landing Page NitroLeads

Landing page desenvolvida no Google AI Studio. Servida em **nitroleads.online/lp**.

## Build

Antes de fazer deploy, execute o build:

```bash
./build.sh
```

Ou manualmente:

```bash
cd lp/Landing-Page---NitroLeads
npm install
npm run build
```

Os arquivos gerados ficam em `lp/Landing-Page---NitroLeads/dist/`.

## Deploy

No servidor, rode o build da LP antes de reiniciar a aplicação (ou inclua no script de deploy):

```bash
cd ~/apps/nitroleads/lp
./build.sh
```

Depois reinicie o Gunicorn/Django para servir a nova versão.
