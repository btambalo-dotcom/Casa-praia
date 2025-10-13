import os
import csv
import sys
import io
import re
import math
from datetime import datetime, date, timedelta
from collections import defaultdict, OrderedDict

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_, func
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
import requests

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///app.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

db = SQLAlchemy(app)

# ---------- AUTH MODELS ----------
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

# ---------- SETTINGS MODEL ----------
class Setting(db.Model):
    __tablename__ = "settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        s = Setting.query.filter_by(key=key).first()
        return s.value if s else default

    @staticmethod
    def set(key, value):
        s = Setting.query.filter_by(key=key).first()
        if not s:
            s = Setting(key=key, value=value)
            db.session.add(s)
        else:
            s.value = value
        db.session.commit()

# ---------- DOMAIN MODELS ----------
class Guest(db.Model):
    __tablename__ = "guests"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(50), nullable=True, index=True)
    email = db.Column(db.String(120), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bookings = db.relationship("Booking", backref="guest", lazy=True, cascade="all, delete-orphan")

class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    guest_id = db.Column(db.Integer, db.ForeignKey("guests.id"), nullable=False, index=True)
    check_in = db.Column(db.Date, nullable=False, index=True)
    check_out = db.Column(db.Date, nullable=False, index=True)
    price_total = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pendente")  # pendente|confirmada|cancelada
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def nights(self):
        return max(0, (self.check_out - self.check_in).days)

    def as_event(self):
        color = {"confirmada": None, "pendente": None, "cancelada": "#999999"}.get(self.status, None)
        exclusive_end = self.check_out
        return {
            "id": self.id,
            "title": f"{self.guest.name} ({self.status})",
            "start": self.check_in.isoformat(),
            "end": exclusive_end.isoformat(),
            "url": url_for("edit_booking", booking_id=self.id),
            **({"color": color} if color else {}),
        }

# ---------- LOGIN MANAGER ----------
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Flask-Login props
User.is_authenticated = property(lambda self: True)
User.is_active = property(lambda self: True)
User.is_anonymous = property(lambda self: False)
User.get_id = lambda self: str(self.id)

# ---------- UTILS ----------
def seed_admin_and_defaults():
    # user admin
    username = os.getenv("ADMIN_USERNAME", "admin")
    pwd = os.getenv("ADMIN_PASSWORD", "admin")
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username, name="Admin", is_admin=True)
        user.set_password(pwd)
        db.session.add(user)
        db.session.commit()
        print(f"Usuário admin criado: {username} / {pwd}")
    else:
        print("Admin já existe.")

    # default WhatsApp message template
    default_tpl = ("Olá {nome}! Aqui é da Casa de Praia. "
                   "Sua reserva de {check_in} a {check_out} está {status}. "
                   "Valor total: {valor}. Qualquer dúvida, estamos à disposição.")
    if Setting.get("wa_message_template") is None:
        Setting.set("wa_message_template", default_tpl)
        print("Template WhatsApp padrão criado.")

def init_db():
    db.create_all()
    seed_admin_and_defaults()
    print("Banco inicializado.")

def sanitize_phone_for_wa(phone: str):
    if not phone:
        return ""
    phone = phone.strip()
    if phone.startswith("+"):
        cleaned = "+" + re.sub(r"\D", "", phone[1:])
    else:
        cleaned = re.sub(r"\D", "", phone)
    return cleaned

def format_currency_br(amount):
    if amount is None:
        return "-"
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_date_br(d: date):
    return d.strftime("%d/%m/%Y")

def render_wa_message(booking: Booking):
    tpl = Setting.get("wa_message_template") or ""
    return tpl.format(
        nome=booking.guest.name,
        telefone=booking.guest.phone or "-",
        check_in=format_date_br(booking.check_in),
        check_out=format_date_br(booking.check_out),
        status=booking.status,
        valor=format_currency_br(booking.price_total),
    )

def send_whatsapp_cloud_api(to_e164: str, text: str):
    token = os.getenv("WHATSAPP_TOKEN", "").strip()
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    api_version = os.getenv("WHATSAPP_API_VERSION", "v20.0").strip()

    if not token or not phone_id:
        # Simulacao de envio (sem credenciais)
        app.logger.info(f"[SIMULADO] Enviaria WhatsApp para {to_e164}: {text}")
        return {"simulado": True, "to": to_e164, "text": text}

    url = f"https://graph.facebook.com/{api_version}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}
    if resp.status_code >= 200 and resp.status_code < 300:
        return {"ok": True, "response": data}
    return {"ok": False, "response": data, "status_code": resp.status_code}

# ---------- ROUTES ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Bem-vindo!", "success")
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        flash("Credenciais inválidas.", "error")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu da sessão.", "success")
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template("index.html")

# Guests
@app.route("/guests")
@login_required
def guests_list():
    q = request.args.get("q", "").strip()
    query = Guest.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Guest.name.ilike(like), Guest.phone.ilike(like)))
    guests = query.order_by(Guest.created_at.desc()).limit(200).all()
    return render_template("guests_list.html", guests=guests, q=q)

