"""iCalendar (RFC 5545) export so students can subscribe to their cohort's events."""

from __future__ import annotations

from datetime import datetime

from .models import Event, utcnow

TIMEZONE = "America/Los_Angeles"

# Minimal VTIMEZONE for Pacific time so calendar apps do not treat times as UTC.
_VTIMEZONE = [
    "BEGIN:VTIMEZONE", f"TZID:{TIMEZONE}",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0800", "TZOFFSETTO:-0700", "TZNAME:PDT",
    "DTSTART:19700308T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:-0700", "TZOFFSETTO:-0800", "TZNAME:PST",
    "DTSTART:19701101T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
    "END:VTIMEZONE",
]


def escape(text: str) -> str:
    """Escape TEXT values per RFC 5545 section 3.3.11."""
    out = text.replace("\\", "\\\\")
    for ch in ";,":
        out = out.replace(ch, "\\" + ch)
    return out.replace("\r\n", "\\n").replace("\n", "\\n")


def fold(line: str, limit: int = 75) -> str:
    """Fold a content line at ``limit`` octets with CRLF + space continuations."""
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return line
    chunks: list[str] = []
    current = b""
    for ch in line:
        enc = ch.encode("utf-8")
        max_len = limit if not chunks else limit - 1  # continuation lines start with a space
        if len(current) + len(enc) > max_len:
            chunks.append(current.decode("utf-8"))
            current = b""
        current += enc
    chunks.append(current.decode("utf-8"))
    return "\r\n ".join(chunks)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def to_ics(events: list[Event], calname: str, stamp: datetime | None = None) -> str:
    stamp = stamp or utcnow()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ACE Cohort Event Planner//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{escape(calname)}",
             f"X-WR-TIMEZONE:{TIMEZONE}", *_VTIMEZONE]
    for ev in sorted(events, key=lambda e: e.start):
        lines += ["BEGIN:VEVENT", f"UID:ace-event-{ev.id}@ace-planner",
                  f"DTSTAMP:{stamp.strftime('%Y%m%dT%H%M%SZ')}",
                  f"DTSTART;TZID={TIMEZONE}:{_fmt(ev.start)}",
                  f"DTEND;TZID={TIMEZONE}:{_fmt(ev.end)}",
                  f"SUMMARY:{escape(ev.title)}",
                  f"CATEGORIES:{escape(ev.type_label)}"]
        if ev.room:
            lines.append(f"LOCATION:{escape(ev.room.name)}")
        if ev.description:
            lines.append(f"DESCRIPTION:{escape(ev.description)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
