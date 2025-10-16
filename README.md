# Casa de Praia — v5.1.1 (Render-ready)
- Correção de sintaxe dos decorators (@app.route / @login_required)
- Contrato com {pix_chave}, {wifi_nome}, {wifi_senha}, {portaria_senha}
- Banco persistente automático se existir /var/data (Render Disk)
- Comandos:
    python app.py init-db   # cria tabelas e usuário
    python app.py           # roda local