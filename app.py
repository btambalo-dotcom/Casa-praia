
import os, io, csv, re
from datetime import datetime, date
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

load_dotenv()

def get_database_url():
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    if os.path.isdir("/var/data"):
        return "sqlite:////var/data/app.db"
    if os.getenv("RENDER", "false").lower() == "true" or os.getenv("RENDER_EXTERNAL_URL"):
        return "sqlite:////tmp/app.db"
    return "sqlite:///app.db"

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = get_database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120))
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)
    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    is_authenticated = True
    is_active = True
    is_anonymous = False
    def get_id(self): return str(self.id)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, index=True, nullable=False)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        s = Setting.query.filter_by(key=key).first()
        return s.value if s else default
    @staticmethod
    def set(key, value):
        s = Setting.query.filter_by(key=key).first()
        if not s: s = Setting(key=key, value=value); db.session.add(s)
        else: s.value = value
        db.session.commit()

class Guest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(50), index=True)
    email = db.Column(db.String(120))
    note = db.Column(db.Text)
    cpf = db.Column(db.String(20), index=True)
    rg = db.Column(db.String(30))
    address = db.Column(db.String(255))
    companions = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    bookings = db.relationship("Booking", backref="guest", lazy=True, cascade="all, delete-orphan")

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guest_id = db.Column(db.Integer, db.ForeignKey("guest.id"), nullable=False, index=True)
    check_in = db.Column(db.Date, nullable=False, index=True)
    check_out = db.Column(db.Date, nullable=False, index=True)
    price_total = db.Column(db.Float)
    status = db.Column(db.String(20), default="pendente")
    payment_method = db.Column(db.String(30))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

login_manager = LoginManager(app)
login_manager.login_view = "login"
@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

def seed_admin_and_defaults():
    username = os.getenv("ADMIN_USERNAME", "admin")
    pwd = os.getenv("ADMIN_PASSWORD", "admin")
    if not User.query.filter_by(username=username).first():
        u = User(username=username, name="Admin", is_admin=True); u.set_password(pwd)
        db.session.add(u); db.session.commit()
        print(f"Admin criado: {username}/{pwd}")
    if Setting.get("wa_message_template") is None:
        Setting.set("wa_message_template","Olá {nome}! Sua reserva de {check_in} a {check_out} está {status}. Valor: {valor}.")
    if Setting.get("contract_template") is None:
        Setting.set("contract_template",
            "CONTRATO DE LOCAÇÃO\n\n"
            "LOCADOR: {locador_nome}\n"
            "LOCATÁRIO: {nome} (CPF {cpf}, RG {rg})\n"
            "Endereço do locatário: {endereco}\n"
            "Acompanhantes: {acompanhantes}\n\n"
            "Imóvel: {imovel}\n"
            "Período: {check_in} a {check_out}\n"
            "Valor: {valor}\n"
            "Forma de pagamento: {forma_pagamento}\n"
            "Chave PIX: {pix_chave}\n"
            "Wi‑Fi: {wifi_nome} / Senha: {wifi_senha}\n"
            "Senha de portaria: {portaria_senha}\n\n"
            "Assinaturas:\n"
            "LOCADOR: ____________________\n"
            "LOCATÁRIO: ____________________"
        )

def init_db():
    db.create_all(); seed_admin_and_defaults()
    print("DB pronto em:", app.config["SQLALCHEMY_DATABASE_URI"])

def sanitize_phone_for_wa(phone:str):
    if not phone: return ""
    phone = phone.strip()
    if phone.startswith("+"): return "+" + re.sub(r"\D","", phone[1:])
    return re.sub(r"\D","", phone)

