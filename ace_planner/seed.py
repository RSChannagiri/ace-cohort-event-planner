"""Deterministic synthetic data: 3 cohorts, 75 students, one Fall 2026 term.

Everything is generated with Faker under a fixed seed, so no real people
appear and every run produces the same data. Run with ``flask --app
ace_planner seed`` (add ``--reset`` to wipe first).
"""

from __future__ import annotations

import os
import random
from datetime import date, datetime, time, timedelta

import click
from faker import Faker
from flask import Flask

from . import followups, rsvp
from .models import (
    RSVP,
    Admin,
    Attendance,
    Cohort,
    Contact,
    Event,
    FollowUp,
    Room,
    Student,
    db,
)
from .scheduling import create_events

SEED = 2026
TERM_START = date(2026, 9, 21)
TERM_END = date(2026, 12, 11)
DEMO_NOW = datetime(2026, 11, 6, 9, 0)
THANKSGIVING = {date(2026, 11, 25), date(2026, 11, 26), date(2026, 11, 27)}
STUDENTS_PER_COHORT = 25
DEFAULT_ADMIN = ("admin", "ace-demo-2026")

COHORTS = [
    ("Cohort 2027", 2027, "#2a78d6"),
    ("Cohort 2028", 2028, "#eb6834"),
    ("Cohort 2029", 2029, "#1baf7a"),
]
ROOMS = [
    ("Learning Commons 210", 30),
    ("Lucas Hall 126", 60),
    ("Benson Parlor", 90),
    ("Vari Hall 135", 24),
]
MAJORS = ["MIS", "Finance", "Marketing", "Accounting", "Economics", "Computer Science",
          "Psychology", "Communication", "Biology", "Mechanical Engineering"]
ROLES = ["speaker", "speaker", "recruiter", "recruiter", "alumni", "faculty"]


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))


