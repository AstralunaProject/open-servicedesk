import os
import uuid
from datetime import timedelta

from flask import current_app

from . import notifications, sla
from .constants import (
    DONE_STATUSES,
    IMPACTS,
    OPEN_STATUSES,
    PAUSED_STATUSES,
    PRIORITIES,
    RESOLUTION_CODES,
    STATUS_CANCELLED,
    STATUS_CLOSED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_RESOLVED,
    STATUSES,
    TYPES,
    URGENCIES,
    calc_priority,
)
from .extensions import db
from .models import Asset, Attachment, Category, Comment, Group, Ticket, TicketEvent, User, utcnow
from .settings import get_int


class ServiceError(Exception):
    """Erro de regra de negócio, com mensagem pronta para o usuário."""


def can_view(user, ticket) -> bool:
    return bool(user and user.is_authenticated and (user.is_agent or ticket.requester_id == user.id))


def can_reopen(user, ticket) -> bool:
    if ticket.status != STATUS_RESOLVED:
        return False
    if user.is_agent:
        return True
    if ticket.requester_id != user.id:
        return False
    limit = get_int("reopen_days", 7)
    return ticket.resolved_at is not None and utcnow() - ticket.resolved_at <= timedelta(days=limit)


def visible_comments(ticket, user):
    return [c for c in ticket.comments if user.is_agent or not c.internal]


def log_event(ticket, user, action, field=None, old=None, new=None) -> None:
    def short(value):
        return None if value is None else str(value)[:255]

    db.session.add(
        TicketEvent(
            ticket=ticket,
            user_id=user.id if user else None,
            action=action,
            field=field,
            old_value=short(old),
            new_value=short(new),
        )
    )


def save_uploads(ticket, files, user, comment=None) -> list:
    saved = []
    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    for storage in files or []:
        if storage is None or not storage.filename:
            continue
        original = os.path.basename(storage.filename.replace("\\", "/")).strip() or "arquivo"
        ext = os.path.splitext(original)[1].lower()[:10]
        if not ext.replace(".", "").isalnum():
            ext = ""
        stored = uuid.uuid4().hex + ext
        path = os.path.join(upload_dir, stored)
        storage.save(path)
        attachment = Attachment(
            ticket=ticket,
            comment=comment,
            uploaded_by_id=user.id if user else None,
            filename=original[:255],
            stored_name=stored,
            content_type=(storage.mimetype or "application/octet-stream")[:120],
            size=os.path.getsize(path),
        )
        db.session.add(attachment)
        saved.append(attachment)
    return saved


def attachment_path(attachment) -> str:
    return os.path.join(current_app.config["UPLOAD_DIR"], attachment.stored_name)


