"""
QR Code Based Attendance System — Flask application entrypoint.

Run locally:
  pip install -r requirements.txt
  copy .env.example to .env and edit SECRET_KEY
  flask --app app init-db
  flask --app app create-admin --email you@example.com --password yourpass --name "Your Name"
  flask --app app run --debug

Deploy: gunicorn app:app (see Procfile and README).
"""
from __future__ import annotations

import csv
import io
import os
import secrets
from datetime import datetime
from functools import wraps

import click
import qrcode
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import Attendance, LectureSession, User, db

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)


# --- Ensure SQLite directory exists -------------------------------------------------
_instance = os.path.join(app.instance_path)
os.makedirs(_instance, exist_ok=True)


db.init_app(app)


@app.context_processor
def inject_current_user():
    """Expose current_user() as `user` in all templates (None if logged out)."""
    return {"user": current_user()}


def _refresh_csrf() -> None:
    """Simple CSRF token stored in server session (for form + fetch POSTs)."""
    session["csrf_token"] = secrets.token_hex(16)


def _validate_csrf() -> bool:
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    return bool(sent and sent == session.get("csrf_token"))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        uid = session.get("user_id")
        if not uid:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        uid = session.get("user_id")
        if not uid:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        user = db.session.get(User, uid)
        if not user or user.role != "admin":
            flash("Admin access only.", "danger")
            return redirect(url_for("student_dashboard"))
        return fn(*args, **kwargs)

    return wrapper


def current_user() -> User | None:
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(User, uid)


def build_qr_payload(session_id: str) -> str:
    """
    Payload format: session_id|unix_timestamp_utc
    The timestamp is when the QR was generated; scan must occur within QR_VALIDITY_SECONDS.
    """
    ts = int(datetime.utcnow().timestamp())
    return f"{session_id}|{ts}"


def parse_qr_payload(raw: str) -> tuple[str, int] | None:
    """Return (session_id, ts) or None if malformed."""
    if not raw or "|" not in raw:
        return None
    parts = raw.strip().split("|", 1)
    if len(parts) != 2:
        return None
    sid, ts_s = parts[0].strip(), parts[1].strip()
    if not sid:
        return None
    try:
        ts = int(ts_s)
    except ValueError:
        return None
    return sid, ts


def validate_qr_scan(session_id: str, embedded_ts: int) -> tuple[bool, str]:
    """
    Verify session exists, timestamp is recent, return (ok, message).
    """
    lec = db.session.get(LectureSession, session_id)
    if not lec:
        return False, "Invalid QR: session not found."

    now_ts = int(datetime.utcnow().timestamp())
    skew = abs(now_ts - embedded_ts)
    max_age = app.config.get("QR_VALIDITY_SECONDS", 300)
    if skew > max_age:
        return False, f"This QR has expired (valid for {max_age // 60} minutes). Ask your instructor for a new code."

    return True, "OK"


@app.cli.command("init-db")
def init_db_command():
    """Create database tables (SQLite file or PostgreSQL)."""
    with app.app_context():
        db.create_all()
    print("Database initialized.")


@app.cli.command("create-admin")
@click.option("--email", required=True, help="Admin login email")
@click.option("--password", required=True, help="Admin password (min 6 characters recommended)")
@click.option("--name", default="Administrator", show_default=True, help="Display name")
def create_admin_command(email: str, password: str, name: str):
    """Create an admin user (use when ADMIN_REGISTRATION_SECRET is not set)."""
    email = email.strip().lower()
    if User.query.filter_by(email=email).first():
        print("User with that email already exists.")
        return
    u = User(
        name=name.strip(),
        email=email,
        password_hash=generate_password_hash(password),
        role="admin",
    )
    db.session.add(u)
    db.session.commit()
    print(f"Admin created: {email}")


# --- Routes: auth -------------------------------------------------------------------


@app.route("/")
def index():
    u = current_user()
    if not u:
        return redirect(url_for("login"))
    if u.role == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("student_dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        if not _validate_csrf():
            flash("Invalid security token. Refresh the page and try again.", "danger")
            return redirect(url_for("login"))
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))
        session.permanent = True
        session["user_id"] = user.id
        _refresh_csrf()
        flash(f"Welcome back, {user.name}!", "success")
        nxt = request.args.get("next") or url_for("index")
        return redirect(nxt)

    if "csrf_token" not in session:
        session.permanent = True
        _refresh_csrf()
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        if not _validate_csrf():
            flash("Invalid security token. Refresh the page and try again.", "danger")
            return redirect(url_for("register"))
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        admin_secret = (request.form.get("admin_secret") or "").strip()

        if not name or not email or len(password) < 6:
            flash("Name and email are required; password must be at least 6 characters.", "danger")
            return redirect(url_for("register"))
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))
        if User.query.filter_by(email=email).first():
            flash("That email is already registered.", "danger")
            return redirect(url_for("register"))

        role = "student"
        cfg_secret = app.config.get("ADMIN_REGISTRATION_SECRET")
        if cfg_secret and admin_secret == cfg_secret:
            role = "admin"

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
        )
        db.session.add(user)
        db.session.commit()
        session.permanent = True
        session["user_id"] = user.id
        _refresh_csrf()
        flash("Registration successful.", "success")
        return redirect(url_for("index"))

    if "csrf_token" not in session:
        session.permanent = True
        _refresh_csrf()
    return render_template("register.html", admin_secret_enabled=bool(app.config.get("ADMIN_REGISTRATION_SECRET")))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# --- Admin --------------------------------------------------------------------------