@app.route("/guests/new", methods=["GET", "POST"])
@login_required
def new_guest():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        note = request.form.get("note", "").strip()
        if not name:
            flash("Nome é obrigatório.", "error")
            return redirect(url_for("new_guest"))
        g = Guest(name=name, phone=phone, email=email, note=note)
        db.session.add(g)
        db.session.commit()
        flash("Hóspede cadastrado com sucesso!", "success")
        return redirect(url_for("guests_list"))
    return render_template("guest_form.html", guest=None)

@app.route("/guests/<int:guest_id>/edit", methods=["GET", "POST"])
@login_required
def edit_guest(guest_id):
    guest = Guest.query.get_or_404(guest_id)
    if request.method == "POST":
        guest.name = request.form.get("name", "").strip()
        guest.phone = request.form.get("phone", "").strip()
        guest.email = request.form.get("email", "").strip()
        guest.note = request.form.get("note", "").strip()
        if not guest.name:
            flash("Nome é obrigatório.", "error")
            return redirect(url_for("edit_guest", guest_id=guest.id))
        db.session.commit()
        flash("Hóspede atualizado!", "success")
        return redirect(url_for("guests_list"))
    return render_template("guest_form.html", guest=guest)

@app.route("/guests/<int:guest_id>/delete", methods=["POST"])
@login_required
def delete_guest(guest_id):
    guest = Guest.query.get_or_404(guest_id)
    db.session.delete(guest)
    db.session.commit()
    flash("Hóspede removido.", "success")
    return redirect(url_for("guests_list"))

@app.route("/guests/export.csv")
@login_required
def export_guests():
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "name", "phone", "email", "note", "created_at"])
    for g in Guest.query.order_by(Guest.id.asc()).all():
        writer.writerow([g.id, g.name, g.phone or "", g.email or "", g.note or "", g.created_at.isoformat()])
    mem = io.BytesIO(si.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="guests.csv")

# Bookings
@app.route("/bookings")
@login_required
def bookings_list():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    query = Booking.query.join(Guest)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Guest.name.ilike(like), Guest.phone.ilike(like)))
    if status:
        query = query.filter(Booking.status == status)
    bookings = query.order_by(Booking.check_in.desc()).limit(500).all()
    return render_template("bookings_list.html", bookings=bookings, q=q, status=status, format_currency_br=format_currency_br)

@app.route("/bookings/new", methods=["GET", "POST"])
@login_required
def new_booking():
    guests = Guest.query.order_by(Guest.name.asc()).all()
    if request.method == "POST":
        guest_id = int(request.form.get("guest_id"))
        check_in = request.form.get("check_in")
        check_out = request.form.get("check_out")
        status = request.form.get("status") or "pendente"
        price_total = request.form.get("price_total")
        note = request.form.get("note", "").strip()
        if not (guest_id and check_in and check_out):
            flash("Hóspede, check-in e check-out são obrigatórios.", "error")
            return redirect(url_for("new_booking"))
        b = Booking(
            guest_id=guest_id,
            check_in=datetime.strptime(check_in, "%Y-%m-%d").date(),
            check_out=datetime.strptime(check_out, "%Y-%m-%d").date(),
            status=status,
            price_total=float(price_total) if price_total else None,
            note=note,
        )
        db.session.add(b)
        db.session.commit()
        flash("Reserva criada!", "success")
        return redirect(url_for("bookings_list"))
    return render_template("booking_form.html", booking=None, guests=guests)

@app.route("/bookings/<int:booking_id>/edit", methods=["GET", "POST"])
@login_required
def edit_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    guests = Guest.query.order_by(Guest.name.asc()).all()
    if request.method == "POST":
        booking.guest_id = int(request.form.get("guest_id"))
        booking.check_in = datetime.strptime(request.form.get("check_in"), "%Y-%m-%d").date()
        booking.check_out = datetime.strptime(request.form.get("check_out"), "%Y-%m-%d").date()
        booking.status = request.form.get("status") or "pendente"
        price_total = request.form.get("price_total")
        booking.price_total = float(price_total) if price_total else None
        booking.note = request.form.get("note", "").strip()
        db.session.commit()
        flash("Reserva atualizada!", "success")
        return redirect(url_for("bookings_list"))
    return render_template("booking_form.html", booking=booking, guests=guests)

@app.route("/bookings/<int:booking_id>/delete", methods=["POST"])
@login_required
def delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    db.session.delete(booking)
    db.session.commit()
    flash("Reserva removida.", "success")
    return redirect(url_for("bookings_list"))

