from __future__ import annotations

from datetime import datetime

import pytest

from ace_planner import create_app
from ace_planner.models import Admin, Cohort, Contact, Room, Student, db

NOW = datetime(2026, 11, 6, 9, 0)


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://",
                      "SECRET_KEY": "test", "NOW": NOW.isoformat()})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def world(app):
    """Two cohorts with 3 students each, two rooms, one contact."""
    a = Cohort(name="Cohort A", year=2027)
    b = Cohort(name="Cohort B", year=2028)
    small = Room(name="Small Room", capacity=2)
    big = Room(name="Big Hall", capacity=100)
    db.session.add_all([a, b, small, big])
    students = []
    for i, cohort in enumerate([a, a, a, b, b, b]):
        students.append(Student(first_name=f"S{i}", last_name=f"Last{i}",
                                email=f"s{i}@example.edu", cohort=cohort))
    contact = Contact(name="Pat Speaker", company="Acme Corp", title="VP Talent",
                      email="pat@acme.example.com", role="recruiter")
    db.session.add_all(students + [contact])
    admin = Admin(username="admin")
    admin.set_password("secret-pass")
    db.session.add(admin)
    db.session.commit()
    return {"a": a, "b": b, "small": small, "big": big, "students": students,
            "contact": contact}


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_csrf"] = "test-token"
    return c


@pytest.fixture
def auth(client, world):
    r = client.post("/login", data={"username": "admin", "password": "secret-pass",
                                    "_csrf": "test-token"})
    assert r.status_code == 302
    with client.session_transaction() as sess:  # login rotates the session
        sess["_csrf"] = "test-token"
    return client
