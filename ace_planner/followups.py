"""Speaker and recruiter follow-up tracker.

Every contact linked to an event is owed a thank-you note, due
``THANK_YOU_DAYS`` after the event ends. Staff can also log ad-hoc follow-ups
(for example "send internship info to cohort"). Tasks are grouped as overdue,
due soon (within ``DUE_SOON_DAYS``), upcoming, or done.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import FOLLOWUP_KINDS, Contact, Event, FollowUp, db

THANK_YOU_DAYS = 2
DUE_SOON_DAYS = 3


class FollowUpError(ValueError):
    """Raised for invalid follow-up input."""


def status(fu: FollowUp, today: date) -> str:
    if fu.done:
        return "done"
    if fu.due < today:
        return "overdue"
    if fu.due <= today + timedelta(days=DUE_SOON_DAYS):
        return "due_soon"
    return "upcoming"


def ensure_thank_yous(event: Event) -> list[FollowUp]:
    """Create one thank-you task per linked contact. Safe to call repeatedly."""
    have = {f.contact_id for f in FollowUp.query.filter_by(event_id=event.id,
                                                           kind="thank_you")}
    created = []
    for contact in event.contacts:
        if contact.id not in have:
            fu = FollowUp(contact_id=contact.id, event_id=event.id, kind="thank_you",
                          due=event.end.date() + timedelta(days=THANK_YOU_DAYS),
                          notes=f"Thank-you for {event.title}")
            db.session.add(fu)
            created.append(fu)
    db.session.commit()
    return created


def add_followup(contact: Contact, event: Event, due: date, notes: str = "",
                 kind: str = "follow_up") -> FollowUp:
    if kind not in FOLLOWUP_KINDS:
        raise FollowUpError(f"Kind must be one of {', '.join(FOLLOWUP_KINDS)}")
    if due < event.start.date():
        raise FollowUpError("A follow-up cannot be due before the event")
    fu = FollowUp(contact_id=contact.id, event_id=event.id, kind=kind, due=due,
                  notes=notes.strip())
    db.session.add(fu)
    db.session.commit()
    return fu


def pending() -> list[FollowUp]:
    return FollowUp.query.filter_by(done=False).order_by(FollowUp.due, FollowUp.id).all()


def overdue(today: date) -> list[FollowUp]:
    return [f for f in pending() if f.is_overdue(today)]


def grouped(today: date) -> dict[str, list[FollowUp]]:
    groups: dict[str, list[FollowUp]] = {"overdue": [], "due_soon": [], "upcoming": [],
                                         "done": []}
    for fu in FollowUp.query.order_by(FollowUp.due, FollowUp.id).all():
        groups[status(fu, today)].append(fu)
    groups["done"].sort(key=lambda f: f.completed_on or f.due, reverse=True)
    return groups


def complete(fu: FollowUp, today: date, notes: str = "") -> None:
    if fu.done:
        raise FollowUpError("Follow-up is already complete")
    fu.done = True
    fu.completed_on = today
    if notes.strip():
        fu.notes = notes.strip()
    db.session.commit()


def reopen(fu: FollowUp) -> None:
    fu.done = False
    fu.completed_on = None
    db.session.commit()
