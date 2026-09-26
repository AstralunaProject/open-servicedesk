import threading
import time

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .. import notifications
from ..bootstrap import seed_catalog
from ..constants import ROLE_ADMIN, ROLE_USER
from ..extensions import db
from ..models import User, utcnow
from ..settings import get_bool, get_setting, set_setting

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 8
_failures_lock = threading.Lock()
_WINDOW = 15 * 60
_MAX_FAILURES = 10


def _client_key(email: str) -> str:
    return f"{request.remote_addr}|{email}"


def _failures() -> dict[str, list[float]]:
    return current_app.extensions.setdefault("login_failures", {})


def _is_blocked(key: str) -> bool:
    now = time.monotonic()
    with _failures_lock:
        failures = _failures()
        attempts = [t for t in failures.get(key, []) if now - t < _WINDOW]
        failures[key] = attempts
        return len(attempts) >= _MAX_FAILURES


def _register_failure(key: str) -> None:
    with _failures_lock:
        _failures().setdefault(key, []).append(time.monotonic())


def _safe_next(target: str | None) -> str | None:
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="redefinir-senha")


def _validate_password(password: str, confirm: str) -> str | None:
    if len(password or "") < MIN_PASSWORD:
        return f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres."
    if password != confirm:
        return "As senhas não conferem."
    return None


def find_user_by_email(email: str):
    return db.session.scalar(
        db.select(User).where(db.func.lower(User.email) == (email or "").strip().lower())
    )


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = _client_key(email)
        if _is_blocked(key):
            flash("Muitas tentativas de login. Aguarde alguns minutos e tente novamente.", "error")
            return render_template("auth/login.html", email=email), 429
        user = find_user_by_email(email)
        if user and user.check_password(password) and user.active:
            session.clear()
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login_at = utcnow()
            db.session.commit()
            return redirect(_safe_next(request.args.get("next")) or url_for("main.index"))
        _register_failure(key)
        flash("E-mail ou senha inválidos.", "error")
        return render_template("auth/login.html", email=email), 401
    return render_template("auth/login.html", email="")


@bp.route("/sair", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/configuracao-inicial", methods=["GET", "POST"])
def setup():
    if db.session.scalar(db.select(db.func.count(User.id))):
        return redirect(url_for("main.index"))
    form = request.form
    if request.method == "POST":
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        company = form.get("company_name", "").strip()
        error = _validate_password(form.get("password", ""), form.get("confirm", ""))
        if not name or "@" not in email:
            error = "Informe seu nome e um e-mail válido."
        if error:
            flash(error, "error")
            return render_template("auth/setup.html", form=form)
        if company:
            set_setting("company_name", company)
        admin = User(name=name, email=email, role=ROLE_ADMIN)
        admin.set_password(form["password"])
        db.session.add(admin)
        db.session.commit()
        seed_catalog()
        from ..models import Group

        for group in db.session.scalars(db.select(Group)):
            group.members.append(admin)
        db.session.commit()
        current_app.extensions["setup_done"] = True
        login_user(admin)
        flash("Tudo pronto! Revise as configurações e cadastre sua equipe.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("auth/setup.html", form=form)


@bp.route("/cadastro", methods=["GET", "POST"])
def register():
    if not get_bool("allow_registration"):
        flash("O autocadastro está desativado. Procure a equipe de T.I.", "info")
        return redirect(url_for("auth.login"))
    form = request.form
    if request.method == "POST":
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        domains = [
            d.strip().lower().lstrip("@") for d in get_setting("registration_domains").split(",") if d.strip()
        ]
        error = _validate_password(form.get("password", ""), form.get("confirm", ""))
        if not name or "@" not in email:
            error = "Informe seu nome e um e-mail válido."
        elif domains and email.split("@")[-1] not in domains:
            error = "Use seu e-mail corporativo (" + ", ".join("@" + d for d in domains) + ")."
        elif find_user_by_email(email):
            error = "Já existe uma conta com este e-mail."
        if error:
            flash(error, "error")
            return render_template("auth/register.html", form=form)
        user = User(
            name=name,
            email=email,
            role=ROLE_USER,
            department=form.get("department", "").strip() or None,
            phone=form.get("phone", "").strip() or None,
        )
        user.set_password(form["password"])
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Conta criada! Você já pode abrir chamados.", "success")
        return redirect(url_for("main.index"))
    return render_template("auth/register.html", form=form)


@bp.route("/perfil", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "GET":
        return render_template("auth/profile.html", new_token=None)
    name = request.form.get("name", "").strip()
    if not name:
        flash("O nome é obrigatório.", "error")
        return redirect(url_for("auth.profile"))
    current_user.name = name
    current_user.phone = request.form.get("phone", "").strip() or None
    current_user.department = request.form.get("department", "").strip() or None
    db.session.commit()
    flash("Perfil atualizado.", "success")
    return redirect(url_for("auth.profile"))


@bp.route("/perfil/senha", methods=["POST"])
@login_required
def change_password():
    if not current_user.check_password(request.form.get("current", "")):
        flash("Senha atual incorreta.", "error")
        return redirect(url_for("auth.profile"))
    error = _validate_password(request.form.get("password", ""), request.form.get("confirm", ""))
    if error:
        flash(error, "error")
        return redirect(url_for("auth.profile"))
    current_user.set_password(request.form["password"])
    db.session.commit()
    flash("Senha alterada.", "success")
    return redirect(url_for("auth.profile"))


@bp.route("/perfil/token", methods=["POST"])
@login_required
def generate_token():
    token = current_user.generate_api_token()
    db.session.commit()
    # O token só existe em claro nesta resposta; no banco fica apenas o hash.
    return render_template("auth/profile.html", new_token=token)


@bp.route("/perfil/token/revogar", methods=["POST"])
@login_required
def revoke_token():
    current_user.api_token_hash = None
    db.session.commit()
    flash("Token de API revogado.", "info")
    return redirect(url_for("auth.profile"))


@bp.route("/esqueci-senha", methods=["GET", "POST"])
def forgot_password():
    email_enabled = notifications.notifications_enabled()
    if request.method == "POST" and email_enabled:
        user = find_user_by_email(request.form.get("email", ""))
        if user and user.active:
            token = _serializer().dumps({"id": user.id, "h": (user.password_hash or "")[-16:]})
            link = f"{notifications.base_url()}{url_for('auth.reset_password', token=token)}"
            notifications.password_reset(user, link)
        flash("Se o e-mail estiver cadastrado, você receberá um link para redefinir a senha.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", email_enabled=email_enabled)


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        data = _serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash("Link inválido ou expirado.", "error")
        return redirect(url_for("auth.forgot_password"))
    user = db.session.get(User, data.get("id"))
    if not user or (user.password_hash or "")[-16:] != data.get("h"):
        flash("Link inválido ou já utilizado.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        error = _validate_password(request.form.get("password", ""), request.form.get("confirm", ""))
        if error:
            flash(error, "error")
        else:
            user.set_password(request.form["password"])
            db.session.commit()
            flash("Senha redefinida. Faça login.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html")
