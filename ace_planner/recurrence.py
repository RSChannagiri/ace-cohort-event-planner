"""Minimal RRULE-style recurrence expansion.

Supported parts (a practical subset of RFC 5545):

* ``FREQ``: DAILY, WEEKLY or MONTHLY
* ``INTERVAL``: positive integer, default 1
* ``BYDAY``: weekday codes (``MO,WE``) for WEEKLY; for MONTHLY a single
  ordinal weekday such as ``1TH`` (first Thursday) or ``-1FR`` (last Friday)
* ``COUNT`` or ``UNTIL`` (YYYYMMDD, inclusive). One of them is required so a
  series can never grow without bound.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

DAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
MAX_OCCURRENCES = 500
_ORDINAL_DAY = re.compile(r"^([+-]?[1-5])?(MO|TU|WE|TH|FR|SA|SU)$")


class RecurrenceError(ValueError):
    """Raised when a recurrence rule is malformed or unsupported."""


def parse_rrule(rule: str) -> dict[str, str]:
    """Parse and validate a rule string into an upper-cased ``{PART: value}`` dict."""
    if not rule or not rule.strip():
        raise RecurrenceError("Rule is empty")
    parts: dict[str, str] = {}
    for chunk in rule.strip().removeprefix("RRULE:").split(";"):
        if not chunk.strip():
            continue
        if "=" not in chunk:
            raise RecurrenceError(f"Malformed rule part: {chunk!r}")
        key, value = chunk.split("=", 1)
        parts[key.strip().upper()] = value.strip().upper()

    freq = parts.get("FREQ")
    if freq not in ("DAILY", "WEEKLY", "MONTHLY"):
        raise RecurrenceError("FREQ must be DAILY, WEEKLY or MONTHLY")
    if "COUNT" not in parts and "UNTIL" not in parts:
        raise RecurrenceError("Rule must be bounded by COUNT or UNTIL")
    if "COUNT" in parts and "UNTIL" in parts:
        raise RecurrenceError("Use COUNT or UNTIL, not both")

    for key in ("INTERVAL", "COUNT"):
        if key in parts:
            if not parts[key].isdigit() or int(parts[key]) < 1:
                raise RecurrenceError(f"{key} must be a positive integer")
    if "COUNT" in parts and int(parts["COUNT"]) > MAX_OCCURRENCES:
        raise RecurrenceError(f"COUNT cannot exceed {MAX_OCCURRENCES}")

    if "BYDAY" in parts:
        _parse_byday(parts["BYDAY"], freq)
    if "UNTIL" in parts:
        _parse_until(parts["UNTIL"])
    return parts


def _parse_byday(value: str, freq: str) -> list[tuple[int | None, int]]:
    """Return ``(ordinal, weekday_index)`` pairs."""
    out: list[tuple[int | None, int]] = []
    for token in value.split(","):
        match = _ORDINAL_DAY.match(token.strip())
        if not match:
            raise RecurrenceError(f"Unknown BYDAY value: {token}")
        ordinal = int(match.group(1)) if match.group(1) else None
        if freq == "WEEKLY" and ordinal is not None:
            raise RecurrenceError("WEEKLY BYDAY values cannot have an ordinal")
        out.append((ordinal, DAY_CODES.index(match.group(2))))
    if freq == "MONTHLY" and (len(out) != 1 or out[0][0] is None):
        raise RecurrenceError("MONTHLY BYDAY must be one ordinal weekday, e.g. 1TH")
    if freq == "DAILY":
        raise RecurrenceError("BYDAY is not supported with FREQ=DAILY")
    return out


def _parse_until(value: str) -> date:
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError as exc:
        raise RecurrenceError("UNTIL must be YYYYMMDD") from exc


def nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date | None:
    """The ``ordinal``-th ``weekday`` of a month (negative counts from the end)."""
    days = [d for d in calendar.Calendar().itermonthdates(year, month)
            if d.month == month and d.weekday() == weekday]
    index = ordinal - 1 if ordinal > 0 else ordinal
    try:
        return days[index]
    except IndexError:
        return None  # e.g. a 5th Monday that does not exist this month


def _month_offset(start: datetime, months: int) -> tuple[int, int]:
    idx = start.year * 12 + start.month - 1 + months
    return idx // 12, idx % 12 + 1


def _candidates(start: datetime, parts: dict[str, str]):
    """Yield candidate datetimes in chronological order (unbounded)."""
    freq = parts["FREQ"]
    interval = int(parts.get("INTERVAL", "1"))
    step = 0
    while True:
        if freq == "DAILY":
            yield start + timedelta(days=step * interval)
        elif freq == "WEEKLY":
            week_start = start - timedelta(days=start.weekday()) + timedelta(weeks=step * interval)
            byday = _parse_byday(parts["BYDAY"], freq) if "BYDAY" in parts else [
                (None, start.weekday())]
            for idx in sorted({wd for _, wd in byday}):
                yield week_start + timedelta(days=idx)
        else:
            year, month = _month_offset(start, step * interval)
            if "BYDAY" in parts:
                ordinal, weekday = _parse_byday(parts["BYDAY"], freq)[0]
                assert ordinal is not None
                day = nth_weekday(year, month, weekday, ordinal)
            else:
                try:
                    day = date(year, month, start.day)
                except ValueError:
                    day = None  # Jan 31 -> no Feb 31, skipped like RFC 5545
            if day is not None:
                yield datetime.combine(day, start.time())
        step += 1


def expand(start: datetime, rule: str, exdates: set[date] | None = None) -> list[datetime]:
    """Return occurrence start datetimes for ``rule`` beginning at ``start``.

    Occurrences before ``start`` are dropped. Dates in ``exdates`` (holidays,
    finals week) are skipped but still count toward ``COUNT`` as in RFC 5545.
    """
    parts = parse_rrule(rule)
    count = int(parts["COUNT"]) if "COUNT" in parts else None
    until = _parse_until(parts["UNTIL"]) if "UNTIL" in parts else None
    exdates = exdates or set()
    out: list[datetime] = []
    produced = 0
    for dt in _candidates(start, parts):
        if dt < start:
            continue
        if until and dt.date() > until:
            break
        produced += 1
        if dt.date() not in exdates:
            out.append(dt)
        if (count and produced >= count) or produced >= MAX_OCCURRENCES:
            break
    return out


def describe(rule: str) -> str:
    """Human-readable summary, e.g. 'Weekly on TU until 2026-12-08'."""
    parts = parse_rrule(rule)
    interval = int(parts.get("INTERVAL", "1"))
    unit = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month"}[parts["FREQ"]]
    text = f"Every {interval} {unit}s" if interval > 1 else parts["FREQ"].title()
    if "BYDAY" in parts:
        text += f" on {parts['BYDAY']}"
    if "COUNT" in parts:
        text += f", {parts['COUNT']} times"
    else:
        until = _parse_until(parts["UNTIL"])
        text += f" until {until.isoformat()}"
    return text
