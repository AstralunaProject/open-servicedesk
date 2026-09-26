from flask import g, has_app_context

from .extensions import db
from .models import Setting

DEFAULTS = {
    "company_name": "Minha Empresa",
    "app_title": "Central de Serviços de T.I",
    "ticket_prefix": "CH",
    "timezone": "America/Sao_Paulo",
    "allow_registration": "0",
    "registration_domains": "",
    "reopen_days": "7",
    "auto_close_days": "5",
    "requester_can_set_priority": "1",
    "business_hours_enabled": "1",
    "business_days": "0,1,2,3,4",
    "business_start": "08:00",
    "business_end": "18:00",
    "notify_enabled": "0",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_security": "starttls",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "imap_enabled": "0",
    "imap_host": "",
    "imap_port": "993",
    "imap_user": "",
    "imap_password": "",
    "imap_folder": "INBOX",
    "imap_interval": "5",
    "imap_create_users": "1",
}


def _cache() -> dict:
    if not has_app_context():
        return {}
    if "_settings" not in g:
        g._settings = {s.key: s.value for s in db.session.scalars(db.select(Setting))}
    return g._settings


def get_setting(key: str, default=None) -> str:
    value = _cache().get(key)
    if value is None:
        value = DEFAULTS.get(key, default)
    return value if value is not None else ""


def get_bool(key: str) -> bool:
    return str(get_setting(key)).strip() in ("1", "true", "on", "sim")


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(str(get_setting(key)).strip())
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value) -> None:
    value = "" if value is None else str(value)
    row = db.session.get(Setting, key)
    if row is None:
        db.session.add(Setting(key=key, value=value))
    else:
        row.value = value
    if has_app_context() and "_settings" in g:
        g._settings[key] = value


def all_settings() -> dict:
    data = dict(DEFAULTS)
    data.update(_cache())
    return data