def br_date(d:date): return d.strftime("%d/%m/%Y")
def br_currency(v): 
    if v is None: return "-"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def render_contract_text(b):
    g = b.guest
    tpl = Setting.get("contract_template") or ""
    acomp = (g.companions or "").strip().replace("\r\n","\n").replace("\r","\n")
    acomp_line = ", ".join([s.strip() for s in acomp.split("\n") if s.strip()]) or "-"
    return tpl.format(
        locador_nome=os.getenv("LOCADOR_NOME", "Divalcir Tambalo"),
        nome=g.name, cpf=g.cpf or "-", rg=g.rg or "-", endereco=g.address or "-",
        acompanhantes=acomp_line,
        imovel=os.getenv("IMOVEL_DESC","Casa de Praia — Bertioga"),
        check_in=br_date(b.check_in), check_out=br_date(b.check_out),
        valor=br_currency(b.price_total),
        forma_pagamento=(b.payment_method or "-").capitalize(),
        pix_chave=os.getenv("PIX_CHAVE","-"),
        wifi_nome=os.getenv("WIFI_NOME","-"),
        wifi_senha=os.getenv("WIFI_SENHA","-"),
        portaria_senha=os.getenv("PORTARIA_SENHA","-"),
    )

def send_whatsapp(to_e164, text):
    token = os.getenv("WHATSAPP_TOKEN","").strip()
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID","").strip()
    api_version = os.getenv("WHATSAPP_API_VERSION","v20.0").strip()
    if not token or not phone_id:
        app.logger.info(f"[SIMULADO] WhatsApp para {to_e164}: {text}")
        return {"simulado": True}
    url = f"https://graph.facebook.com/{api_version}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product":"whatsapp","to":to_e164,"type":"text","text":{"preview_url":False,"body":text}}
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    return {"ok": 200 <= r.status_code < 300, "status": r.status_code, "resp": r.text}

from flask_login import login_required

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = User.query.filter_by(username=request.form.get("username","").strip()).first()
        if u and u.check_password(request.form.get("password","")):
            login_user(u); flash("Bem-vindo!", "success"); return redirect(url_for("index"))
        flash("Credenciais inválidas.", "error")
    return render_template("login.html")

@app.route("/logout"); @login_required
def logout():
    logout_user(); flash("Você saiu.", "success"); return redirect(url_for("login"))

@app.route("/"); @login_required
def index(): return render_template("index.html")

@app.route("/guests"); @login_required
def guests_list():
    q = request.args.get("q","").strip()
    query = Guest.query
    if q:
        like = f"%{q}%"; query = query.filter(or_(Guest.name.ilike(like), Guest.phone.ilike(like), Guest.cpf.ilike(like)))
    guests = query.order_by(Guest.created_at.desc()).limit(300).all()
    return render_template("guests_list.html", guests=guests, q=q)

@app.route("/guests/new", methods=["GET","POST"]); @login_required
def new_guest():
    if request.method=="POST":
        g = Guest(
            name=request.form.get("name","").strip(),
            phone=request.form.get("phone","").strip(),
            email=request.form.get("email","").strip(),
            note=request.form.get("note","").strip(),
            cpf=request.form.get("cpf","").strip(),
            rg=request.form.get("rg","").strip(),
            address=request.form.get("address","").strip(),
            companions=request.form.get("companions","").strip(),
        )
        if not g.name: flash("Nome é obrigatório.", "error"); return redirect(url_for("new_guest"))
        db.session.add(g); db.session.commit(); flash("Hóspede cadastrado!", "success")
        return redirect(url_for("guests_list"))
    return render_template("guest_form.html", guest=None)

@app.route("/guests/<int:guest_id>/edit", methods=["GET","POST"]); @login_required
def edit_guest(guest_id):
    g = Guest.query.get_or_404(guest_id)
    if request.method=="POST":
        g.name=request.form.get("name","").strip()
        g.phone=request.form.get("phone","").strip()
        g.email=request.form.get("email","").strip()
        g.note=request.form.get("note","").strip()
        g.cpf=request.form.get("cpf","").strip()
        g.rg=request.form.get("rg","").strip()
        g.address=request.form.get("address","").strip()
        g.companions=request.form.get("companions","").strip()
        if not g.name: flash("Nome é obrigatório.", "error"); return redirect(url_for("edit_guest", guest_id=g.id))
        db.session.commit(); flash("Hóspede atualizado!", "success")
        return redirect(url_for("guests_list"))
    return render_template("guest_form.html", guest=g)

@app.route("/bookings"); @login_required
def bookings_list():
    q = request.args.get("q","").strip(); status = request.args.get("status","").strip()
    query = Booking.query.join(Guest)
    if q:
        like = f"%{q}%"; query = query.filter(or_(Guest.name.ilike(like), Guest.phone.ilike(like), Guest.cpf.ilike(like)))
    if status: query = query.filter(Booking.status==status)
    bookings = query.order_by(Booking.check_in.desc()).limit(500).all()
    return render_template("bookings_list.html", bookings=bookings, q=q, status=status, br_currency=br_currency)

