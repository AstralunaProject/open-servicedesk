from datetime import datetime, time

from app.constants import calc_priority
from app.sla import Schedule, add_business_minutes, business_minutes_between

# Horário comercial em UTC para facilitar as contas: seg-sex, 08h-18h.
SCHEDULE = Schedule(enabled=True, days=frozenset({0, 1, 2, 3, 4}), start=time(8), end=time(18), tz="UTC")


def test_priority_matrix():
    assert calc_priority(1, 1) == 1
    assert calc_priority(1, 2) == 2
    assert calc_priority(2, 2) == 3
    assert calc_priority(3, 1) == 3
    assert calc_priority(3, 3) == 4


def test_add_minutes_within_same_day():
    start = datetime(2026, 9, 21, 9, 0)  # segunda
    assert add_business_minutes(start, 120, SCHEDULE) == datetime(2026, 9, 21, 11, 0)


def test_add_minutes_rolls_over_night():
    start = datetime(2026, 9, 21, 17, 0)
    assert add_business_minutes(start, 120, SCHEDULE) == datetime(2026, 9, 22, 9, 0)


def test_add_minutes_skips_weekend():
    start = datetime(2026, 9, 25, 17, 30)  # sexta
    assert add_business_minutes(start, 60, SCHEDULE) == datetime(2026, 9, 28, 8, 30)


def test_ticket_opened_at_night_starts_counting_next_morning():
    start = datetime(2026, 9, 21, 22, 0)
    assert add_business_minutes(start, 30, SCHEDULE) == datetime(2026, 9, 22, 8, 30)


def test_business_minutes_between_ignores_off_hours():
    friday = datetime(2026, 9, 25, 17, 0)
    monday = datetime(2026, 9, 28, 9, 0)
    assert business_minutes_between(friday, monday, SCHEDULE) == 120


def test_disabled_schedule_is_24x7():
    schedule = Schedule(enabled=False)
    start = datetime(2026, 9, 26, 23, 0)
    assert add_business_minutes(start, 60, schedule) == datetime(2026, 9, 27, 0, 0)
    assert business_minutes_between(start, datetime(2026, 9, 27, 1, 0), schedule) == 120


def test_sao_paulo_timezone_is_respected():
    schedule = Schedule(tz="America/Sao_Paulo")
    start = datetime(2026, 9, 21, 20, 30)  # 17h30 em São Paulo
    assert add_business_minutes(start, 60, schedule) == datetime(2026, 9, 22, 11, 30)
