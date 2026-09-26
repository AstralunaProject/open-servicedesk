import csv
import io
import os

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from .. import services
from ..constants import (
    CHANNELS,
    OPEN_STATUSES,
    ROLE_ADMIN,
    ROLE_AGENT,
    STATUS_CLOSED,
    STATUS_RESOLVED,
    STATUSES,
)
from ..extensions import db
from ..models import Asset, Attachment, Category, Group, Ticket, User, utcnow
from ..settings import get_bool
from ..ticket_query import AGENT_VIEWS, USER_VIEWS, filtered_query
from ..utils import agent_required, fmt_datetime

bp = Blueprint("tickets", __name__, url_prefix="/chamados")


def _get_ticket_or_404(ticket_id) -> Ticket:
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        abort(404)
    if not services.can_view(current_user, ticket):
        abort(403)
    return ticket


def _agents():
    return db.session.scalars(
        db.select(User)
        .where(User.role.in_([ROLE_ADMIN, ROLE_AGENT]), User.active.is_(True))
        .order_by(User.name)
    ).all()


def _form_options():
    return {
        "categories": db.session.scalars(
            db.select(Category).where(Category.active.is_(True)).order_by(Category.name)
        ).all(),
        "groups": db.session.scalars(
            db.select(Group).where(Group.active.is_(True)).order_by(Group.name)
        ).all(),
        "agents": _agents(),
    }


@bp.route("/")
@login_required
def list_tickets():
    query, view, sort = filtered_query(request.args, current_user)
    page = db.paginate(query, page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template(
        "tickets/list.html",
        page=page,
        view=view,
        sort=sort,
        views=AGENT_VIEWS if current_user.is_agent else USER_VIEWS,
        args=args,
        now=utcnow(),
        **_form_options(),
    )


@bp.route("/exportar.csv")
@agent_required
def export_csv():
    query, _, _ = filtered_query(request.args, current_user)
    buffer = io.StringIO()
    buffer.write("﻿")  # BOM para o Excel reconhecer UTF-8
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "Número",
            "Tipo",
            "Título",
            "Status",
            "Prioridade",
            "Categoria",
            "Grupo",
            "Responsável",
            "Solicitante",
            "E-mail",
            "Departamento",
            "Canal",
            "Aberto em",
            "Primeira resposta",
            "Resolvido em",
            "Prazo de solução",
            "SLA",
            "Avaliação",
        ]
    )
    sla_labels = {
        "met": "Cumprido",
        "breached": "Violado",
        "ok": "No prazo",
        "warning": "Em risco",
        "paused": "Pausado",
    }
    for t in db.session.scalars(query):
        writer.writerow(
            [
                t.number,
                t.type_label,
                t.title,
                t.status_label,
                t.priority_label,
                t.category.name if t.category else "",
                t.group.name if t.group else "",
                t.assignee.name if t.assignee else "",
                t.requester.name,
                t.requester.email,
                t.requester.department or "",
                t.channel_label,
                fmt_datetime(t.created_at),
                fmt_datetime(t.first_response_at) if t.first_response_at else "",
                fmt_datetime(t.resolved_at) if t.resolved_at else "",
                fmt_datetime(t.resolution_due) if t.resolution_due else "",
                sla_labels.get(t.resolution_sla(), ""),
                t.satisfaction or "",
            ]
        )
    filename = f"chamados-{utcnow():%Y%m%d-%H%M}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
def new_ticket():
    options = _form_options()
    form = request.form
    if request.method == "POST":
        try:
            category = db.session.get(Category, form.get("category_id", type=int) or 0)
            asset = db.session.get(Asset, form.get("asset_id", type=int) or 0)
            if current_user.is_agent:
                requester = current_user
                if form.get("requester_email", "").strip():
                    email = form["requester_email"].strip().lower()
                    requester = db.session.scalar(db.select(User).where(db.func.lower(User.email) == email))
                    if requester is None:
                        raise services.ServiceError(f"Nenhum usuário cadastrado com o e-mail {email}.")
                group = db.session.get(Group, form.get("group_id", type=int) or 0)
                assignee = db.session.get(User, form.get("assignee_id", type=int) or 0)
                if assignee is not None and not assignee.is_agent:
                    assignee = None
                channel = form.get("channel") if form.get("channel") in CHANNELS else "phone"
            else:
                requester, group, assignee, channel = current_user, None, None, "portal"
                if asset is not None and asset.assigned_to_id != current_user.id:
                    asset = None
            can_set = current_user.is_agent or get_bool("requester_can_set_priority")
            ticket = services.create_ticket(
                requester,
                form.get("title"),
                form.get("description"),
                created_by=current_user,
                type=form.get("type", "incident"),
                category=category,
                impact=form.get("impact", 3) if can_set else 3,
                urgency=form.get("urgency", 3) if can_set else 3,
                channel=channel,
                group=group,
                assignee=assignee,
                asset=asset,
                files=request.files.getlist("files"),
            )
        except services.ServiceError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        else:
            flash(f"Chamado {ticket.number} aberto com sucesso.", "success")
            return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    users = []
    if current_user.is_agent:
        users = db.session.scalars(db.select(User).where(User.active.is_(True)).order_by(User.name)).all()
        assets = db.session.scalars(
            db.select(Asset).where(Asset.status != "retired").order_by(Asset.tag)
        ).all()
    else:
        assets = db.session.scalars(db.select(Asset).where(Asset.assigned_to_id == current_user.id)).all()
    return render_template("tickets/new.html", form=form, users=users, assets=assets, **options)