@app.route("/bookings/new", methods=["GET","POST"]); @login_required
def new_booking():
    guests = Guest.query.order_by(Guest.name.asc()).all()
    if request.method=="POST":
        b = Booking(
            guest_id=int(request.form.get("guest_id")),
            check_in=datetime.strptime(request.form.get("check_in"), "%Y-%m-%d").date(),
            check_out=datetime.strptime(request.form.get("check_out"), "%Y-%m-%d").date(),
            status=request.form.get("status") or "pendente",
            price_total=float(request.form.get("price_total")) if request.form.get("price_total") else None,
            payment_method=request.form.get("payment_method","").strip(),
            note=request.form.get("note","").strip(),
        )
        db.session.add(b); db.session.commit(); flash("Reserva criada!", "success")
        return redirect(url_for("bookings_list"))
    return render_template("booking_form.html", booking=None, guests=guests)

@app.route("/bookings/<int:booking_id>/edit", methods=["GET","POST"]); @login_required
def edit_booking(booking_id):
    b = Booking.query.get_or_404(booking_id); guests = Guest.query.order_by(Guest.name.asc()).all()
    if request.method=="POST":
        b.guest_id=int(request.form.get("guest_id"))
        b.check_in=datetime.strptime(request.form.get("check_in"), "%Y-%m-%d").date()
        b.check_out=datetime.strptime(request.form.get("check_out"), "%Y-%m-%d").date()
        b.status=request.form.get("status") or "pendente"
        b.price_total=float(request.form.get("price_total")) if request.form.get("price_total") else None
        b.payment_method=request.form.get("payment_method","").strip()
        b.note=request.form.get("note","").strip()
        db.session.commit(); flash("Reserva atualizada!", "success")
        return redirect(url_for("bookings_list"))
    return render_template("booking_form.html", booking=b, guests=guests)

@app.route("/guests/export.csv"); @login_required
def export_guests():
    si = io.StringIO(); w = csv.writer(si)
    w.writerow(["id","name","phone","email","cpf","rg","address","companions","note","created_at"])
    for g in Guest.query.order_by(Guest.id.asc()).all():
        w.writerow([g.id,g.name,g.phone or "",g.email or "",g.cpf or "",g.rg or "",g.address or "",(g.companions or "").replace("\n"," | "),g.note or "",g.created_at.isoformat()])
    mem = io.BytesIO(si.getvalue().encode("utf-8-sig")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="guests.csv")

@app.route("/bookings/export.csv"); @login_required
def export_bookings():
    si = io.StringIO(); w = csv.writer(si)
    w.writerow(["id","guest_name","guest_cpf","check_in","check_out","status","payment_method","price_total","note","created_at"])
    for b in Booking.query.order_by(Booking.id.asc()).all():
        w.writerow([b.id,b.guest.name,b.guest.cpf or "",b.check_in.isoformat(),b.check_out.isoformat(),b.status,b.payment_method or "",f"{b.price_total:.2f}" if b.price_total is not None else "",b.note or "",b.created_at.isoformat()])
    mem = io.BytesIO(si.getvalue().encode("utf-8-sig")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="bookings.csv")

@app.route("/bookings/<int:booking_id>/receipt.pdf"); @login_required
def booking_receipt(booking_id):
    b = Booking.query.get_or_404(booking_id)
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); w,h=A4
    def row(y,l,v): c.setFont("Helvetica-Bold",10); c.drawString(2*cm,y,l); c.setFont("Helvetica",10); c.drawString(6*cm,y,v)
    c.setTitle("Recibo de Reserva"); c.setFont("Helvetica-Bold",16); c.drawString(2*cm,h-2*cm,"Recibo de Reserva")
    y=h-3.2*cm; row(y,"Hóspede:", b.guest.name); y-=0.8*cm
    row(y,"CPF:", b.guest.cpf or "-"); y-=0.8*cm
    row(y,"Telefone:", b.guest.phone or "-"); y-=0.8*cm
    row(y,"Período:", f"{br_date(b.check_in)} a {br_date(b.check_out)}"); y-=0.8*cm
    row(y,"Status:", b.status.capitalize()); y-=0.8*cm
    row(y,"Forma de pagamento:", (b.payment_method or "-").capitalize()); y-=0.8*cm
    row(y,"Valor:", br_currency(b.price_total)); y-=1.0*cm
    c.setFont("Helvetica",10); c.drawString(2*cm,y,"Observações:"); y-=0.6*cm
    from textwrap import wrap
    t=c.beginText(2*cm,y); t.setFont("Helvetica",10)
    for line in wrap(b.note or "-", 90): t.textLine(line)
    c.drawText(t); c.showPage(); c.save(); buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"recibo_reserva_{b.id}.pdf")

