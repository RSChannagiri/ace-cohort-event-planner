"""Attendance marking and per-student participation with at-risk flags.

A student's participation rate is the share of *required* events targeted at
their cohort that have already ended and that they attended. Students below
``AT_RISK_THRESHOLD`` (60%) are flagged so staff can check in early. Students
with no required events yet have no rate and are never flagged.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from .models import Attendance, Event, Student, db, event_cohorts

AT_RISK_THRESHOLD = 0.60


class AttendanceError(ValueError):
    """Raised when attendance cannot be recorded."""


@dataclass(frozen=True)
class Participation:
    student: Student
    required_events: int
    attended: int

    @property
    def rate(self) -> float | None:
        return self.attended / self.required_events if self.required_events else None

    @property
    def percent(self) -> float | None:
        return None if self.rate is None else round(self.rate * 100, 1)

    @property
    def missed(self) -> int:
        return self.required_events - self.attended

    @property
    def at_risk(self) -> bool:
        return self.rate is not None and self.rate < AT_RISK_THRESHOLD


def mark_attendance(event: Event, present_ids: set[int], now: datetime | None = None) -> int:
    """Record present/absent for every invited student. Returns the number present.

    Re-marking overwrites earlier marks, so staff can fix mistakes.
    """
    now = now or datetime.now()
    if event.start > now:
        raise AttendanceError("Attendance can only be taken once the event has started")
    invited = event.invited_students
    invited_ids = {s.id for s in invited}
    stray = present_ids - invited_ids
    if stray:
        raise AttendanceError(f"{len(stray)} selected student(s) are not invited to this event")
    existing = {a.student_id: a for a in event.attendance}
    for student in invited:
        is_present = student.id in present_ids
        record = existing.get(student.id)
        if record is None:
            db.session.add(Attendance(event_id=event.id, student_id=student.id,
                                      present=is_present))
        else:
            record.present = is_present
    db.session.commit()
    return len(present_ids)


def roster_participation(students: list[Student],
                         now: datetime | None = None) -> list[Participation]:
    """Participation for many students using two aggregate queries.

    Sorted lowest rate first so at-risk students surface at the top; students
    with no required events sort last.
    """
    now = now or datetime.now()
    required_by_cohort: Counter[int] = Counter(
        dict(db.session.query(event_cohorts.c.cohort_id, db.func.count())
             .join(Event, Event.id == event_cohorts.c.event_id)
             .filter(Event.required.is_(True), Event.end <= now)
             .group_by(event_cohorts.c.cohort_id).all())
    )
    attended_by_student: Counter[int] = Counter(
        dict(db.session.query(Attendance.student_id, db.func.count())
             .join(Event, Event.id == Attendance.event_id)
             .join(event_cohorts, event_cohorts.c.event_id == Event.id)
             .join(Student, Student.id == Attendance.student_id)
             .filter(Event.required.is_(True), Event.end <= now,
                     Attendance.present.is_(True),
                     event_cohorts.c.cohort_id == Student.cohort_id)
             .group_by(Attendance.student_id).all())
    )
    rows = [Participation(s, required_by_cohort[s.cohort_id], attended_by_student[s.id])
            for s in students]
    return sorted(rows, key=lambda p: (p.rate if p.rate is not None else 2.0,
                                       p.student.last_name, p.student.first_name))


def participation_for(student: Student, now: datetime | None = None) -> Participation:
    return roster_participation([student], now)[0]


def at_risk(students: list[Student], now: datetime | None = None) -> list[Participation]:
    return [p for p in roster_participation(students, now) if p.at_risk]
