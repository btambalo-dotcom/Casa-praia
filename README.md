# App de Administração de Aluguel (Casa de Praia) — v4

🚀 **Otimizado para Render (SQLite automático)**

## Novidades
- Detecta automaticamente o ambiente **Render** e salva o banco em `/tmp/app.db` (gravável no Render).  
- Mantém compatibilidade local com `sqlite:///app.db`.  
- Se quiser usar PostgreSQL, basta trocar `DATABASE_URL` no `.env`.  
- Mantém todos os recursos da v3:
  - Login por usuário (sem e-mail)
  - Recibos PDF
  - WhatsApp automático (Cloud API / simulado)
  - Relatórios e template de mensagem

## Como rodar localmente
```bash
pip install -r requirements.txt
python app.py init-db
python app.py
```
Acesse em: http://127.0.0.1:5000

## Como usar no Render
1. Faça deploy no Render.  
2. Não é preciso mudar nada — o app usará `/tmp/app.db` automaticamente.  
3. (Opcional) Use PostgreSQL preenchendo no `.env`:
   ```
   DATABASE_URL=postgresql://user:senha@host:porta/db
   ```

## Variáveis de ambiente (.env)
```
SECRET_KEY=troque-esta-chave
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_API_VERSION=v20.0
```