@app.route("/bookings/<int:booking_id>/contract.pdf"); @login_required
def booking_contract(booking_id):
    b = Booking.query.get_or_404(booking_id)
    text = render_contract_text(b)
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); w,h=A4
    c.setTitle("Contrato de Locação"); c.setFont("Helvetica-Bold",14); c.drawString(2*cm,h-2*cm,"Contrato de Locação")
    y = h-3*cm; c.setFont("Helvetica",10)
    for para in text.split("\n"):
        from textwrap import wrap
        lines = wrap(para, 95) or [""]
        for ln in lines:
            if y < 2*cm: c.showPage(); y=h-2*cm; c.setFont("Helvetica",10)
            c.drawString(2*cm,y,ln); y -= 0.5*cm
        y -= 0.2*cm
    c.showPage(); c.save(); buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"contrato_reserva_{b.id}.pdf")

@app.route("/settings/contract-template", methods=["GET","POST"]); @login_required
def settings_contract_template():
    curr = Setting.get("contract_template") or ""
    if request.method=="POST":
        tpl = request.form.get("template","").strip()
        if not tpl: flash("Template não pode ficar vazio.", "error")
        else: Setting.set("contract_template", tpl); flash("Template do contrato atualizado!", "success")
        return redirect(url_for("settings_contract_template"))
    return render_template("settings_contract_template.html", template=curr)

@app.route("/bookings/<int:booking_id>/whatsapp/send", methods=["POST"]); @login_required
def booking_whatsapp_send(booking_id):
    b = Booking.query.get_or_404(booking_id)
    to = sanitize_phone_for_wa(b.guest.phone or "")
    if not to or not to.startswith("+"): flash("Telefone precisa do DDI (ex: +55...)", "error"); return redirect(url_for("bookings_list"))
    msg = Setting.get("wa_message_template") or ""
    msg = msg.format(nome=b.guest.name, check_in=br_date(b.check_in), check_out=br_date(b.check_out), status=b.status, valor=br_currency(b.price_total))
    res = send_whatsapp(to, msg)
    flash("Mensagem enviada (ou simulada)." if res.get("simulado") or res.get("ok") else "Falha ao enviar.", "success" if (res.get("simulado") or res.get("ok")) else "error")
    return redirect(url_for("bookings_list"))

@app.route("/api/events"); @login_required
def api_events():
    start = request.args.get("start"); end = request.args.get("end")
    q = Booking.query
    if start and end:
        s = datetime.fromisoformat(start.replace("Z","")).date()
        e = datetime.fromisoformat(end.replace("Z","")).date()
        q = q.filter(Booking.check_in < e, Booking.check_out > s)
    events = []
    for b in q.all():
        color = {"confirmada":"#3a87ad","pendente":"#f6c453","cancelada":"#999999"}.get(b.status)
        events.append({"id":b.id,"title":f"{b.guest.name} ({b.status})","start":b.check_in.isoformat(),"end":b.check_out.isoformat(),"url":url_for("edit_booking", booking_id=b.id),"color":color})
    return jsonify(events)

@app.route("/calendar"); @login_required
def calendar_view(): return render_template("calendar.html")

@app.route("/healthz")
def healthz(): return {"ok":True}

if __name__ == "__main__":
    import sys
    if len(sys.argv)>1 and sys.argv[1]=="init-db":
        with app.app_context():
            db.create_all(); seed_admin_and_defaults()
            print("Inicializado em", app.config["SQLALCHEMY_DATABASE_URI"])
    else:
        app.run(debug=True)
