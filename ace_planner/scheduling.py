"""Event creation, validation, and room/time conflict detection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .models import EVENT_TYPES, Cohort, Contact, Event, Room, db
from .recurrence import RecurrenceError, expand


class ValidationError(ValueError):
    """Raised when event input is invalid or would create a conflict."""


@dataclass
class Conflict:
    event: Event
    reason: str  # "room" or "cohort"

    def describe(self) -> str:
        what = (f"room {self.event.room.name}" if self.reason == "room" and self.event.room
                else "a shared cohort")
        return f"'{self.event.title}' on {self.event.start:%b %d, %I:%M %p} already uses {what}"


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open interval overlap: back-to-back events do not conflict."""
    return a_start < b_end and b_start < a_end


def validate_event(title: str, event_type: str, start: datetime, end: datetime,
                   capacity: int | None, cohort_ids: list[int]) -> None:
    if not title or not title.strip():
        raise ValidationError("Title is required")
    if event_type not in EVENT_TYPES:
        raise ValidationError(f"Event type must be one of {', '.join(EVENT_TYPES)}")
    if end <= start:
        raise ValidationError("End must be after start")
    if end - start > timedelta(hours=12):
        raise ValidationError("Events cannot exceed 12 hours")
    if capacity is not None and capacity < 1:
        raise ValidationError("Capacity must be positive")
    if not cohort_ids:
        raise ValidationError("Select at least one cohort")


def find_conflicts(start: datetime, end: datetime, room_id: int | None, cohort_ids: list[int],
                   exclude_id: int | None = None) -> list[Conflict]:
    """Events sharing the room, or targeting a shared cohort, that overlap in time."""
    q = Event.query.filter(Event.start < end, Event.end > start)
    if exclude_id:
        q = q.filter(Event.id != exclude_id)
    conflicts: list[Conflict] = []
    wanted = set(cohort_ids)
    for ev in q.all():
        if room_id and ev.room_id == room_id:
            conflicts.append(Conflict(ev, "room"))
        elif wanted & {c.id for c in ev.cohorts}:
            conflicts.append(Conflict(ev, "cohort"))
    return conflicts


def create_events(*, title: str, event_type: str, start: datetime, end: datetime,
                  cohort_ids: list[int], room_id: int | None = None,
                  capacity: int | None = None, required: bool = True, description: str = "",
                  rrule: str | None = None, contact_ids: list[int] | None = None,
                  exdates: set[date] | None = None,
                  allow_conflicts: bool = False) -> list[Event]:
    """Create one event, or a series if ``rrule`` is given. Raises on conflicts.

    The whole series is checked before anything is written, so a conflict on
    week 7 does not leave weeks 1 to 6 half-created.
    """
    validate_event(title, event_type, start, end, capacity, cohort_ids)
    cohorts = Cohort.query.filter(Cohort.id.in_(cohort_ids)).all()
    if len(cohorts) != len(set(cohort_ids)):
        raise ValidationError("Unknown cohort")
    if room_id is not None and db.session.get(Room, room_id) is None:
        raise ValidationError("Unknown room")
    contacts = Contact.query.filter(Contact.id.in_(contact_ids or [])).all()
    if len(contacts) != len(set(contact_ids or [])):
        raise ValidationError("Unknown contact")
    duration = end - start
    rrule = (rrule or "").strip() or None
    try:
        starts = expand(start, rrule, exdates) if rrule else [start]
    except RecurrenceError as exc:
        raise ValidationError(f"Recurrence rule: {exc}") from exc
    if not starts:
        raise ValidationError("Recurrence rule produced no occurrences")
    series_id = uuid.uuid4().hex[:12] if rrule else None

    if not allow_conflicts:
        for s in starts:
            found = find_conflicts(s, s + duration, room_id, cohort_ids)
            if found:
                raise ValidationError(f"{found[0].reason.title()} conflict: {found[0].describe()}")
        for i, a in enumerate(starts):  # series must not overlap itself
            for b in starts[i + 1:]:
                if overlaps(a, a + duration, b, b + duration):
                    raise ValidationError("Recurring occurrences overlap each other")

    events = []
    for s in starts:
        ev = Event(title=title.strip(), event_type=event_type, start=s, end=s + duration,
                   room_id=room_id, capacity=capacity, required=required,
                   description=description.strip(), series_id=series_id,
                   recurrence_rule=rrule)
        ev.cohorts = list(cohorts)
        ev.contacts = list(contacts)
        db.session.add(ev)
        events.append(ev)
    db.session.commit()
    return events


def delete_event(event: Event, scope: str = "single") -> int:
    """Delete one event, or with ``scope='future'`` this and later events in its series.

    Past occurrences in a series are kept so attendance history survives.
    Returns the number of events deleted.
    """
    if scope not in ("single", "future"):
        raise ValidationError("Scope must be 'single' or 'future'")
    targets = [event]
    if scope == "future" and event.series_id:
        targets = (Event.query.filter(Event.series_id == event.series_id,
                                      Event.start >= event.start).all())
    for ev in targets:
        db.session.delete(ev)
    db.session.commit()
    return len(targets)


def reschedule(event: Event, start: datetime, end: datetime, room_id: int | None,
               allow_conflicts: bool = False) -> Event:
    """Move a single occurrence, re-running validation and conflict checks."""
    validate_event(event.title, event.event_type, start, end, event.capacity,
                   [c.id for c in event.cohorts])
    if room_id is not None and db.session.get(Room, room_id) is None:
        raise ValidationError("Unknown room")
    if not allow_conflicts:
        found = find_conflicts(start, end, room_id, [c.id for c in event.cohorts],
                               exclude_id=event.id)
        if found:
            raise ValidationError(f"{found[0].reason.title()} conflict: {found[0].describe()}")
    event.start, event.end, event.room_id = start, end, room_id
    db.session.commit()
    return event
