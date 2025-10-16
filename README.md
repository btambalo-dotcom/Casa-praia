# App de Administração de Aluguel (Casa de Praia) — v4.1 (Render-ready)

Pronto para o Render com:
- **Gunicorn** (Procfile incluso)
- **SQLite automático**: local = `sqlite:///app.db`; Render = `sqlite:////tmp/app.db`
- Todas as features: login, recibos PDF, WhatsApp automático (Cloud API/simulado), relatórios, template

## Variáveis (.env)
SECRET_KEY=troque-esta-chave
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_API_VERSION=v20.0

## Rodar local
pip install -r requirements.txt
python app.py init-db
python app.py

## Render
- Novo Web Service → Python
- Start command: **deixe vazio** (o Render usa o Procfile) ou `gunicorn app:app`
- Adicione as variáveis .env acima (Settings → Environment)
- Deploy