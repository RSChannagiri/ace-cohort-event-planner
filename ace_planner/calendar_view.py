"""Month-grid construction for the calendar page."""

from __future__ import annotations

import calendar
from datetime import date, datetime

from .models import Event


def month_grid(year: int, month: int, events: list[Event]) -> list[list[dict]]:
    """Weeks (Mon-Sun) of day cells: {'date', 'in_month', 'events'}."""
    by_day: dict[date, list[Event]] = {}
    for ev in sorted(events, key=lambda e: e.start):
        by_day.setdefault(ev.start.date(), []).append(ev)
    cal = calendar.Calendar(firstweekday=0)
    return [[{"date": d, "in_month": d.month == month, "events": by_day.get(d, [])}
             for d in week] for week in cal.monthdatescalendar(year, month)]


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), month % 12 + 1, 1)
    return start, end


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def months_between(start: date, end: date) -> list[tuple[int, int]]:
    """Every (year, month) from ``start`` through ``end`` inclusive."""
    if end < start:
        return []
    out = [(start.year, start.month)]
    while out[-1] != (end.year, end.month):
        out.append(shift_month(*out[-1], 1))
    return out
