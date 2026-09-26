import imaplib
import os
import smtplib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from .. import notifications
from ..backup import create_backup, sqlite_path
from ..constants import PRIORITIES, ROLE_ADMIN, ROLES
from ..extensions import db
from ..models import Attachment, Category, Group, SLAPolicy, Ticket, User
from ..settings import DEFAULTS, get_setting, set_setting
from ..utils import admin_required
from .auth import MIN_PASSWORD, find_user_by_email

bp = Blueprint("admin", __name__, url_prefix="/admin")

WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _active_admins() -> int:
    return db.session.scalar(
        db.select(db.func.count(User.id)).where(User.role == ROLE_ADMIN, User.active.is_(True))
    )


@bp.route("/usuarios")
@admin_required
def users():
    query = db.select(User)
    text = (request.args.get("q") or "").strip()
    if text:
        like = f"%{text}%"
        query = query.where(
            db.or_(User.name.ilike(like), User.email.ilike(like), User.department.ilike(like))
        )
    if request.args.get("role") in ROLES:
        query = query.where(User.role == request.args["role"])
    page = db.paginate(
        query.order_by(User.name), page=request.args.get("page", 1, type=int), per_page=30, error_out=False
    )
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template("admin/users.html", page=page, args=args)


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@bp.route("/usuarios/<int:user_id>", methods=["GET", "POST"])
@admin_required
def user_edit(user_id=None):
    user = db.session.get(User, user_id) if user_id else User(role="user", active=True)
    if user is None:
        abort(404)
    groups = db.session.scalars(db.select(Group).order_by(Group.name)).all()
    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        role = form.get("role") if form.get("role") in ROLES else "user"
        active = form.get("active") == "1"
        password = form.get("password", "")
        existing = find_user_by_email(email)
        error = None
        if not name or "@" not in email:
            error = "Nome e e-mail válidos são obrigatórios."
        elif existing and existing.id != user.id:
            error = "Já existe um usuário com este e-mail."
        elif user.id is None and len(password) < MIN_PASSWORD:
            error = f"Defina uma senha inicial com pelo menos {MIN_PASSWORD} caracteres."
        elif password and len(password) < MIN_PASSWORD:
            error = f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres."
        elif (
            user.id
            and user.role == ROLE_ADMIN
            and user.active
            and (role != ROLE_ADMIN or not active)
            and _active_admins() <= 1
        ):
            error = "Não é possível remover o último administrador ativo."
        if error:
            flash(error, "error")
        else:
            user.name = name
            user.email = email
            user.role = role
            user.active = active
            user.department = form.get("department", "").strip() or None
            user.phone = form.get("phone", "").strip() or None
            if password:
                user.set_password(password)
            selected = {int(g) for g in form.getlist("groups") if g.isdigit()}
            user.groups = [g for g in groups if g.id in selected] if user.is_agent else []
            if user.id is None:
                db.session.add(user)
            db.session.commit()
            flash("Usuário salvo.", "success")
            return redirect(url_for("admin.users"))
    tickets_count = 0
    if user.id:
        tickets_count = db.session.scalar(
            db.select(db.func.count(Ticket.id)).where(Ticket.requester_id == user.id)
        )
    return render_template("admin/user_edit.html", user=user, groups=groups, tickets_count=tickets_count)


@bp.route("/grupos")
@admin_required
def groups():
    items = db.session.scalars(db.select(Group).order_by(Group.name)).all()
    counts = dict(
        db.session.execute(
            db.select(Ticket.group_id, db.func.count(Ticket.id))
            .where(Ticket.status.in_(("new", "in_progress", "waiting_user", "waiting_vendor")))
            .group_by(Ticket.group_id)
        ).all()
    )
    return render_template("admin/groups.html", groups=items, counts=counts)


@bp.route("/grupos/novo", methods=["GET", "POST"])
@bp.route("/grupos/<int:group_id>", methods=["GET", "POST"])
@admin_required
def group_edit(group_id=None):
    group = db.session.get(Group, group_id) if group_id else Group(active=True)
    if group is None:
        abort(404)
    agents = db.session.scalars(
        db.select(User).where(User.role.in_(["admin", "agent"])).order_by(User.name)
    ).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        duplicate = db.session.scalar(db.select(Group).where(Group.name == name, Group.id != (group.id or 0)))
        if not name or duplicate:
            flash("Informe um nome único para o grupo.", "error")
        else:
            group.name = name
            group.description = request.form.get("description", "").strip() or None
            group.email = request.form.get("email", "").strip() or None
            group.active = request.form.get("active") == "1"
            selected = {int(u) for u in request.form.getlist("members") if u.isdigit()}
            group.members = [a for a in agents if a.id in selected]
            if group.id is None:
                db.session.add(group)
            db.session.commit()
            flash("Grupo salvo.", "success")
            return redirect(url_for("admin.groups"))
    return render_template("admin/group_edit.html", group=group, agents=agents)


