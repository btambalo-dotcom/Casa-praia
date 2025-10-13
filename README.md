# App de Administração de Aluguel (Casa de Praia) — v3

Novidades desta versão:
- ✅ **Usuários sem e-mail** (login por **username**).
- ✅ **Envio automático de WhatsApp** (WhatsApp Cloud API / Meta). Se não configurar credenciais, o app simula o envio (log/flash).
- ✅ **Relatórios**: ocupação mensal (noites reservadas) e receita mensal.
- ✅ **Modelo de mensagem editável** para WhatsApp com placeholders.

## Configuração .env
Crie `.env` (baseado no `.env.example`):
```
FLASK_DEBUG=1
SECRET_KEY=troque-esta-chave
DATABASE_URL=sqlite:///app.db

# Admin inicial ao rodar init-db
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin

# WhatsApp Cloud API (Meta) - opcional para envio automático
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_API_VERSION=v20.0
```
> Se WHATSAPP_TOKEN/WHATSAPP_PHONE_NUMBER_ID estiverem vazios, o app **não** fará requisições externas e apenas **simulará** o envio (útil para testes).

## Rodando
```
pip install -r requirements.txt
python app.py init-db   # cria o banco, seed do admin e template padrão de WhatsApp
python app.py
# abra http://127.0.0.1:5000  (tela de login - username/senha do .env)
```

## Recursos
- Hóspedes e reservas com busca por **nome** ou **telefone**.
- Calendário (FullCalendar) com status por cor.
- Recibos em PDF por reserva.
- **WhatsApp automático** por reserva (botão “WhatsApp (auto)”).
- **Relatórios** (menu "Relatórios"): ocupação e receita por mês (últimos 12 meses).
- **Modelo de mensagem** (menu "Configurações"): edite texto e use placeholders:
  - `{nome}`, `{telefone}`, `{check_in}`, `{check_out}`, `{status}`, `{valor}`.

## Observação
Para envio programático em produção, configure o **WhatsApp Cloud API** no Meta e preencha `WHATSAPP_TOKEN` e `WHATSAPP_PHONE_NUMBER_ID`.