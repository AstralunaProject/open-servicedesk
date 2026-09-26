import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import current_app, has_request_context, request

from .constants import ROLE_ADMIN, ROLE_AGENT, STATUS_RESOLVED, STATUS_WAITING_USER
from .extensions import db
from .models import User
from .settings import get_bool, get_setting

log = logging.getLogger(__name__)


def smtp_config() -> dict:
    return {
        "host": get_setting("smtp_host").strip(),
        "port": int(get_setting("smtp_port") or 587),
        "security": get_setting("smtp_security") or "starttls",
        "user": get_setting("smtp_user"),
        "password": get_setting("smtp_password"),
        "from": get_setting("smtp_from") or get_setting("smtp_user"),
        "from_name": get_setting("app_title"),
    }


def notifications_enabled() -> bool:
    return get_bool("notify_enabled") and bool(get_setting("smtp_host").strip())


def build_message(cfg: dict, recipients, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["from_name"], cfg["from"]))
    msg["To"] = ", ".join(recipients)
    domain = cfg["from"].split("@")[-1] if "@" in cfg["from"] else None
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    return msg


def deliver(cfg: dict, msg: EmailMessage) -> None:
    """Entrega síncrona; levanta exceção em caso de erro."""
    context = ssl.create_default_context()
    if cfg["security"] == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20, context=context)
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)
    with server:
        if cfg["security"] == "starttls":
            server.starttls(context=context)
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.send_message(msg)


def _deliver_in_background(cfg, msg):
    try:
        deliver(cfg, msg)
    except (smtplib.SMTPException, OSError):
        log.exception("Falha ao enviar e-mail '%s'", msg["Subject"])


def send_mail(recipients, subject: str, body: str) -> None:
    recipients = sorted({r.strip().lower() for r in recipients if r and "@" in r})
    if not recipients or not notifications_enabled():
        return
    cfg = smtp_config()
    msg = build_message(cfg, recipients, subject, body)
    if current_app.config.get("TESTING") or current_app.config.get("MAIL_SUPPRESS"):
        current_app.extensions.setdefault("outbox", []).append(msg)
        return
    threading.Thread(target=_deliver_in_background, args=(cfg, msg), daemon=True).start()


def base_url() -> str:
    configured = current_app.config.get("BASE_URL")
    if configured:
        return configured
    if has_request_context():
        return request.url_root.rstrip("/")
    return "http://localhost:8080"


def ticket_url(ticket) -> str:
    return f"{base_url()}/chamados/{ticket.id}"


def _subject(ticket, text: str) -> str:
    # O número entre colchetes permite que respostas por e-mail voltem ao chamado.
    return f"[{ticket.number}] {text}: {ticket.title}"


def _footer(ticket) -> str:
    return (
        f"\n\nAcompanhe o chamado: {ticket_url(ticket)}\n"
        f"Para responder, basta responder este e-mail mantendo [{ticket.number}] no assunto.\n"
        f"— {get_setting('app_title')} · {get_setting('company_name')}"
    )


def _agents_for(ticket) -> list:
    if ticket.group:
        emails = [m.email for m in ticket.group.members if m.active]
        if ticket.group.email:
            emails.append(ticket.group.email)
        if emails:
            return emails
    agents = db.session.scalars(
        db.select(User).where(User.role.in_([ROLE_ADMIN, ROLE_AGENT]), User.active.is_(True))
    )
    return [a.email for a in agents]


def ticket_created(ticket) -> None:
    requester = ticket.requester
    send_mail(
        [requester.email],
        _subject(ticket, "Chamado aberto"),
        f"Olá, {requester.name}.\n\n"
        f"Recebemos seu chamado {ticket.number} e ele já está na fila de atendimento.\n\n"
        f"Assunto: {ticket.title}\nPrioridade: {ticket.priority_label}\n"
        f"Descrição:\n{ticket.description}" + _footer(ticket),
    )
    recipients = [ticket.assignee.email] if ticket.assignee else _agents_for(ticket)
    recipients = [r for r in recipients if r != requester.email]
    send_mail(
        recipients,
        _subject(ticket, f"Novo chamado ({ticket.priority_label})"),
        f"Novo chamado aberto por {requester.name} ({requester.email}).\n\n"
        f"Tipo: {ticket.type_label}\nCategoria: {ticket.category.name if ticket.category else '-'}\n"
        f"Grupo: {ticket.group.name if ticket.group else '-'}\nPrioridade: {ticket.priority_label}\n\n"
        f"{ticket.description}" + _footer(ticket),
    )


def comment_added(ticket, comment) -> None:
    author = comment.author
    if comment.internal:
        if ticket.assignee and (not author or ticket.assignee_id != author.id):
            send_mail(
                [ticket.assignee.email],
                _subject(ticket, "Nova nota interna"),
                f"{author.name if author else 'Sistema'} adicionou uma nota interna:\n\n{comment.body}"
                + _footer(ticket),
            )
        return
    if author and author.id == ticket.requester_id:
        recipients = [ticket.assignee.email] if ticket.assignee else _agents_for(ticket)
        send_mail(
            [r for r in recipients if r != author.email],
            _subject(ticket, "Resposta do solicitante"),
            f"{author.name} respondeu:\n\n{comment.body}" + _footer(ticket),
        )
    else:
        send_mail(
            [ticket.requester.email],
            _subject(ticket, "Nova resposta"),
            f"Olá, {ticket.requester.name}.\n\n"
            f"{author.name if author else 'A equipe de T.I'} respondeu seu chamado:\n\n{comment.body}"
            + _footer(ticket),
        )


def ticket_assigned(ticket, actor) -> None:
    if not ticket.assignee or (actor and ticket.assignee_id == actor.id):
        return
    send_mail(
        [ticket.assignee.email],
        _subject(ticket, "Chamado atribuído a você"),
        f"O chamado {ticket.number} foi atribuído a você"
        f"{' por ' + actor.name if actor else ''}.\n\nPrioridade: {ticket.priority_label}\n"
        f"Solicitante: {ticket.requester.name}\n\n{ticket.description}" + _footer(ticket),
    )


def status_changed(ticket, old_status, actor) -> None:
    if actor and actor.id == ticket.requester_id:
        return
    if ticket.status == STATUS_RESOLVED:
        send_mail(
            [ticket.requester.email],
            _subject(ticket, "Chamado resolvido"),
            f"Olá, {ticket.requester.name}.\n\nSeu chamado {ticket.number} foi marcado como resolvido.\n\n"
            f"Solução:\n{ticket.resolution_notes or '-'}\n\n"
            f"Se o problema continuar, você pode reabrir o chamado pelo portal ou respondendo este e-mail. "
            f"Aproveite para avaliar o atendimento!" + _footer(ticket),
        )
    elif ticket.status == STATUS_WAITING_USER:
        send_mail(
            [ticket.requester.email],
            _subject(ticket, "Aguardando seu retorno"),
            f"Olá, {ticket.requester.name}.\n\nA equipe de T.I precisa do seu retorno para continuar o "
            f"atendimento do chamado {ticket.number}." + _footer(ticket),
        )


def password_reset(user, link: str) -> None:
    send_mail(
        [user.email],
        "Redefinição de senha",
        f"Olá, {user.name}.\n\nRecebemos um pedido para redefinir sua senha. Acesse o link abaixo "
        f"(válido por 1 hora):\n\n{link}\n\nSe você não fez esse pedido, ignore este e-mail.\n\n"
        f"— {get_setting('app_title')}",
    )
