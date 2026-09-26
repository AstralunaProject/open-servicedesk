import hashlib
import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .constants import (
    ASSET_STATUSES,
    CHANNELS,
    OPEN_STATUSES,
    PAUSED_STATUSES,
    PRIORITIES,
    ROLE_ADMIN,
    ROLE_AGENT,
    ROLE_USER,
    ROLES,
    STATUS_CANCELLED,
    STATUS_CLOSED,
    STATUS_NEW,
    STATUSES,
    TYPES,
)
from .extensions import db, login_manager


def utcnow() -> datetime:
    """Datas são gravadas em UTC sem fuso (naive) e convertidas na exibição."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


group_members = db.Table(
    "group_members",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("group_id", db.Integer, db.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))
    role = db.Column(db.String(20), nullable=False, default=ROLE_USER)
    department = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    active = db.Column(db.Boolean, nullable=False, default=True)
    api_token_hash = db.Column(db.String(64), index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime)

    groups = db.relationship(
        "Group", secondary=group_members, back_populates="members", order_by="Group.name"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

    @property
    def is_active(self) -> bool:  # usado pelo Flask-Login
        return bool(self.active)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_agent(self) -> bool:
        return self.role in (ROLE_ADMIN, ROLE_AGENT)

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role)

    @property
    def initials(self) -> str:
        parts = [p for p in (self.name or "?").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return (parts[0][:2] if parts else "?").upper()

    def generate_api_token(self) -> str:
        token = "tic_" + secrets.token_urlsafe(32)
        self.api_token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def __repr__(self) -> str:
        return f"<User {self.email}>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)
    email = db.Column(db.String(255))
    active = db.Column(db.Boolean, nullable=False, default=True)

    members = db.relationship("User", secondary=group_members, back_populates="groups", order_by="User.name")


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(255))
    default_group_id = db.Column(db.Integer, db.ForeignKey("groups.id", ondelete="SET NULL"))
    active = db.Column(db.Boolean, nullable=False, default=True)

    default_group = db.relationship("Group")


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False, default="incident")
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default=STATUS_NEW, index=True)
    impact = db.Column(db.Integer, nullable=False, default=3)
    urgency = db.Column(db.Integer, nullable=False, default=3)
    priority = db.Column(db.Integer, nullable=False, default=4, index=True)
    channel = db.Column(db.String(20), nullable=False, default="portal")

    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"))
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id", ondelete="SET NULL"), index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id", ondelete="SET NULL"))

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    first_response_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)

    response_due = db.Column(db.DateTime)
    resolution_due = db.Column(db.DateTime, index=True)
    sla_paused_at = db.Column(db.DateTime)
    sla_paused_minutes = db.Column(db.Integer, nullable=False, default=0)

    resolution_code = db.Column(db.String(30))
    resolution_notes = db.Column(db.Text)

    satisfaction = db.Column(db.Integer)
    satisfaction_comment = db.Column(db.Text)

    category = db.relationship("Category")
    group = db.relationship("Group")
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    requester = db.relationship("User", foreign_keys=[requester_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    asset = db.relationship("Asset", back_populates="tickets")

    comments = db.relationship(
        "Comment", back_populates="ticket", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    events = db.relationship(
        "TicketEvent",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketEvent.created_at",
    )
    attachments = db.relationship(
        "Attachment", back_populates="ticket", cascade="all, delete-orphan", order_by="Attachment.created_at"
    )

    @property
    def number(self) -> str:
        from .settings import get_setting

        return f"{get_setting('ticket_prefix')}{self.id:06d}"

    @property
    def status_label(self) -> str:
        return STATUSES.get(self.status, self.status)

    @property
    def priority_label(self) -> str:
        return PRIORITIES.get(self.priority, str(self.priority))

    @property
    def type_label(self) -> str:
        return TYPES.get(self.type, self.type)

    @property
    def channel_label(self) -> str:
        return CHANNELS.get(self.channel, self.channel)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_paused(self) -> bool:
        return self.status in PAUSED_STATUSES

    def response_sla(self, now=None):
        return _sla_state(self.created_at, self.response_due, self.first_response_at, self, now)

    def resolution_sla(self, now=None):
        done = self.resolved_at or (self.closed_at if self.status == STATUS_CLOSED else None)
        return _sla_state(self.created_at, self.resolution_due, done, self, now)


def overdue_filter(now) -> list:
    # Chamados em espera não contam como atrasados: o prazo só é recalculado na retomada.
    return [
        Ticket.status.in_(OPEN_STATUSES),
        Ticket.status.notin_(PAUSED_STATUSES),
        Ticket.resolution_due < now,
    ]


def _sla_state(start, due, done_at, ticket, now=None):
    """Retorna 'met', 'breached', 'paused', 'warning', 'ok' ou None."""
    if due is None or ticket.status == STATUS_CANCELLED:
        return None
    if done_at is not None:
        return "met" if done_at <= due else "breached"
    if ticket.is_paused:
        return "paused"
    now = now or utcnow()
    if now > due:
        return "breached"
    total = (due - start).total_seconds()
    if total > 0 and (due - now).total_seconds() < total * 0.25:
        return "warning"
    return "ok"


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    body = db.Column(db.Text, nullable=False)
    internal = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="comments")
    author = db.relationship("User")
    attachments = db.relationship("Attachment", back_populates="comment")


class Attachment(db.Model):
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    comment_id = db.Column(db.Integer, db.ForeignKey("comments.id", ondelete="SET NULL"))
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    filename = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(80), nullable=False, unique=True)
    content_type = db.Column(db.String(120))
    size = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="attachments")
    comment = db.relationship("Comment", back_populates="attachments")
    uploaded_by = db.relationship("User")

    @property
    def is_internal(self) -> bool:
        return bool(self.comment and self.comment.internal)


class TicketEvent(db.Model):
    __tablename__ = "ticket_events"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(40), nullable=False)
    field = db.Column(db.String(40))
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="events")
    user = db.relationship("User")


class SLAPolicy(db.Model):
    __tablename__ = "sla_policies"

    priority = db.Column(db.Integer, primary_key=True)
    response_minutes = db.Column(db.Integer, nullable=False)
    resolution_minutes = db.Column(db.Integer, nullable=False)


class Setting(db.Model):
    __tablename__ = "settings"

    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")


class KBArticle(db.Model):
    __tablename__ = "kb_articles"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.String(300))
    body = db.Column(db.Text, nullable=False, default="")
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"))
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    published = db.Column(db.Boolean, nullable=False, default=False)
    internal = db.Column(db.Boolean, nullable=False, default=False)
    views = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    category = db.relationship("Category")
    author = db.relationship("User")


class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    type = db.Column(db.String(40), nullable=False, default="Desktop")
    status = db.Column(db.String(20), nullable=False, default="in_use")
    manufacturer = db.Column(db.String(120))
    model = db.Column(db.String(120))
    serial = db.Column(db.String(120))
    location = db.Column(db.String(120))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    purchase_date = db.Column(db.Date)
    warranty_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    assigned_to = db.relationship("User")
    tickets = db.relationship("Ticket", back_populates="asset", order_by="Ticket.created_at.desc()")

    @property
    def status_label(self) -> str:
        return ASSET_STATUSES.get(self.status, self.status)

    @property
    def display(self) -> str:
        return f"{self.tag} — {self.name}"