@bp.route("/grupos/<int:group_id>/excluir", methods=["POST"])
@admin_required
def group_delete(group_id):
    group = db.session.get(Group, group_id) or abort(404)
    db.session.execute(db.update(Ticket).where(Ticket.group_id == group.id).values(group_id=None))
    db.session.execute(
        db.update(Category).where(Category.default_group_id == group.id).values(default_group_id=None)
    )
    db.session.delete(group)
    db.session.commit()
    flash("Grupo excluído.", "info")
    return redirect(url_for("admin.groups"))


@bp.route("/categorias", methods=["GET", "POST"])
@admin_required
def categories():
    items = db.session.scalars(db.select(Category).order_by(Category.name)).all()
    groups_list = db.session.scalars(db.select(Group).order_by(Group.name)).all()
    return render_template("admin/categories.html", categories=items, groups=groups_list)


@bp.route("/categorias/salvar", methods=["POST"])
@bp.route("/categorias/<int:category_id>/salvar", methods=["POST"])
@admin_required
def category_save(category_id=None):
    category = db.session.get(Category, category_id) if category_id else Category(active=True)
    if category is None:
        abort(404)
    name = request.form.get("name", "").strip()
    duplicate = db.session.scalar(
        db.select(Category).where(Category.name == name, Category.id != (category.id or 0))
    )
    if not name or duplicate:
        flash("Informe um nome único para a categoria.", "error")
        return redirect(url_for("admin.categories"))
    category.name = name
    category.description = request.form.get("description", "").strip()[:255] or None
    category.default_group_id = request.form.get("default_group_id", type=int) or None
    category.active = request.form.get("active") == "1"
    if category.id is None:
        db.session.add(category)
    db.session.commit()
    flash("Categoria salva.", "success")
    return redirect(url_for("admin.categories"))


@bp.route("/categorias/<int:category_id>/excluir", methods=["POST"])
@admin_required
def category_delete(category_id):
    category = db.session.get(Category, category_id) or abort(404)
    db.session.execute(db.update(Ticket).where(Ticket.category_id == category.id).values(category_id=None))
    from ..models import KBArticle

    db.session.execute(
        db.update(KBArticle).where(KBArticle.category_id == category.id).values(category_id=None)
    )
    db.session.delete(category)
    db.session.commit()
    flash("Categoria excluída.", "info")
    return redirect(url_for("admin.categories"))


def _hours_to_minutes(value, default):
    try:
        minutes = round(float(str(value).replace(",", ".")) * 60)
    except (TypeError, ValueError):
        return default
    return max(1, minutes)


@bp.route("/sla", methods=["GET", "POST"])
@admin_required
def sla():
    policies = {p.priority: p for p in db.session.scalars(db.select(SLAPolicy))}
    if request.method == "POST":
        for priority in PRIORITIES:
            policy = policies.get(priority) or SLAPolicy(
                priority=priority, response_minutes=60, resolution_minutes=480
            )
            policy.response_minutes = _hours_to_minutes(
                request.form.get(f"response_{priority}"), policy.response_minutes
            )
            policy.resolution_minutes = _hours_to_minutes(
                request.form.get(f"resolution_{priority}"), policy.resolution_minutes
            )
            db.session.add(policy)
        set_setting("business_hours_enabled", "1" if request.form.get("business_hours_enabled") else "0")
        set_setting(
            "business_days", ",".join(d for d in request.form.getlist("business_days") if d.isdigit())
        )
        for key in ("business_start", "business_end"):
            value = request.form.get(key, "")
            if len(value) == 5 and value[2] == ":":
                set_setting(key, value)
        db.session.commit()
        flash("SLA atualizado. Os novos prazos valem para chamados abertos a partir de agora.", "success")
        return redirect(url_for("admin.sla"))
    days = {int(d) for d in get_setting("business_days").split(",") if d.strip().isdigit()}
    return render_template("admin/sla.html", policies=policies, weekdays=WEEKDAYS, days=days)


GENERAL_KEYS = (
    "company_name",
    "app_title",
    "ticket_prefix",
    "timezone",
    "registration_domains",
    "reopen_days",
    "auto_close_days",
)
GENERAL_FLAGS = ("allow_registration", "requester_can_set_priority")
SMTP_KEYS = ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_from")
IMAP_KEYS = ("imap_host", "imap_port", "imap_user", "imap_folder", "imap_interval")


