import re
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import abort
from flask_login import current_user, login_required
from markupsafe import Markup, escape

from .models import utcnow
from .settings import get_setting


def agent_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_agent:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


def local_zone():
    try:
        return ZoneInfo(get_setting("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_local(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(local_zone())


def fmt_datetime(value, fmt="%d/%m/%Y %H:%M") -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return to_local(value).strftime(fmt)
    return value.strftime("%d/%m/%Y")


def fmt_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        value = to_local(value)
    return value.strftime("%d/%m/%Y")


def fmt_duration(minutes) -> str:
    if minutes is None:
        return "—"
    minutes = int(abs(minutes))
    days, rest = divmod(minutes, 60 * 24)
    hours, mins = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins and not days:
        parts.append(f"{mins}min")
    return " ".join(parts) or "0min"


def time_ago(value) -> str:
    if not value:
        return "—"
    delta = utcnow() - value
    seconds = int(delta.total_seconds())
    future = seconds < 0
    minutes = abs(seconds) // 60
    if minutes < 1:
        return "agora"
    text = fmt_duration(minutes)
    return f"em {text}" if future else f"há {text}"


def time_left(value) -> str:
    if not value:
        return "—"
    minutes = int((value - utcnow()).total_seconds() // 60)
    if minutes >= 0:
        return f"restam {fmt_duration(minutes)}"
    return f"vencido há {fmt_duration(-minutes)}"


def fmt_size(num) -> str:
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


_URL_RE = re.compile(r"(https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]])")


def _autolink(escaped: str) -> str:
    return _URL_RE.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', escaped)


def nl2br(text) -> Markup:
    if not text:
        return Markup("")
    escaped = str(escape(text))
    return Markup(_autolink(escaped).replace("\r\n", "\n").replace("\n", "<br>\n"))


def _inline(text: str) -> str:
    """Formatação inline sobre texto JÁ escapado."""
    codes = []

    def keep_code(match):
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep_code, text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)
    return text


def markdown(text) -> Markup:
    """Markdown simplificado e seguro (títulos, listas, negrito, código, links).

    Todo o conteúdo é escapado antes da formatação, então não há como injetar HTML.
    """
    if not text:
        return Markup("")
    lines = str(escape(text)).replace("\r\n", "\n").split("\n")
    html, paragraph, list_type, in_code, code = [], [], None, False, []

    def flush_paragraph():
        if paragraph:
            html.append("<p>" + "<br>".join(_inline(p) for p in paragraph) + "</p>")
            paragraph.clear()

    def close_list():
        nonlocal list_type
        if list_type:
            html.append(f"</{list_type}>")
            list_type = None

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                html.append("<pre><code>" + "\n".join(code) + "</code></pre>")
                code.clear()
                in_code = False
            else:
                flush_paragraph()
                close_list()
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        stripped = line.strip()
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if not stripped:
            flush_paragraph()
            close_list()
        elif heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1)) + 1
            html.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif bullet or numbered:
            flush_paragraph()
            wanted = "ul" if bullet else "ol"
            if list_type != wanted:
                close_list()
                html.append(f"<{wanted}>")
                list_type = wanted
            html.append(f"<li>{_inline((bullet or numbered).group(1))}</li>")
        elif stripped.startswith("&gt;"):
            flush_paragraph()
            close_list()
            html.append(f"<blockquote>{_inline(stripped[4:].strip())}</blockquote>")
        else:
            close_list()
            paragraph.append(stripped)
    if in_code:
        html.append("<pre><code>" + "\n".join(code) + "</code></pre>")
    flush_paragraph()
    close_list()
    return Markup("\n".join(html))


def register_filters(app) -> None:
    app.jinja_env.filters.update(
        dt=fmt_datetime,
        date=fmt_date,
        ago=time_ago,
        left=time_left,
        duration=fmt_duration,
        filesize=fmt_size,
        nl2br=nl2br,
        markdown=markdown,
    )
