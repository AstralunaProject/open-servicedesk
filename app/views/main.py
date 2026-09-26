from collections import Counter
from datetime import timedelta

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from ..constants import OPEN_STATUSES, PAUSED_STATUSES, STATUS_CLOSED, STATUS_RESOLVED
from ..extensions import db
from ..models import KBArticle, Ticket, overdue_filter, utcnow
from ..utils import to_local

bp = Blueprint("main", __name__)


@bp.route("/saude")
def health():
    db.session.execute(db.text("SELECT 1"))
    return {"status": "ok"}


@bp.route("/")
@login_required
def index():
    if current_user.is_agent:
        return dashboard()
    return portal()


def portal():
    mine = db.select(Ticket).where(Ticket.requester_id == current_user.id)
    open_tickets = db.session.scalars(
        mine.where(Ticket.status.in_(OPEN_STATUSES)).order_by(Ticket.updated_at.desc())
    ).all()
    to_rate = db.session.scalars(
        mine.where(Ticket.status.in_([STATUS_RESOLVED, STATUS_CLOSED]), Ticket.satisfaction.is_(None))
        .order_by(Ticket.resolved_at.desc())
        .limit(5)
    ).all()
    articles = db.session.scalars(
        db.select(KBArticle)
        .where(KBArticle.published.is_(True), KBArticle.internal.is_(False))
        .order_by(KBArticle.views.desc())
        .limit(6)
    ).all()
    return render_template("portal.html", open_tickets=open_tickets, to_rate=to_rate, articles=articles)


def _count(*conditions) -> int:
    return db.session.scalar(db.select(db.func.count(Ticket.id)).where(*conditions)) or 0


def dashboard():
    now = utcnow()
    is_open = Ticket.status.in_(OPEN_STATUSES)
    my_group_ids = [g.id for g in current_user.groups]

    kpis = {
        "open": _count(is_open),
        "unassigned": _count(is_open, Ticket.assignee_id.is_(None)),
        "mine": _count(is_open, Ticket.assignee_id == current_user.id),
        "overdue": _count(*overdue_filter(now)),
        "waiting": _count(Ticket.status.in_(PAUSED_STATUSES)),
        "my_groups": _count(is_open, Ticket.group_id.in_(my_group_ids)) if my_group_ids else 0,
    }

    def grouped(column):
        rows = db.session.execute(db.select(column, db.func.count(Ticket.id)).where(is_open).group_by(column))
        return dict(rows.all())

    by_status = grouped(Ticket.status)
    by_priority = grouped(Ticket.priority)
    by_group = db.session.execute(
        db.select(Ticket.group_id, db.func.count(Ticket.id)).where(is_open).group_by(Ticket.group_id)
    ).all()
    from ..models import Group

    group_names = {g.id: g.name for g in db.session.scalars(db.select(Group))}
    by_group = sorted(((group_names.get(gid, "Sem grupo"), n) for gid, n in by_group), key=lambda r: -r[1])

    since = now - timedelta(days=30)
    recent_resolved = db.session.scalars(
        db.select(Ticket).where(Ticket.resolved_at.is_not(None), Ticket.resolved_at >= since)
    ).all()
    resolution_minutes = [(t.resolved_at - t.created_at).total_seconds() / 60 for t in recent_resolved]
    within_sla = [t for t in recent_resolved if t.resolution_due and t.resolved_at <= t.resolution_due]
    ratings = [t.satisfaction for t in recent_resolved if t.satisfaction]
    stats = {
        "resolved_30": len(recent_resolved),
        "avg_resolution": sum(resolution_minutes) / len(resolution_minutes) if resolution_minutes else None,
        "sla_rate": round(100 * len(within_sla) / len(recent_resolved)) if recent_resolved else None,
        "csat": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "csat_count": len(ratings),
    }

    days = [(to_local(now) - timedelta(days=i)).date() for i in range(13, -1, -1)]
    start = now - timedelta(days=15)
    created = Counter(
        to_local(d).date()
        for d in db.session.scalars(db.select(Ticket.created_at).where(Ticket.created_at >= start))
    )
    resolved = Counter(
        to_local(d).date()
        for d in db.session.scalars(db.select(Ticket.resolved_at).where(Ticket.resolved_at >= start))
    )
    daily = [{"day": d, "created": created.get(d, 0), "resolved": resolved.get(d, 0)} for d in days]
    daily_max = max([1] + [max(x["created"], x["resolved"]) for x in daily])

    top_categories = db.session.execute(
        db.select(Ticket.category_id, db.func.count(Ticket.id))
        .where(Ticket.created_at >= since)
        .group_by(Ticket.category_id)
        .order_by(db.func.count(Ticket.id).desc())
        .limit(6)
    ).all()
    from ..models import Category

    cat_names = {c.id: c.name for c in db.session.scalars(db.select(Category))}
    top_categories = [(cat_names.get(cid, "Sem categoria"), n) for cid, n in top_categories]

    my_queue = db.session.scalars(
        db.select(Ticket)
        .where(is_open, Ticket.assignee_id == current_user.id)
        .order_by(Ticket.priority, Ticket.resolution_due)
        .limit(10)
    ).all()
    unassigned = db.session.scalars(
        db.select(Ticket)
        .where(is_open, Ticket.assignee_id.is_(None))
        .order_by(Ticket.priority, Ticket.created_at)
        .limit(10)
    ).all()

    return render_template(
        "dashboard.html",
        kpis=kpis,
        by_status=by_status,
        by_priority=by_priority,
        by_group=by_group,
        stats=stats,
        daily=daily,
        daily_max=daily_max,
        top_categories=top_categories,
        my_queue=my_queue,
        unassigned=unassigned,
        now=now,
    )
