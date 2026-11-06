"""SQLAlchemy models for the ACE cohort event planner."""

from __future__ import annotations

from datetime import UTC, date, datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

EVENT_TYPES = ("weekly", "professional_development", "one_off")
EVENT_TYPE_LABELS = {
    "weekly": "Weekly cohort meeting",
    "professional_development": "Professional development",
    "one_off": "One-off event",
}
RSVP_STATUSES = ("going", "waitlisted", "cancelled")
CONTACT_ROLES = ("speaker", "recruiter", "alumni", "faculty")
FOLLOWUP_KINDS = ("thank_you", "follow_up")


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes)."""
    return datetime.now(UTC).replace(tzinfo=None)

event_cohorts = db.Table(
    "event_cohorts",
    db.Column("event_id", db.ForeignKey("event.id"), primary_key=True),
    db.Column("cohort_id", db.ForeignKey("cohort.id"), primary_key=True),
)

event_contacts = db.Table(
    "event_contacts",
    db.Column("event_id", db.ForeignKey("event.id"), primary_key=True),
    db.Column("contact_id", db.ForeignKey("contact.id"), primary_key=True),
)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Cohort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#2563eb")
    students = db.relationship("Student", back_populates="cohort", order_by="Student.last_name")


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    major = db.Column(db.String(80), nullable=False, default="MIS")
    cohort_id = db.Column(db.ForeignKey("cohort.id"), nullable=False)
    cohort = db.relationship("Cohort", back_populates="students")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)


class Contact(db.Model):
    """A speaker, recruiter, or industry leader."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    company = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="speaker")
    followups = db.relationship("FollowUp", back_populates="contact", cascade="all, delete-orphan")


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    event_type = db.Column(db.String(40), nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    room_id = db.Column(db.ForeignKey("room.id"), nullable=True)
    capacity = db.Column(db.Integer, nullable=True)
    required = db.Column(db.Boolean, nullable=False, default=True)
    description = db.Column(db.Text, default="")
    series_id = db.Column(db.String(40), nullable=True, index=True)
    recurrence_rule = db.Column(db.String(200), nullable=True)
    room = db.relationship("Room")
    cohorts = db.relationship("Cohort", secondary=event_cohorts, lazy="selectin")
    contacts = db.relationship("Contact", secondary=event_contacts, lazy="selectin")
    rsvps = db.relationship("RSVP", back_populates="event", cascade="all, delete-orphan")
    attendance = db.relationship(
        "Attendance", back_populates="event", cascade="all, delete-orphan"
    )
    followups = db.relationship("FollowUp", back_populates="event", cascade="all, delete-orphan")

    @property
    def effective_capacity(self) -> int | None:
        caps = [c for c in (self.capacity, self.room.capacity if self.room else None) if c]
        return min(caps) if caps else None

    @property
    def type_label(self) -> str:
        return EVENT_TYPE_LABELS.get(self.event_type, self.event_type)

    @property
    def invited_students(self) -> list[Student]:
        return [s for c in sorted(self.cohorts, key=lambda c: c.name) for s in c.students]


class RSVP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.ForeignKey("event.id"), nullable=False)
    student_id = db.Column(db.ForeignKey("student.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    event = db.relationship("Event", back_populates="rsvps")
    student = db.relationship("Student")
    __table_args__ = (db.UniqueConstraint("event_id", "student_id"),)


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.ForeignKey("event.id"), nullable=False)
    student_id = db.Column(db.ForeignKey("student.id"), nullable=False)
    present = db.Column(db.Boolean, nullable=False)
    event = db.relationship("Event", back_populates="attendance")
    student = db.relationship("Student")
    __table_args__ = (db.UniqueConstraint("event_id", "student_id"),)


class FollowUp(db.Model):
    """Thank-you / follow-up task owed to a contact after an event."""

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.ForeignKey("contact.id"), nullable=False)
    event_id = db.Column(db.ForeignKey("event.id"), nullable=False)
    kind = db.Column(db.String(40), nullable=False, default="thank_you")
    due = db.Column(db.Date, nullable=False)
    done = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, default="")
    contact = db.relationship("Contact", back_populates="followups")
    event = db.relationship("Event", back_populates="followups")

    completed_on = db.Column(db.Date, nullable=True)

    def is_overdue(self, today: date) -> bool:
        return not self.done and self.due < today
