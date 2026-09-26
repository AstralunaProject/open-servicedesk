"""Abertura de chamados por e-mail (caixa IMAP).

- E-mail novo → novo chamado (canal "E-mail").
- Resposta com [PREFIXO000123] no assunto → comentário no chamado existente.
"""

import contextlib
import email
import html
import imaplib
import io
import logging
import re
import secrets
from email import policy
from email.utils import parseaddr

from werkzeug.datastructures import FileStorage

from . import services
from .constants import ROLE_USER, STATUS_CANCELLED, STATUS_CLOSED
from .extensions import db
from .models import Ticket, User
from .settings import get_bool, get_setting

log = logging.getLogger(__name__)

_REPLY_MARKERS = [
    re.compile(r"^\s*Em .{5,200} escreveu:\s*$", re.I),
    re.compile(r"^\s*On .{5,200} wrote:\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*(Original Message|Mensagem original)\s*-{2,}", re.I),
    re.compile(r"^\s*(De|From):\s.+", re.I),
    re.compile(r"^_{10,}\s*$"),
]


def strip_reply(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if any(p.match(line) for p in _REPLY_MARKERS):
            break
        if line.startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|head).*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _body(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        content = part.get_payload(decode=True).decode("utf-8", "replace")
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return content.strip()


def _attachments(msg) -> list:
    files = []
    for part in msg.iter_attachments():
        filename = part.get_filename()
        if not filename:
            continue
        data = part.get_payload(decode=True) or b""
        files.append(
            FileStorage(stream=io.BytesIO(data), filename=filename, content_type=part.get_content_type())
        )
    return files


def _find_or_create_user(address: str, name: str):
    user = db.session.scalar(db.select(User).where(db.func.lower(User.email) == address.lower()))
    if user or not get_bool("imap_create_users"):
        return user
    user = User(name=name or address.split("@")[0], email=address.lower(), role=ROLE_USER)
    user.set_password(secrets.token_urlsafe(24))  # usuário pode usar "Esqueci minha senha"
    db.session.add(user)
    db.session.flush()
    return user


def process_message(raw: bytes):
    """Processa um e-mail bruto. Retorna o chamado criado/atualizado ou None."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    if (msg.get("Auto-Submitted") or "no").lower() != "no":
        return None  # ignora respostas automáticas (férias, bounces) para evitar loops
    name, address = parseaddr(str(msg.get("From", "")))
    if not address or "@" not in address:
        return None
    own = (get_setting("smtp_from") or "").lower(), (get_setting("imap_user") or "").lower()
    if address.lower() in own:
        return None

    subject = str(msg.get("Subject", "")).strip() or "(sem assunto)"
    body = _body(msg)
    files = _attachments(msg)
    user = _find_or_create_user(address, name)
    if user is None or not user.active:
        log.info("E-mail ignorado de remetente desconhecido/inativo: %s", address)
        return None

    prefix = re.escape(get_setting("ticket_prefix"))
    match = re.search(rf"\[{prefix}(\d+)\]", subject)
    ticket = db.session.get(Ticket, int(match.group(1))) if match else None
    if ticket and not services.can_view(user, ticket):
        ticket = None
    if ticket and ticket.status not in (STATUS_CLOSED, STATUS_CANCELLED):
        services.add_comment(ticket, user, strip_reply(body) or "(sem texto)", files=files)
        return ticket

    description = body
    if match:
        subject = re.sub(rf"\[{prefix}\d+\]\s*", "", subject)
    if ticket:
        description = f"Referente ao chamado encerrado {ticket.number}.\n\n{body}"
    subject = re.sub(r"^\s*((re|res|fw|fwd|enc)\s*:\s*)+", "", subject, flags=re.I) or "(sem assunto)"
    return services.create_ticket(user, subject, description, channel="email", files=files)


def poll_mailbox() -> int:
    host = get_setting("imap_host").strip()
    if not get_bool("imap_enabled") or not host:
        return 0
    port = int(get_setting("imap_port") or 993)
    conn = imaplib.IMAP4_SSL(host, port) if port == 993 else imaplib.IMAP4(host, port)
    processed = 0
    try:
        if port != 993:
            conn.starttls()
        conn.login(get_setting("imap_user"), get_setting("imap_password"))
        conn.select(get_setting("imap_folder") or "INBOX")
        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            return 0
        for num in data[0].split():
            status, parts = conn.fetch(num, "(RFC822)")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            try:
                process_message(parts[0][1])
                processed += 1
            except Exception:
                # Um e-mail malformado não pode impedir a leitura dos demais; ele fica
                # marcado como lido e o erro completo vai para o log.
                db.session.rollback()
                log.exception("Erro ao processar e-mail %s", num)
    finally:
        # O LOGOUT pode falhar se o servidor já derrubou a conexão; o que foi
        # processado até aqui já está gravado.
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            conn.logout()
    return processed
