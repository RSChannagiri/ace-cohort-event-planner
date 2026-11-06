import click
import pytest
from conftest import NOW

from ace_planner import participation, rsvp
from ace_planner.models import Cohort, Event, FollowUp, Student
from ace_planner.seed import seed_database


@pytest.fixture
def seeded(app):
    return seed_database(now=NOW)


def test_seed_counts(seeded):
    assert seeded["cohorts"] == 3 and seeded["students"] == 75
    assert all(len(c.students) == 25 for c in Cohort.query.all())
    assert seeded["events"] > 30


def test_seed_has_all_event_types_and_monthly_pd(seeded):
    types = {e.event_type for e in Event.query.all()}
    assert types == {"weekly", "professional_development", "one_off"}
    pd = Event.query.filter_by(event_type="professional_development").order_by(Event.start).all()
    assert [e.start.strftime("%a %m-%d") for e in pd] == ["Thu 10-01", "Thu 11-05", "Thu 12-03"]


def test_seed_skips_thanksgiving_and_has_no_conflicts(seeded):
    from ace_planner.scheduling import find_conflicts

    assert not any(e.start.month == 11 and e.start.day in (25, 26, 27)
                   for e in Event.query.all())
    for ev in Event.query.all():
        assert find_conflicts(ev.start, ev.end, ev.room_id, [c.id for c in ev.cohorts],
                              exclude_id=ev.id) == []


def test_seed_produces_at_risk_students_and_a_waitlist(seeded):
    risk = participation.at_risk(Student.query.all(), NOW)
    assert 3 <= len(risk) <= 20
    night = Event.query.filter_by(title="Industry Networking Night").one()
    assert rsvp.going_count(night) == 40 and len(rsvp.waitlist(night)) > 0


def test_seed_followups_mix(seeded):
    assert FollowUp.query.filter_by(done=True).count() > 0
    assert FollowUp.query.filter_by(done=False).count() > 0


def test_seed_is_deterministic_and_refuses_double_seed(app):
    seed_database(now=NOW)
    names = [s.full_name for s in Student.query.order_by(Student.id)]
    with pytest.raises(click.ClickException):
        seed_database(now=NOW)
    seed_database(now=NOW, reset=True)
    assert [s.full_name for s in Student.query.order_by(Student.id)] == names


def test_seeded_app_pages_render(app, seeded):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_csrf"] = "t"
    c.post("/login", data={"username": "admin", "password": "ace-demo-2026", "_csrf": "t"})
    for url in ["/", "/participation", "/analytics", "/followups", "/calendar"]:
        assert c.get(url).status_code == 200
