"""RSVP handling with capacity enforcement and an auto-promoting waitlist.

Rules:

* Only students in a cohort targeted by the event may RSVP.
* While seats remain (``Event.effective_capacity``) an RSVP is ``going``;
  after that it joins the waitlist in first-come order.
* When a ``going`` student cancels, the earliest waitlisted student is
  promoted automatically. Raising capacity promotes as many as now fit.
* A cancelled student who RSVPs again goes to the back of the line.
"""

from __future__ import annotations

from datetime import datetime

from .models import RSVP, Event, Student, db, utcnow


class RSVPError(ValueError):
    """Raised when an RSVP action is not allowed."""


def going_count(event: Event) -> int:
    return RSVP.query.filter_by(event_id=event.id, status="going").count()


def waitlist(event: Event) -> list[RSVP]:
    return (RSVP.query.filter_by(event_id=event.id, status="waitlisted")
            .order_by(RSVP.created_at, RSVP.id).all())


def seats_left(event: Event) -> int | None:
    cap = event.effective_capacity
    return None if cap is None else max(cap - going_count(event), 0)


def rsvp(event: Event, student: Student, now: datetime | None = None) -> RSVP:
    """RSVP a student. Returns the RSVP with status ``going`` or ``waitlisted``."""
    now = now or datetime.now()
    if event.start <= now:
        raise RSVPError("RSVPs are closed once an event has started")
    if student.cohort_id not in {c.id for c in event.cohorts}:
        raise RSVPError(f"{student.cohort.name} is not invited to this event")
    existing = RSVP.query.filter_by(event_id=event.id, student_id=student.id).first()
    if existing and existing.status != "cancelled":
        return existing  # idempotent: a double click does not lose a seat
    left = seats_left(event)
    status = "going" if left is None or left > 0 else "waitlisted"
    if existing:
        existing.status, existing.created_at = status, utcnow()
        record = existing
    else:
        record = RSVP(event_id=event.id, student_id=student.id, status=status,
                      created_at=utcnow())
        db.session.add(record)
    db.session.commit()
    return record


def cancel(event: Event, student: Student) -> RSVP | None:
    """Cancel an RSVP. Returns the RSVP promoted off the waitlist, if any."""
    record = RSVP.query.filter_by(event_id=event.id, student_id=student.id).first()
    if record is None or record.status == "cancelled":
        raise RSVPError("No active RSVP to cancel")
    was_going = record.status == "going"
    record.status = "cancelled"
    db.session.flush()
    promoted = promote(event, limit=1) if was_going else []
    db.session.commit()
    return promoted[0] if promoted else None


def promote(event: Event, limit: int | None = None) -> list[RSVP]:
    """Move waitlisted RSVPs to ``going`` while seats are free. Caller commits."""
    promoted: list[RSVP] = []
    for record in waitlist(event):
        left = seats_left(event)
        if (left is not None and left <= 0) or (limit is not None and len(promoted) >= limit):
            break
        record.status = "going"
        db.session.flush()
        promoted.append(record)
    return promoted


def set_capacity(event: Event, capacity: int | None) -> list[RSVP]:
    """Change an event's capacity and promote anyone who now fits.

    Lowering capacity never bumps students who already hold a seat; it only
    stops new ``going`` RSVPs until attendance drops below the new limit.
    """
    if capacity is not None and capacity < 1:
        raise RSVPError("Capacity must be positive")
    event.capacity = capacity
    db.session.flush()
    promoted = promote(event)
    db.session.commit()
    return promoted
