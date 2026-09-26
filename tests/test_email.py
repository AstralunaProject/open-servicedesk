from email.message import EmailMessage

from app import mail_inbound
from app.constants import STATUS_WAITING_USER
from app.extensions import db
from app.models import Ticket, User
from app.settings import set_setting


def raw_email(sender, subject, body, **headers):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "suporte@empresa.com"
    msg["Subject"] = subject
    for key, value in headers.items():
        msg[key.replace("_", "-")] = value
    msg.set_content(body)
    msg.add_attachment(b"log", maintype="text", subtype="plain", filename="log.txt")
    return msg.as_bytes()


def test_new_email_creates_ticket_and_user(app, admin):
    ticket = mail_inbound.process_message(
        raw_email("Carlos <carlos@cliente.com>", "PC não liga", "Apertei o botão")
    )
    assert ticket.channel == "email"
    assert ticket.title == "PC não liga"
    assert ticket.requester.email == "carlos@cliente.com"
    assert ticket.attachments[0].filename == "log.txt"


def test_unknown_sender_ignored_when_auto_create_disabled(app, admin):
    set_setting("imap_create_users", "0")
    db.session.commit()
    assert mail_inbound.process_message(raw_email("x@y.com", "oi", "oi")) is None
    assert db.session.scalar(db.select(User).where(User.email == "x@y.com")) is None


def test_reply_with_number_becomes_comment(app, admin):
    ticket = mail_inbound.process_message(raw_email("ana@cliente.com", "Sem acesso", "Não entra"))
    ticket.status = STATUS_WAITING_USER
    db.session.commit()
    body = "Agora funcionou!\n\nEm 20/09/2026 10:00, Suporte escreveu:\n> Tente de novo"
    same = mail_inbound.process_message(
        raw_email("ana@cliente.com", f"RE: [{ticket.number}] Sem acesso", body)
    )
    assert same.id == ticket.id
    assert ticket.comments[-1].body == "Agora funcionou!"
    assert ticket.status == "in_progress"
    assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 1


def test_reply_from_stranger_opens_new_ticket(app, admin):
    ticket = mail_inbound.process_message(raw_email("ana@cliente.com", "Sem acesso", "Não entra"))
    other = mail_inbound.process_message(
        raw_email("bob@cliente.com", f"[{ticket.number}] Sem acesso", "eu também")
    )
    assert other.id != ticket.id
    assert other.title == "Sem acesso"


def test_auto_replies_are_ignored(app, admin):
    message = raw_email(
        "ana@cliente.com", "Fora do escritório", "Volto dia 10", Auto_Submitted="auto-replied"
    )
    assert mail_inbound.process_message(message) is None


def test_notifications_are_sent_when_enabled(app, requester, agent):
    from app import services

    set_setting("notify_enabled", "1")
    set_setting("smtp_host", "smtp.test")
    set_setting("smtp_from", "suporte@empresa.com")
    db.session.commit()
    ticket = services.create_ticket(requester, "Teste", "desc")
    outbox = app.extensions["outbox"]
    subjects = [m["Subject"] for m in outbox]
    assert any(ticket.number in s and "Chamado aberto" in s for s in subjects)
    assert any(agent.email in m["To"] for m in outbox)