@app.route("/admin")
@admin_required
def admin_dashboard():
    u = current_user()
    sessions = (
        LectureSession.query.filter_by(admin_id=u.id).order_by(LectureSession.created_at.desc()).all()
    )
    return render_template("admin/dashboard.html", user=u, sessions=sessions, qr_ttl_sec=app.config["QR_VALIDITY_SECONDS"])


@app.route("/admin/session/create", methods=["POST"])
@admin_required
def admin_create_session():
    if not _validate_csrf():
        flash("Invalid security token.", "danger")
        return redirect(url_for("admin_dashboard"))
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Session title is required.", "danger")
        return redirect(url_for("admin_dashboard"))
    u = current_user()
    lec = LectureSession(title=title, admin_id=u.id)
    db.session.add(lec)
    db.session.commit()
    flash("Session created. Share the live QR with students.", "success")
    return redirect(url_for("admin_session_qr", session_id=lec.id))


@app.route("/admin/session/<session_id>")
@admin_required
def admin_session_qr(session_id):
    """Show large QR with auto-refresh (new timestamp periodically)."""
    u = current_user()
    lec = db.session.get(LectureSession, session_id)
    if not lec or lec.admin_id != u.id:
        flash("Session not found.", "danger")
        return redirect(url_for("admin_dashboard"))
    return render_template(
        "admin/session_qr.html",
        user=u,
        lecture=lec,
        qr_ttl_sec=app.config["QR_VALIDITY_SECONDS"],
        refresh_interval_ms=min(120_000, app.config["QR_VALIDITY_SECONDS"] * 500),
    )


@app.route("/admin/session/<session_id>/qr.png")
@admin_required
def admin_session_qr_image(session_id):
    """PNG QR for current payload (session_id|timestamp)."""
    u = current_user()
    lec = db.session.get(LectureSession, session_id)
    if not lec or lec.admin_id != u.id:
        return ("Not found", 404)
    payload = build_qr_payload(lec.id)
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    # Short cache — browser should still refresh via query string on the page
    return send_file(buf, mimetype="image/png", max_age=0)


@app.route("/admin/attendance")
@admin_required
def admin_attendance():
    u = current_user()
    my_sessions = {s.id for s in LectureSession.query.filter_by(admin_id=u.id).all()}
    rows = (
        db.session.query(Attendance, User, LectureSession)
        .join(User, Attendance.user_id == User.id)
        .join(LectureSession, Attendance.session_id == LectureSession.id)
        .filter(LectureSession.admin_id == u.id)
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .all()
    )
    return render_template("admin/attendance.html", user=u, rows=rows)


@app.route("/admin/export.csv")
@admin_required
def admin_export_csv():
    u = current_user()
    rows = (
        db.session.query(Attendance, User, LectureSession)
        .join(User, Attendance.user_id == User.id)
        .join(LectureSession, Attendance.session_id == LectureSession.id)
        .filter(LectureSession.admin_id == u.id)
        .order_by(LectureSession.title, Attendance.date, Attendance.time)
        .all()
    )
    si = io.StringIO()
    w = csv.writer(si)
    w.writerow(["session_title", "session_id", "student_name", "student_email", "date", "time"])
    for att, student, lec in rows:
        w.writerow(
            [
                lec.title,
                lec.id,
                student.name,
                student.email,
                att.date.isoformat(),
                att.time.strftime("%H:%M:%S"),
            ]
        )
    mem = io.BytesIO(si.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"attendance_export_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv",
    )


# --- Student ------------------------------------------------------------------------


@app.route("/student")
@login_required
def student_dashboard():
    u = current_user()
    if u.role == "admin":
        return redirect(url_for("admin_dashboard"))
    history = (
        db.session.query(Attendance, LectureSession)
        .join(LectureSession, Attendance.session_id == LectureSession.id)
        .filter(Attendance.user_id == u.id)
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .all()
    )
    return render_template(
        "student/dashboard.html",
        user=u,
        history=history,
        qr_ttl_sec=app.config["QR_VALIDITY_SECONDS"],
    )


@app.route("/student/mark", methods=["POST"])
@login_required
def student_mark():
    """JSON body: { "qr_text": "session_id|ts" } — used by html5-qrcode fetch."""
    u = current_user()
    if u.role == "admin":
        return jsonify({"ok": False, "message": "Admins use the dashboard; student account required."}), 403
    if not _validate_csrf():
        return jsonify({"ok": False, "message": "Invalid security token. Refresh the page."}), 403

    data = request.get_json(silent=True) or {}
    raw = (data.get("qr_text") or data.get("qr_data") or "").strip()
    parsed = parse_qr_payload(raw)
    if not parsed:
        return jsonify({"ok": False, "message": "Invalid QR: could not read session data."}), 400

    session_id, embedded_ts = parsed
    ok, msg = validate_qr_scan(session_id, embedded_ts)
    if not ok:
        return jsonify({"ok": False, "message": msg}), 400

    lec = db.session.get(LectureSession, session_id)
    existing = Attendance.query.filter_by(user_id=u.id, session_id=session_id).first()
    if existing:
        return jsonify({"ok": False, "message": "You have already marked attendance for this session."}), 409

    now = datetime.utcnow()
    row = Attendance(user_id=u.id, session_id=session_id, date=now.date(), time=now.time().replace(microsecond=0))
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "You have already marked attendance for this session."}), 409

    return jsonify({"ok": True, "message": f"Attendance recorded for “{lec.title}”.", "session_title": lec.title})


# --- Error handlers (friendly messages) ---------------------------------------------


@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500


# --- App factory hook for first request (optional) ----------------------------------

with app.app_context():
    db.create_all()