def _first_weekday_on_or_after(day: date, weekday: int) -> date:
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def seed_database(now: datetime = DEMO_NOW, reset: bool = False) -> dict[str, int]:
    """Populate the database. Returns counts of created rows."""
    if reset:
        db.drop_all()
        db.create_all()
    elif Cohort.query.first() is not None:
        raise click.ClickException("Database already has data. Use --reset to rebuild it.")

    fake = Faker("en_US")
    Faker.seed(SEED)
    rng = random.Random(SEED)

    username, password = DEFAULT_ADMIN
    admin = Admin(username=os.environ.get("ACE_ADMIN_USER", username))
    admin.set_password(os.environ.get("ACE_ADMIN_PASSWORD", password))
    db.session.add(admin)

    rooms = [Room(name=n, capacity=c) for n, c in ROOMS]
    cohorts = [Cohort(name=n, year=y, color=c) for n, y, c in COHORTS]
    db.session.add_all(rooms + cohorts)

    # Each student gets an engagement propensity; about 1 in 8 is disengaged so
    # the at-risk report has something real to show.
    propensity: dict[str, float] = {}
    emails: set[str] = set()
    students: list[Student] = []
    for cohort in cohorts:
        for _ in range(STUDENTS_PER_COHORT):
            first, last = fake.first_name(), fake.last_name()
            base = f"{first[0]}{last}".lower().replace("'", "")
            email, n = f"{base}@scu.example.edu", 1
            while email in emails:
                n += 1
                email = f"{base}{n}@scu.example.edu"
            emails.add(email)
            student = Student(first_name=first, last_name=last, email=email,
                              major=rng.choice(MAJORS), cohort=cohort)
            propensity[email] = (rng.uniform(0.25, 0.6) if rng.random() < 0.13
                                 else rng.uniform(0.72, 0.98))
            students.append(student)
    db.session.add_all(students)

    contacts = []
    for role in ROLES + ROLES[:2]:
        name = fake.name()
        company = fake.company()
        domain = company.split()[0].lower().strip(",").replace("'", "") + ".example.com"
        contacts.append(Contact(
            name=name, company=company, title=fake.job()[:120], role=role,
            email=f"{name.split()[0].lower()}@{domain}"))
    db.session.add_all(contacts)
    db.session.commit()

    until = TERM_END.strftime("%Y%m%d")
    c27, c28, c29 = (c.id for c in cohorts)
    by_name = {r.name: r.id for r in rooms}

    # Weekly cohort meetings: each cohort has its own day so they never collide.
    weekly = [(c27, 1, "Cohort 2027 Leadership Seminar", "Lucas Hall 126"),
              (c28, 2, "Cohort 2028 Skills Lab", "Learning Commons 210"),
              (c29, 3, "Cohort 2029 Community Circle", "Lucas Hall 126")]
    for cohort_id, weekday, title, room in weekly:
        first = _first_weekday_on_or_after(TERM_START, weekday)
        code = ("MO", "TU", "WE", "TH", "FR")[weekday]
        create_events(title=title, event_type="weekly", start=_at(first, 16),
                      end=_at(first, 17, 15), cohort_ids=[cohort_id], room_id=by_name[room],
                      rrule=f"FREQ=WEEKLY;BYDAY={code};UNTIL={until}", exdates=THANKSGIVING,
                      description="Weekly check-in, goal setting and peer coaching.")

    # Monthly professional development: first Thursday of Oct, Nov, Dec, all cohorts.
    pd_topics = ["Resume and LinkedIn Studio", "Networking with Intention",
                 "Negotiating Your First Offer"]
    pd = create_events(title="Professional Development Workshop",
                       event_type="professional_development",
                       start=_at(date(2026, 10, 1), 18), end=_at(date(2026, 10, 1), 19, 30),
                       cohort_ids=[c27, c28, c29], room_id=by_name["Benson Parlor"],
                       rrule="FREQ=MONTHLY;BYDAY=1TH;COUNT=3",
                       description="Monthly workshop led by an industry speaker.")
    for ev, topic, contact in zip(pd, pd_topics, contacts[:3], strict=True):
        ev.title = f"PD: {topic}"
        ev.contacts = [contact]

    one_offs = [
        ("ACE Fall Kickoff", date(2026, 9, 25), 17, 19, [c27, c28, c29], "Benson Parlor",
         None, True, []),
        ("Recruiter Panel: Breaking into Tech", date(2026, 10, 14), 18, 19, [c27, c28],
         "Lucas Hall 126", 45, False, [2, 3]),
        ("Mock Interview Night", date(2026, 10, 22), 18, 20, [c27], "Vari Hall 135", None,
         False, [3, 4]),
        ("Alumni Coffee Chats", date(2026, 11, 12), 12, 13, [c27, c28, c29],
         "Learning Commons 210", None, False, [4]),
        ("Industry Networking Night", date(2026, 11, 18), 18, 20, [c27, c28, c29],
         "Benson Parlor", 40, False, [2, 5, 6]),
        ("Community Service Day", date(2026, 11, 14), 9, 13, [c28, c29], None, None, True,
         [5]),
        ("End of Term Celebration", date(2026, 12, 11), 17, 19, [c27, c28, c29],
         "Benson Parlor", None, True, []),
    ]
    for title, day, h1, h2, cids, room, cap, req, contact_idx in one_offs:
        create_events(title=title, event_type="one_off", start=_at(day, h1), end=_at(day, h2),
                      cohort_ids=cids, room_id=by_name[room] if room else None, capacity=cap,
                      required=req, contact_ids=[contacts[i].id for i in contact_idx],
                      description=f"{title} for ACE students.")
    db.session.commit()

    # Attendance for every event that has already happened.
    past = Event.query.filter(Event.end <= now).order_by(Event.start).all()
    for ev in past:
        for s in ev.invited_students:
            chance = propensity[s.email] - (0.0 if ev.required else 0.2)
            db.session.add(Attendance(event_id=ev.id, student_id=s.id,
                                      present=rng.random() < chance))
    db.session.commit()

    # Thank-you notes for past events with speakers: anything older than two
    # weeks was sent; recent ones are still open, so some are overdue.
    for ev in past:
        for fu in followups.ensure_thank_yous(ev):
            if (now.date() - fu.due).days > 14:
                fu.done, fu.completed_on = True, fu.due - timedelta(days=rng.randint(0, 2))
    db.session.commit()
    networking = Event.query.filter_by(title="Industry Networking Night").one()
    for contact in networking.contacts:
        if contact.role == "recruiter":
            followups.add_followup(contact, networking, networking.start.date() + timedelta(days=5),
                                   "Send the ACE resume book and RSVP list")

    # RSVPs for upcoming optional events, oversubscribing the capped networking night.
    upcoming = Event.query.filter(Event.start > now, Event.required.is_(False)).all()
    for ev in upcoming:
        pool = list(ev.invited_students)
        rng.shuffle(pool)
        share = 0.62 if ev.capacity else 0.45
        for i, s in enumerate(pool[: int(len(pool) * share)]):
            record = rsvp.rsvp(ev, s, now)
            record.created_at = now - timedelta(hours=len(pool) - i)
        db.session.commit()

    return {
        "cohorts": Cohort.query.count(), "students": Student.query.count(),
        "events": Event.query.count(), "contacts": Contact.query.count(),
        "attendance": Attendance.query.count(), "rsvps": RSVP.query.count(),
        "followups": FollowUp.query.count(),
    }


def register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Drop and recreate all tables first.")
    def seed_command(reset: bool) -> None:
        """Load the synthetic Fall 2026 demo term."""
        counts = seed_database(reset=reset)
        click.echo(", ".join(f"{v} {k}" for k, v in counts.items()))
        click.echo(f"Admin login: {DEFAULT_ADMIN[0]} / {DEFAULT_ADMIN[1]} "
                   "(override with ACE_ADMIN_USER / ACE_ADMIN_PASSWORD)")
        click.echo("Tip: export ACE_NOW=2026-11-06T09:00 to view the term mid-quarter.")
