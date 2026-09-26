import re

from .constants import DONE_STATUSES, OPEN_STATUSES, PAUSED_STATUSES, STATUSES, TYPES
from .extensions import db
from .models import Ticket, User, overdue_filter, utcnow
from .settings import get_setting

AGENT_VIEWS = {
    "abertos": "Todos em aberto",
    "meus": "Atribuídos a mim",
    "grupos": "Dos meus grupos",
    "sem_responsavel": "Sem responsável",
    "atrasados": "SLA vencido",
    "aguardando": "Em espera",
    "encerrados": "Resolvidos / fechados",
    "todos": "Todos",
}
USER_VIEWS = {
    "abertos": "Em aberto",
    "encerrados": "Encerrados",
    "todos": "Todos",
}
VIEW_FILTERS = {
    "abertos": lambda user: [Ticket.status.in_(OPEN_STATUSES)],
    "meus": lambda user: [Ticket.status.in_(OPEN_STATUSES), Ticket.assignee_id == user.id],
    "grupos": lambda user: [
        Ticket.status.in_(OPEN_STATUSES),
        Ticket.group_id.in_([g.id for g in user.groups]),
    ],
    "sem_responsavel": lambda user: [Ticket.status.in_(OPEN_STATUSES), Ticket.assignee_id.is_(None)],
    "atrasados": lambda user: overdue_filter(utcnow()),
    "aguardando": lambda user: [Ticket.status.in_(PAUSED_STATUSES)],
    "encerrados": lambda user: [Ticket.status.in_(DONE_STATUSES)],
    "todos": lambda user: [],
}
SORTS = {
    "prioridade": (Ticket.priority.asc(), Ticket.created_at.asc()),
    "recentes": (Ticket.created_at.desc(),),
    "atualizados": (Ticket.updated_at.desc(),),
    "prazo": (Ticket.resolution_due.is_(None), Ticket.resolution_due.asc()),
}


def filtered_query(args, user):
    query = db.select(Ticket)
    views = AGENT_VIEWS if user.is_agent else USER_VIEWS
    view = args.get("view") if args.get("view") in views else "abertos"
    if not user.is_agent:
        query = query.where(Ticket.requester_id == user.id)

    query = query.where(*VIEW_FILTERS[view](user))

    text = (args.get("q") or "").strip()
    if text:
        prefix = re.escape(get_setting("ticket_prefix"))
        number = re.fullmatch(rf"(?i)(?:{prefix})?0*(\d+)", text)
        like = f"%{text}%"
        conditions = [Ticket.title.ilike(like), Ticket.description.ilike(like)]
        if user.is_agent:
            conditions.append(Ticket.requester.has(User.name.ilike(like)))
            conditions.append(Ticket.requester.has(User.email.ilike(like)))
        if number:
            conditions.append(Ticket.id == int(number.group(1)))
        query = query.where(db.or_(*conditions))

    if args.get("status") in STATUSES:
        query = query.where(Ticket.status == args["status"])
    if args.get("type") in TYPES:
        query = query.where(Ticket.type == args["type"])
    for field, column in (
        ("priority", Ticket.priority),
        ("group", Ticket.group_id),
        ("category", Ticket.category_id),
        ("assignee", Ticket.assignee_id),
    ):
        value = args.get(field, "")
        if value.isdigit():
            query = query.where(column == int(value))

    sort = args.get("sort") if args.get("sort") in SORTS else ("prioridade" if user.is_agent else "recentes")
    query = query.order_by(*SORTS[sort])
    return query, view, sort