# Receipt PDF
@app.route("/bookings/<int:booking_id>/receipt.pdf")
@login_required
def booking_receipt(booking_id):
    b = Booking.query.get_or_404(booking_id)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    def draw_label_value(y, label, value):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2*cm, y, label)
        c.setFont("Helvetica", 11)
        c.drawString(6*cm, y, value)

    c.setTitle("Recibo de Reserva")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, height - 2*cm, "Recibo de Reserva")
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, height - 2.6*cm, f"Emitido em: {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}")

    y = height - 4*cm
    draw_label_value(y, "Hóspede:", b.guest.name); y -= 1.0*cm
    draw_label_value(y, "Telefone:", b.guest.phone or "-"); y -= 1.0*cm
    draw_label_value(y, "E-mail:", b.guest.email or "-"); y -= 1.0*cm
    draw_label_value(y, "Período:", f"{b.check_in.strftime('%d/%m/%Y')} a {b.check_out.strftime('%d/%m/%Y')}"); y -= 1.0*cm
    draw_label_value(y, "Status:", b.status.capitalize()); y -= 1.0*cm
    draw_label_value(y, "Valor total:", format_currency_br(b.price_total)); y -= 1.2*cm

    c.setFont("Helvetica", 10)
    c.drawString(2*cm, y, "Observações:")
    text_object = c.beginText(2*cm, y - 0.6*cm)
    text_object.setFont("Helvetica", 10)
    note = b.note or "-"
    import textwrap as tw
    for line in tw.wrap(note, width=90):
        text_object.textLine(line)
    c.drawText(text_object)

    c.showPage()
    c.save()
    buffer.seek(0)
    filename = f"recibo_reserva_{b.id}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)

# WhatsApp auto send
@app.route("/bookings/<int:booking_id>/whatsapp/send", methods=["POST"])
@login_required
def booking_whatsapp_send(booking_id):
    b = Booking.query.get_or_404(booking_id)
    to_raw = b.guest.phone or ""
    to = sanitize_phone_for_wa(to_raw)
    if not to or (not to.startswith("+") and not to.startswith("+"[:1])):
        flash("Telefone do hóspede deve incluir DDI (ex: +55...).", "error")
        return redirect(url_for("bookings_list"))
    text = render_wa_message(b)
    result = send_whatsapp_cloud_api(to, text)
    if result.get("ok") or result.get("simulado"):
        flash("Mensagem enviada (ou simulada) com sucesso.", "success")
    else:
        flash(f"Falha ao enviar WhatsApp: {result}", "error")
    return redirect(url_for("bookings_list"))

# Reports
def months_back(n=12, from_date=None):
    if from_date is None:
        from_date = date.today().replace(day=1)
    months = []
    y, m = from_date.year, from_date.month
    for i in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(months))

def month_date_range(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year+1, 1, 1)
    else:
        end = date(year, month+1, 1)
    return start, end

@app.route("/reports")
@login_required
def reports():
    # Últimos 12 meses
    ym_list = months_back(12)
    revenue = OrderedDict()
    occupancy_nights = OrderedDict()

    for (y, m) in ym_list:
        start, end = month_date_range(y, m)
        # Receita: soma de price_total de reservas que intersectam o mês (aproximação simples: soma total se intersecta)
        q = Booking.query.filter(Booking.check_in < end, Booking.check_out > start)
        total = 0.0
        nights = 0
        for b in q.all():
            total += (b.price_total or 0.0)
            # Ocupação: conta noites dentro do intervalo do mês
            seg_start = max(b.check_in, start)
            seg_end = min(b.check_out, end)
            n = max(0, (seg_end - seg_start).days)
            nights += n
        revenue[(y, m)] = total
        occupancy_nights[(y, m)] = nights

    # Capacidade (noites possíveis por mês) = dias do mês
    capacity = OrderedDict()
    for (y, m) in ym_list:
        start, end = month_date_range(y, m)
        capacity[(y, m)] = (end - start).days

    return render_template("reports.html",
                           ym_list=ym_list,
                           revenue=revenue,
                           occupancy_nights=occupancy_nights,
                           capacity=capacity)

# Settings - WhatsApp message template
@app.route("/settings/whatsapp-template", methods=["GET", "POST"])
@login_required
def settings_whatsapp_template():
    current_tpl = Setting.get("wa_message_template") or ""
    if request.method == "POST":
        tpl = request.form.get("template", "").strip()
        if not tpl:
            flash("O template não pode ficar vazio.", "error")
        else:
            Setting.set("wa_message_template", tpl)
            flash("Template atualizado!", "success")
        return redirect(url_for("settings_whatsapp_template"))
    return render_template("settings_whatsapp_template.html", template=current_tpl)

# Calendar view and API
@app.route("/calendar")
@login_required
def calendar_view():
    return render_template("calendar.html")

@app.route("/api/events")
@login_required
def api_events():
    start = request.args.get("start")
    end = request.args.get("end")
    query = Booking.query
    if start and end:
        start_d = datetime.fromisoformat(start.replace("Z","")).date()
        end_d = datetime.fromisoformat(end.replace("Z","")).date()
        query = query.filter(
            and_(
                Booking.check_in < end_d,
                Booking.check_out > start_d,
            )
        )
    events = [b.as_event() for b in query.all()]
    for e in events:
        if "pendente" in e["title"] and "color" not in e:
            e["color"] = "#f6c453"
        if "confirmada" in e["title"] and "color" not in e:
            e["color"] = "#3a87ad"
    return jsonify(events)

# Healthcheck
@app.route("/healthz")
def healthz():
    return {"ok": True}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init-db":
        with app.app_context():
            db.create_all()
            init_db()
    else:
        app.run(debug=True)