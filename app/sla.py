from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .extensions import db
from .models import SLAPolicy

DEFAULT_POLICIES = {
    # prioridade: (resposta, solução) em minutos
    1: (30, 4 * 60),
    2: (60, 8 * 60),
    3: (4 * 60, 24 * 60),
    4: (8 * 60, 48 * 60),
}

# Limite de dias percorridos na busca por horário útil (evita laço infinito
# caso a configuração não tenha nenhum dia útil).
_MAX_DAYS = 3660


@dataclass
class Schedule:
    enabled: bool = True
    days: frozenset = frozenset({0, 1, 2, 3, 4})
    start: time = time(8, 0)
    end: time = time(18, 0)
    tz: str = "America/Sao_Paulo"

    @property
    def zone(self):
        try:
            return ZoneInfo(self.tz)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.days) and self.end > self.start


def _parse_time(value: str, default: time) -> time:
    try:
        hours, minutes = str(value).split(":", 1)
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return default


def current_schedule() -> Schedule:
    from .settings import get_bool, get_setting

    days = set()
    for part in str(get_setting("business_days")).split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 6:
            days.add(int(part))
    return Schedule(
        enabled=get_bool("business_hours_enabled"),
        days=frozenset(days),
        start=_parse_time(get_setting("business_start"), time(8, 0)),
        end=_parse_time(get_setting("business_end"), time(18, 0)),
        tz=get_setting("timezone") or "UTC",
    )


def _to_local(dt: datetime, zone) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(zone)


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _window(day: datetime, schedule: Schedule):
    start = day.replace(hour=schedule.start.hour, minute=schedule.start.minute, second=0, microsecond=0)
    end = day.replace(hour=schedule.end.hour, minute=schedule.end.minute, second=0, microsecond=0)
    return start, end


def _next_day(day: datetime) -> datetime:
    return (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def add_business_minutes(start: datetime, minutes: int, schedule: Schedule) -> datetime:
    """Soma `minutes` minutos úteis a `start` (UTC naive) e devolve UTC naive."""
    if not schedule.usable:
        return start + timedelta(minutes=minutes)
    cur = _to_local(start, schedule.zone)
    remaining = timedelta(minutes=max(0, minutes))
    for _ in range(_MAX_DAYS):
        if cur.weekday() in schedule.days:
            win_start, win_end = _window(cur, schedule)
            if cur < win_start:
                cur = win_start
            if cur < win_end:
                available = win_end - cur
                if remaining <= available:
                    return _to_utc(cur + remaining)
                remaining -= available
        cur = _next_day(cur)
    return start + timedelta(minutes=minutes)


def business_minutes_between(a: datetime, b: datetime, schedule: Schedule) -> int:
    if b <= a:
        return 0
    if not schedule.usable:
        return int((b - a).total_seconds() // 60)
    zone = schedule.zone
    cur = _to_local(a, zone)
    end = _to_local(b, zone)
    total = timedelta()
    for _ in range(_MAX_DAYS):
        if cur >= end:
            break
        if cur.weekday() in schedule.days:
            win_start, win_end = _window(cur, schedule)
            lo = max(cur, win_start)
            hi = min(end, win_end)
            if hi > lo:
                total += hi - lo
        cur = _next_day(cur)
    return int(total.total_seconds() // 60)


def get_policy(priority: int):
    policy = db.session.get(SLAPolicy, priority)
    if policy:
        return policy.response_minutes, policy.resolution_minutes
    return DEFAULT_POLICIES.get(priority, DEFAULT_POLICIES[4])


def apply_sla(ticket, start: datetime | None = None) -> None:
    schedule = current_schedule()
    start = start or ticket.created_at
    response, resolution = get_policy(ticket.priority)
    ticket.response_due = add_business_minutes(start, response, schedule)
    ticket.resolution_due = add_business_minutes(
        start, resolution + (ticket.sla_paused_minutes or 0), schedule
    )


def pause(ticket, now: datetime) -> None:
    if ticket.sla_paused_at is None:
        ticket.sla_paused_at = now


def resume(ticket, now: datetime) -> None:
    """Retoma o SLA empurrando o prazo de solução pelo tempo útil em pausa."""
    if ticket.sla_paused_at is None:
        return
    schedule = current_schedule()
    paused = business_minutes_between(ticket.sla_paused_at, now, schedule)
    ticket.sla_paused_minutes = (ticket.sla_paused_minutes or 0) + paused
    if ticket.resolution_due and paused:
        ticket.resolution_due = add_business_minutes(ticket.resolution_due, paused, schedule)
    ticket.sla_paused_at = None


def ensure_policies() -> None:
    for priority, (response, resolution) in DEFAULT_POLICIES.items():
        if db.session.get(SLAPolicy, priority) is None:
            db.session.add(
                SLAPolicy(priority=priority, response_minutes=response, resolution_minutes=resolution)
            )