def _as_int(value, allowed, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value in allowed else default


def create_ticket(
    requester,
    title,
    description,
    *,
    created_by=None,
    type="incident",
    category=None,
    impact=3,
    urgency=3,
    channel="portal",
    group=None,
    assignee=None,
    asset=None,
    files=None,
) -> Ticket:
    title = (title or "").strip()
    if not title:
        raise ServiceError("Informe um título para o chamado.")
    if requester is None:
        raise ServiceError("Informe o solicitante.")
    created_by = created_by or requester
    impact = _as_int(impact, IMPACTS, 3)
    urgency = _as_int(urgency, URGENCIES, 3)
    if group is None and category is not None and category.default_group and category.default_group.active:
        group = category.default_group

    now = utcnow()
    ticket = Ticket(
        type=type if type in TYPES else "incident",
        title=title[:200],
        description=(description or "").strip(),
        status=STATUS_NEW,
        impact=impact,
        urgency=urgency,
        priority=calc_priority(impact, urgency),
        channel=channel,
        category=category,
        group=group,
        assignee=assignee,
        requester=requester,
        created_by=created_by,
        asset=asset,
        created_at=now,
        updated_at=now,
    )
    sla.apply_sla(ticket, now)
    db.session.add(ticket)
    db.session.flush()
    log_event(ticket, created_by, "created")
    if assignee:
        log_event(ticket, created_by, "assigned", "assignee", None, assignee.name)
    save_uploads(ticket, files, created_by)
    db.session.commit()
    notifications.ticket_created(ticket)
    return ticket


def add_comment(ticket, author, body, *, internal=False, files=None) -> Comment:
    body = (body or "").strip()
    has_files = any(f and f.filename for f in (files or []))
    if not body and not has_files:
        raise ServiceError("Escreva uma mensagem ou anexe um arquivo.")
    if ticket.status in (STATUS_CLOSED, STATUS_CANCELLED) and not author.is_agent:
        raise ServiceError("Este chamado está encerrado. Abra um novo chamado.")
    internal = bool(internal and author.is_agent)
    now = utcnow()

    comment = Comment(ticket=ticket, author=author, body=body or "(anexo)", internal=internal, created_at=now)
    db.session.add(comment)
    db.session.flush()
    save_uploads(ticket, files, author, comment)

    is_requester = author.id == ticket.requester_id
    if author.is_agent and not internal and not is_requester and ticket.first_response_at is None:
        ticket.first_response_at = now
    if is_requester and not internal:
        if ticket.status in PAUSED_STATUSES:
            set_status(ticket, author, STATUS_IN_PROGRESS, commit=False, notify=False)
        elif ticket.status == STATUS_RESOLVED and can_reopen(author, ticket):
            set_status(ticket, author, STATUS_IN_PROGRESS, commit=False, notify=False)
    ticket.updated_at = now
    db.session.commit()
    notifications.comment_added(ticket, comment)
    return comment


def set_status(
    ticket,
    user,
    new_status,
    *,
    resolution_code=None,
    resolution_notes=None,
    commit=True,
    notify=True,
) -> None:
    if new_status not in STATUSES:
        raise ServiceError("Status inválido.")
    old_status = ticket.status
    if new_status == old_status:
        return
    now = utcnow()

    if new_status == STATUS_RESOLVED:
        notes = (resolution_notes or "").strip()
        if not notes:
            raise ServiceError("Descreva a solução para resolver o chamado.")
        ticket.resolution_notes = notes
        ticket.resolution_code = resolution_code if resolution_code in RESOLUTION_CODES else "solved"
        ticket.resolved_at = now
    elif new_status == STATUS_CLOSED:
        ticket.closed_at = now
        if ticket.resolved_at is None:
            ticket.resolved_at = now
    elif new_status == STATUS_CANCELLED:
        ticket.closed_at = now

    reopening = old_status in DONE_STATUSES and new_status in OPEN_STATUSES
    if reopening:
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.resolution_code = None
        ticket.satisfaction = None
        ticket.satisfaction_comment = None

    if old_status in PAUSED_STATUSES and new_status not in PAUSED_STATUSES:
        sla.resume(ticket, now)
    if new_status in PAUSED_STATUSES and old_status not in PAUSED_STATUSES:
        sla.pause(ticket, now)

    if user and user.is_agent and user.id != ticket.requester_id and ticket.first_response_at is None:
        if new_status != STATUS_NEW:
            ticket.first_response_at = now

    ticket.status = new_status
    ticket.updated_at = now
    log_event(ticket, user, "reopened" if reopening else "status", "status", old_status, new_status)
    if commit:
        db.session.commit()
    if notify:
        notifications.status_changed(ticket, old_status, user)


RELATIONS = (
    ("category_id", Category, "category", "name"),
    ("group_id", Group, "group", "name"),
    ("assignee_id", User, "assignee", "name"),
    ("asset_id", Asset, "asset", "display"),
)


def _update_basic_fields(ticket, user, data) -> list:
    changed = []
    title = (data.get("title") or "").strip()[:200]
    if title and title != ticket.title:
        log_event(ticket, user, "field", "title", ticket.title, title)
        ticket.title = title
        changed.append("title")
    if data.get("type") in TYPES and data["type"] != ticket.type:
        log_event(ticket, user, "field", "type", TYPES[ticket.type], TYPES[data["type"]])
        ticket.type = data["type"]
        changed.append("type")
    return changed


def _update_relations(ticket, user, data) -> list:
    changed = []
    for key, model, attr, label_attr in RELATIONS:
        if key not in data:
            continue
        try:
            new_id = int(data[key] or 0)
        except (TypeError, ValueError):
            raise ServiceError("Valor inválido.") from None
        new = db.session.get(model, new_id) if new_id else None
        current = getattr(ticket, attr)
        if (new.id if new else None) == (current.id if current else None):
            continue
        log_event(
            ticket,
            user,
            "assigned" if attr == "assignee" else "field",
            attr,
            getattr(current, label_attr) if current else None,
            getattr(new, label_attr) if new else None,
        )
        setattr(ticket, attr, new)
        changed.append(attr)
    if ticket.assignee is not None and not ticket.assignee.is_agent:
        raise ServiceError("O responsável precisa ser um técnico.")
    return changed


def _update_priority(ticket, user, data) -> list:
    changed = []
    impact = _as_int(data.get("impact"), IMPACTS, ticket.impact)
    urgency = _as_int(data.get("urgency"), URGENCIES, ticket.urgency)
    if impact != ticket.impact:
        log_event(ticket, user, "field", "impact", IMPACTS[ticket.impact], IMPACTS[impact])
        ticket.impact = impact
        changed.append("impact")
    if urgency != ticket.urgency:
        log_event(ticket, user, "field", "urgency", URGENCIES[ticket.urgency], URGENCIES[urgency])
        ticket.urgency = urgency
        changed.append("urgency")
    priority = calc_priority(ticket.impact, ticket.urgency)
    if priority != ticket.priority:
        log_event(ticket, user, "field", "priority", PRIORITIES[ticket.priority], PRIORITIES[priority])
        ticket.priority = priority
        sla.apply_sla(ticket)
        changed.append("priority")
    return changed


def _update_status(ticket, user, data, assignee_changed: bool) -> list:
    new_status = data.get("status")
    # Atribuir um chamado novo a alguém significa que o atendimento começou.
    if (
        assignee_changed
        and ticket.assignee
        and ticket.status == STATUS_NEW
        and new_status in (None, STATUS_NEW)
    ):
        new_status = STATUS_IN_PROGRESS

    if new_status and new_status != ticket.status:
        set_status(
            ticket,
            user,
            new_status,
            resolution_code=data.get("resolution_code"),
            resolution_notes=data.get("resolution_notes"),
            commit=False,
        )
        return ["status"]

    notes = (data.get("resolution_notes") or "").strip()
    if ticket.status != STATUS_RESOLVED or not notes or notes == ticket.resolution_notes:
        return []
    ticket.resolution_notes = notes
    if data.get("resolution_code") in RESOLUTION_CODES:
        ticket.resolution_code = data["resolution_code"]
    return ["resolution"]


def update_ticket(ticket, user, data: dict) -> list:
    if not user.is_agent:
        raise ServiceError("Sem permissão para alterar o chamado.")
    resolving = data.get("status") == STATUS_RESOLVED and ticket.status != STATUS_RESOLVED
    if resolving and not (data.get("resolution_notes") or "").strip():
        raise ServiceError("Descreva a solução para resolver o chamado.")

    old_assignee = ticket.assignee
    changed = _update_basic_fields(ticket, user, data)
    changed += _update_relations(ticket, user, data)
    changed += _update_priority(ticket, user, data)
    changed += _update_status(ticket, user, data, "assignee" in changed)

    if changed:
        ticket.updated_at = utcnow()
    db.session.commit()
    if ticket.assignee and ticket.assignee != old_assignee:
        notifications.ticket_assigned(ticket, user)
    return changed


def take_ticket(ticket, user) -> None:
    update_ticket(ticket, user, {"assignee_id": user.id})


def reopen(ticket, user) -> None:
    if not can_reopen(user, ticket):
        raise ServiceError("Este chamado não pode mais ser reaberto.")
    set_status(ticket, user, STATUS_IN_PROGRESS)


def cancel(ticket, user) -> None:
    if not (user.is_agent or ticket.requester_id == user.id):
        raise ServiceError("Sem permissão.")
    if ticket.status not in OPEN_STATUSES:
        raise ServiceError("Somente chamados em aberto podem ser cancelados.")
    set_status(ticket, user, STATUS_CANCELLED)


def rate(ticket, user, score, comment=None) -> None:
    if ticket.requester_id != user.id:
        raise ServiceError("Somente o solicitante pode avaliar o atendimento.")
    if ticket.status not in (STATUS_RESOLVED, STATUS_CLOSED):
        raise ServiceError("O chamado ainda não foi resolvido.")
    score = _as_int(score, range(1, 6), None)
    if score is None:
        raise ServiceError("Escolha uma nota de 1 a 5.")
    ticket.satisfaction = score
    ticket.satisfaction_comment = (comment or "").strip() or None
    log_event(ticket, user, "rated", "satisfaction", None, score)
    db.session.commit()


def auto_close_resolved() -> int:
    days = get_int("auto_close_days", 5)
    if days <= 0:
        return 0
    limit = utcnow() - timedelta(days=days)
    tickets = db.session.scalars(
        db.select(Ticket).where(Ticket.status == STATUS_RESOLVED, Ticket.resolved_at < limit)
    ).all()
    for ticket in tickets:
        set_status(ticket, None, STATUS_CLOSED, commit=False, notify=False)
    if tickets:
        db.session.commit()
    return len(tickets)