@bp.route("/configuracoes", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        section = request.form.get("section")
        if section == "general":
            prefix = "".join(ch for ch in request.form.get("ticket_prefix", "").upper() if ch.isalnum())[:6]
            for key in GENERAL_KEYS:
                value = request.form.get(key, "").strip()
                if key == "ticket_prefix":
                    value = prefix or DEFAULTS[key]
                if key in ("reopen_days", "auto_close_days") and not value.isdigit():
                    value = DEFAULTS[key]
                if key == "timezone":
                    try:
                        ZoneInfo(value)
                    except (ZoneInfoNotFoundError, ValueError):
                        flash("Fuso horário inválido; mantido o anterior.", "error")
                        continue
                set_setting(key, value)
            for key in GENERAL_FLAGS:
                set_setting(key, "1" if request.form.get(key) else "0")
        elif section == "smtp":
            for key in SMTP_KEYS:
                set_setting(key, request.form.get(key, "").strip())
            set_setting("notify_enabled", "1" if request.form.get("notify_enabled") else "0")
            if request.form.get("smtp_password"):
                set_setting("smtp_password", request.form["smtp_password"])
        elif section == "imap":
            for key in IMAP_KEYS:
                set_setting(key, request.form.get(key, "").strip())
            for key in ("imap_enabled", "imap_create_users"):
                set_setting(key, "1" if request.form.get(key) else "0")
            if request.form.get("imap_password"):
                set_setting("imap_password", request.form["imap_password"])
        db.session.commit()
        flash("Configurações salvas.", "success")
        return redirect(url_for("admin.settings", _anchor=section or ""))
    return render_template("admin/settings.html")


@bp.route("/configuracoes/testar-email", methods=["POST"])
@admin_required
def test_email():
    cfg = notifications.smtp_config()
    if not cfg["host"]:
        flash("Configure o servidor SMTP primeiro.", "error")
        return redirect(url_for("admin.settings", _anchor="smtp"))
    msg = notifications.build_message(
        cfg,
        [current_user.email],
        "Teste de e-mail — T.I Chamados",
        "Se você recebeu esta mensagem, o envio de e-mails está funcionando.",
    )
    try:
        notifications.deliver(cfg, msg)
    except (smtplib.SMTPException, OSError) as exc:
        flash(f"Falha ao enviar: {exc}", "error")
    else:
        flash(f"E-mail de teste enviado para {current_user.email}.", "success")
    return redirect(url_for("admin.settings", _anchor="smtp"))


@bp.route("/configuracoes/testar-imap", methods=["POST"])
@admin_required
def test_imap():
    host = get_setting("imap_host").strip()
    if not host:
        flash("Configure o servidor IMAP primeiro.", "error")
        return redirect(url_for("admin.settings", _anchor="imap"))
    port = int(get_setting("imap_port") or 993)
    try:
        conn = (
            imaplib.IMAP4_SSL(host, port, timeout=15)
            if port == 993
            else imaplib.IMAP4(host, port, timeout=15)
        )
        conn.login(get_setting("imap_user"), get_setting("imap_password"))
        status, _ = conn.select(get_setting("imap_folder") or "INBOX", readonly=True)
        conn.logout()
        if status != "OK":
            raise RuntimeError("pasta não encontrada")
    except (imaplib.IMAP4.error, OSError, RuntimeError) as exc:
        flash(f"Falha na conexão IMAP: {exc}", "error")
    else:
        flash("Conexão IMAP funcionando.", "success")
    return redirect(url_for("admin.settings", _anchor="imap"))


@bp.route("/sistema")
@admin_required
def system():
    path = sqlite_path()
    info = {
        "database": current_app.config["SQLALCHEMY_DATABASE_URI"].split("@")[-1],
        "db_size": os.path.getsize(path) if path and os.path.exists(path) else None,
        "attachments": db.session.scalar(db.select(db.func.count(Attachment.id))),
        "attachments_size": db.session.scalar(db.select(db.func.coalesce(db.func.sum(Attachment.size), 0))),
        "tickets": db.session.scalar(db.select(db.func.count(Ticket.id))),
        "users": db.session.scalar(db.select(db.func.count(User.id))),
        "data_dir": current_app.config["DATA_DIR"],
        "sqlite": path is not None,
    }
    return render_template("admin/system.html", info=info)


@bp.route("/sistema/backup", methods=["POST"])
@admin_required
def backup():
    try:
        path = create_backup()
    except RuntimeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.system"))
    return send_file(
        path, as_attachment=True, download_name=os.path.basename(path), mimetype="application/zip"
    )
