"""API REST simples para integrações (bots, monitoramento, scripts).

Autenticação: cabeçalho `Authorization: Bearer <token>` (gerado em "Meu perfil").
"""

from functools import wraps

from flask import Blueprint, g, jsonify, request

from .. import services
from ..constants import CHANNELS
from ..extensions import db
from ..models import Category, Comment, Ticket, User
from ..settings import get_bool
from ..ticket_query import filtered_query
from ..utils import to_local

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _iso(value):
    return to_local(value).isoformat() if value else None


def token_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        user = None
        if token:
            user = db.session.scalar(db.select(User).where(User.api_token_hash == User.hash_token(token)))
        if user is None or not user.active:
            return jsonify(error="Token inválido ou ausente."), 401
        g.api_user = user
        return view(*args, **kwargs)

    return wrapper


def _user(user):
    if user is None:
        return None
    return {"id": user.id, "name": user.name, "email": user.email}


def _comment(comment: Comment) -> dict:
    return {
        "id": comment.id,
        "author": _user(comment.author),
        "body": comment.body,
        "internal": comment.internal,
        "created_at": _iso(comment.created_at),
    }


def serialize(ticket: Ticket, full: bool = False) -> dict:
    data = {
        "id": ticket.id,
        "number": ticket.number,
        "type": ticket.type,
        "title": ticket.title,
        "status": ticket.status,
        "status_label": ticket.status_label,
        "priority": ticket.priority,
        "priority_label": ticket.priority_label,
        "impact": ticket.impact,
        "urgency": ticket.urgency,
        "channel": ticket.channel,
        "category": ticket.category.name if ticket.category else None,
        "group": ticket.group.name if ticket.group else None,
        "assignee": _user(ticket.assignee),
        "requester": _user(ticket.requester),
        "created_at": _iso(ticket.created_at),
        "updated_at": _iso(ticket.updated_at),
        "resolved_at": _iso(ticket.resolved_at),
        "response_due": _iso(ticket.response_due),
        "resolution_due": _iso(ticket.resolution_due),
        "sla": ticket.resolution_sla(),
    }
    if full:
        data["description"] = ticket.description
        data["resolution_notes"] = ticket.resolution_notes
        data["comments"] = [_comment(c) for c in services.visible_comments(ticket, g.api_user)]
    return data


def _ticket_or_error(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None or not services.can_view(g.api_user, ticket):
        return None
    return ticket


@bp.route("/me")
@token_required
def me():
    user = g.api_user
    return jsonify(id=user.id, name=user.name, email=user.email, role=user.role)


@bp.route("/tickets")
@token_required
def list_tickets():
    args = request.args.to_dict()
    args.setdefault("view", "todos")
    query, _, _ = filtered_query(args, g.api_user)
    page = db.paginate(
        query,
        page=request.args.get("page", 1, type=int),
        per_page=min(100, request.args.get("per_page", 50, type=int)),
        error_out=False,
    )
    return jsonify(
        items=[serialize(t) for t in page.items], page=page.page, pages=page.pages, total=page.total
    )


@bp.route("/tickets", methods=["POST"])
@token_required
def create_ticket():
    data = request.get_json(silent=True) or {}
    user = g.api_user
    requester = user
    if data.get("requester_email"):
        if not user.is_agent:
            return jsonify(error="Somente técnicos podem abrir chamados em nome de outra pessoa."), 403
        requester = db.session.scalar(
            db.select(User).where(db.func.lower(User.email) == str(data["requester_email"]).strip().lower())
        )
        if requester is None:
            return jsonify(error="Solicitante não encontrado."), 404
    category = None
    if data.get("category"):
        category = db.session.scalar(
            db.select(Category).where(db.func.lower(Category.name) == str(data["category"]).lower())
        )
    can_set = user.is_agent or get_bool("requester_can_set_priority")
    try:
        ticket = services.create_ticket(
            requester,
            data.get("title"),
            data.get("description"),
            created_by=user,
            type=data.get("type", "incident"),
            category=category,
            impact=data.get("impact", 3) if can_set else 3,
            urgency=data.get("urgency", 3) if can_set else 3,
            channel=data.get("channel") if data.get("channel") in CHANNELS else "api",
        )
    except services.ServiceError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(serialize(ticket, full=True)), 201


@bp.route("/tickets/<int:ticket_id>")
@token_required
def get_ticket(ticket_id):
    ticket = _ticket_or_error(ticket_id)
    if ticket is None:
        return jsonify(error="Chamado não encontrado."), 404
    return jsonify(serialize(ticket, full=True))


@bp.route("/tickets/<int:ticket_id>", methods=["PATCH"])
@token_required
def update_ticket(ticket_id):
    ticket = _ticket_or_error(ticket_id)
    if ticket is None:
        return jsonify(error="Chamado não encontrado."), 404
    if not g.api_user.is_agent:
        return jsonify(error="Sem permissão."), 403
    data = request.get_json(silent=True) or {}
    allowed = {
        "title",
        "type",
        "status",
        "impact",
        "urgency",
        "assignee_id",
        "group_id",
        "category_id",
        "resolution_code",
        "resolution_notes",
    }
    try:
        services.update_ticket(ticket, g.api_user, {k: v for k, v in data.items() if k in allowed})
    except services.ServiceError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(serialize(ticket, full=True))


@bp.route("/tickets/<int:ticket_id>/comments", methods=["POST"])
@token_required
def add_comment(ticket_id):
    ticket = _ticket_or_error(ticket_id)
    if ticket is None:
        return jsonify(error="Chamado não encontrado."), 404
    data = request.get_json(silent=True) or {}
    try:
        comment = services.add_comment(
            ticket, g.api_user, data.get("body"), internal=bool(data.get("internal"))
        )
    except services.ServiceError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(_comment(comment)), 201