@bp.route("/<int:ticket_id>")
@login_required
def detail(ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    comments = services.visible_comments(ticket, current_user)
    timeline = [{"kind": "comment", "at": c.created_at, "item": c} for c in comments]
    for event in ticket.events:
        if event.action == "created":
            continue
        if current_user.is_agent or event.action in ("status", "reopened"):
            timeline.append({"kind": "event", "at": event.created_at, "item": event})
    timeline.sort(key=lambda entry: (entry["at"], entry["kind"] == "comment"))

    ticket_files = [a for a in ticket.attachments if a.comment_id is None]
    context = {
        "ticket": ticket,
        "timeline": timeline,
        "ticket_files": ticket_files,
        "can_reopen": services.can_reopen(current_user, ticket),
        "now": utcnow(),
    }
    if current_user.is_agent:
        context.update(_form_options())
        context["assets"] = db.session.scalars(db.select(Asset).order_by(Asset.tag)).all()
        context["other_open"] = db.session.scalar(
            db.select(db.func.count(Ticket.id)).where(
                Ticket.requester_id == ticket.requester_id,
                Ticket.status.in_(OPEN_STATUSES),
                Ticket.id != ticket.id,
            )
        )
    return render_template("tickets/detail.html", **context)


@bp.route("/<int:ticket_id>/atualizar", methods=["POST"])
@agent_required
def update(ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    fields = (
        "title",
        "type",
        "status",
        "category_id",
        "group_id",
        "assignee_id",
        "asset_id",
        "impact",
        "urgency",
        "resolution_code",
        "resolution_notes",
    )
    data = {k: request.form.get(k) for k in fields if k in request.form}
    try:
        changed = services.update_ticket(ticket, current_user, data)
    except services.ServiceError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    else:
        flash("Chamado atualizado." if changed else "Nenhuma alteração.", "success" if changed else "info")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@bp.route("/<int:ticket_id>/comentar", methods=["POST"])
@login_required
def comment(ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    internal = request.form.get("internal") == "1"
    try:
        services.add_comment(
            ticket,
            current_user,
            request.form.get("body"),
            internal=internal,
            files=request.files.getlist("files"),
        )
        new_status = request.form.get("then_status")
        if (
            current_user.is_agent
            and new_status in STATUSES
            and new_status not in (STATUS_RESOLVED, STATUS_CLOSED)
        ):
            services.set_status(ticket, current_user, new_status)
    except services.ServiceError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    else:
        flash(
            "Nota interna registrada." if internal and current_user.is_agent else "Mensagem enviada.",
            "success",
        )
    return redirect(url_for("tickets.detail", ticket_id=ticket.id) + "#atividade")


@bp.route("/<int:ticket_id>/assumir", methods=["POST"])
@agent_required
def take(ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    try:
        services.take_ticket(ticket, current_user)
    except services.ServiceError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    else:
        flash("Chamado atribuído a você.", "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@bp.route("/<int:ticket_id>/reabrir", methods=["POST"])
@login_required
def reopen(ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    reason = (request.form.get("reason") or "").strip()
    try:
        services.reopen(ticket, current_user)
        if reason:
            services.add_comment(ticket, current_user, f"Chamado reaberto: {reason}")
    except services.ServiceError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    else:
        flash("Chamado reaberto.", "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@bp.route("/<int:ticket_id>/cancelar", methods=["POST"])
@login_required
def cancel(ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    try:
        services.cancel(ticket, current_user)
    except services.ServiceError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    else:
        flash("Chamado cancelado.", "info")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@bp.route("/<int:ticket_id>/avaliar", methods=["POST"])
@login_required
def rate(ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    try:
        services.rate(ticket, current_user, request.form.get("score"), request.form.get("comment"))
    except services.ServiceError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    else:
        flash("Obrigado pela avaliação!", "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"}


@bp.route("/anexo/<int:attachment_id>")
@login_required
def attachment(attachment_id):
    item = db.session.get(Attachment, attachment_id)
    if item is None:
        abort(404)
    if not services.can_view(current_user, item.ticket) or (item.is_internal and not current_user.is_agent):
        abort(403)
    path = services.attachment_path(item)
    if not os.path.exists(path):
        abort(404)
    inline = item.content_type in INLINE_TYPES and request.args.get("baixar") is None
    response = send_file(
        path,
        mimetype=item.content_type if inline else "application/octet-stream",
        as_attachment=not inline,
        download_name=item.filename,
    )
    if item.content_type != "application/pdf":
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        )
    return response
