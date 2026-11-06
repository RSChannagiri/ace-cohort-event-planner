from datetime import timedelta

import pytest
from conftest import NOW
from factories import make_event

from ace_planner.models import RSVP, Attendance, Contact, Event, FollowUp, db

CSRF = {"_csrf": "test-token"}
PAGES = ["/", "/cohorts", "/participation", "/participation?at_risk=1", "/events",
         "/events?when=past&type=weekly", "/events/new", "/calendar",
         "/calendar?year=2026&month=12", "/contacts", "/followups", "/analytics"]


@pytest.mark.parametrize("url", PAGES)
def test_pages_require_login(client, world, url):
    r = client.get(url)
    assert r.status_code == 302 and "/login" in r.location


@pytest.mark.parametrize("url", PAGES)
def test_pages_render_for_admin(auth, url):
    assert auth.get(url).status_code == 200


def test_bad_password_rejected(client, world):
    r = client.post("/login", data={"username": "admin", "password": "nope", **CSRF})
    assert r.status_code == 200 and b"Invalid username or password" in r.data


def test_login_redirects_to_safe_next_only(client, world):
    data = {"username": "admin", "password": "secret-pass", **CSRF}
    r = client.post("/login?next=https://evil.example.com", data=data)
    assert r.location == "/"
    client.post("/logout", data=CSRF)
    with client.session_transaction() as sess:
        sess["_csrf"] = "test-token"
    r = client.post("/login?next=/analytics", data=data)
    assert r.location == "/analytics"


def test_post_without_or_with_wrong_csrf_rejected(auth):
    assert auth.post("/contacts", data={"name": "X"}).status_code == 400
    assert auth.post("/contacts", data={"name": "X", "_csrf": "forged"}).status_code == 400


def test_empty_csrf_rejected_even_with_empty_session(app):
    c = app.test_client()
    assert c.post("/login", data={"_csrf": ""}).status_code == 400


def test_logout_clears_session(auth):
    auth.post("/logout", data=CSRF)
    assert auth.get("/").status_code == 302


def test_create_recurring_event_via_form(auth, world):
    r = auth.post("/events/new", data={
        **CSRF, "title": "Seminar", "event_type": "weekly", "date": "2026-11-10",
        "start_time": "16:00", "end_time": "17:00", "cohort_ids": [str(world["a"].id)],
        "room_id": str(world["big"].id), "rrule": "FREQ=WEEKLY;COUNT=4",
        "exdates": "2026-11-24", "required": "on"})
    assert r.status_code == 302
    assert Event.query.count() == 3
    page = auth.get(r.location)
    assert b"Part of a series of 3" in page.data


def test_create_event_conflict_shows_error_and_keeps_input(auth, world):
    make_event([world["a"]], NOW + timedelta(days=4), title="Existing")
    day = (NOW + timedelta(days=4)).strftime("%Y-%m-%d")
    r = auth.post("/events/new", data={
        **CSRF, "title": "Clash", "event_type": "one_off", "date": day,
        "start_time": NOW.strftime("%H:%M"), "end_time": "11:00",
        "cohort_ids": [str(world["a"].id)]})
    assert r.status_code == 422
    assert b"Cohort conflict" in r.data and b'value="Clash"' in r.data


def test_create_event_bad_date(auth, world):
    r = auth.post("/events/new", data={**CSRF, "title": "X", "event_type": "one_off",
                                       "date": "nope", "start_time": "10:00",
                                       "end_time": "11:00"})
    assert r.status_code == 422 and b"valid date" in r.data


def test_rsvp_waitlist_and_cancel_flow(auth, world):
    ev = make_event([world["a"]], NOW + timedelta(days=2), room_id=world["small"].id)
    s = world["students"]
    for st in s[:3]:
        auth.post(f"/events/{ev.id}/rsvp", data={**CSRF, "student_id": st.id})
    assert RSVP.query.filter_by(status="waitlisted").count() == 1
    r = auth.post(f"/events/{ev.id}/rsvp/{s[0].id}/cancel", data=CSRF, follow_redirects=True)
    assert b"promoted from the waitlist" in r.data
    assert RSVP.query.filter_by(status="going").count() == 2


def test_rsvp_for_uninvited_student_flashes_error(auth, world):
    ev = make_event([world["a"]], NOW + timedelta(days=2))
    r = auth.post(f"/events/{ev.id}/rsvp", data={**CSRF, "student_id": world["students"][4].id},
                  follow_redirects=True)
    assert b"not invited" in r.data and RSVP.query.count() == 0


def test_capacity_update_promotes(auth, world):
    ev = make_event([world["a"]], NOW + timedelta(days=2), capacity=1)
    for st in world["students"][:3]:
        auth.post(f"/events/{ev.id}/rsvp", data={**CSRF, "student_id": st.id})
    r = auth.post(f"/events/{ev.id}/capacity", data={**CSRF, "capacity": "3"},
                  follow_redirects=True)
    assert b"2 promoted" in r.data


def test_attendance_marking_creates_thank_yous(auth, world):
    ev = make_event([world["a"]], NOW - timedelta(days=1), contact_ids=[world["contact"].id])
    s = world["students"]
    assert auth.get(f"/events/{ev.id}/attendance").status_code == 200
    r = auth.post(f"/events/{ev.id}/attendance",
                  data={**CSRF, "present": [str(s[0].id), str(s[1].id)]}, follow_redirects=True)
    assert b"2 of 3 present" in r.data
    assert Attendance.query.filter_by(present=True).count() == 2
    assert FollowUp.query.count() == 1


def test_attendance_on_future_event_rejected(auth, world):
    ev = make_event([world["a"]], NOW + timedelta(days=1))
    r = auth.post(f"/events/{ev.id}/attendance", data={**CSRF, "present": []})
    assert r.status_code == 200 and b"once the event has started" in r.data


def test_delete_event(auth, world):
    ev = make_event([world["a"]], NOW + timedelta(days=1))
    r = auth.post(f"/events/{ev.id}/delete", data={**CSRF, "scope": "single"})
    assert r.status_code == 302 and Event.query.count() == 0


def test_followup_complete_and_reopen(auth, world):
    ev = make_event([world["a"]], NOW - timedelta(days=5), contact_ids=[world["contact"].id])
    from ace_planner.followups import ensure_thank_yous

    fu = ensure_thank_yous(ev)[0]
    page = auth.get("/followups")
    assert b"Overdue" in page.data and b"Pat Speaker" in page.data
    auth.post(f"/followups/{fu.id}/complete", data=CSRF)
    assert db.session.get(FollowUp, fu.id).done
    auth.post(f"/followups/{fu.id}/reopen", data=CSRF)
    assert not db.session.get(FollowUp, fu.id).done


def test_add_contact_validation(auth, world):
    bad = auth.post("/contacts", data={**CSRF, "name": "A", "company": "B", "title": "C",
                                       "email": "not-an-email", "role": "speaker"})
    assert b"valid email" in bad.data
    good = auth.post("/contacts", data={**CSRF, "name": "Jo Rivera", "company": "Initech",
                                        "title": "Recruiter", "email": "jo@initech.example.com",
                                        "role": "recruiter"})
    assert good.status_code == 302 and Contact.query.count() == 2


def test_cohort_ics_is_public_and_scoped(client, world):
    make_event([world["a"]], NOW + timedelta(days=1), title="Only A")
    make_event([world["b"]], NOW + timedelta(days=1), title="Only B")
    r = client.get(f"/cohorts/{world['a'].id}/calendar.ics")
    assert r.status_code == 200 and r.mimetype == "text/calendar"
    assert b"Only A" in r.data and b"Only B" not in r.data
    assert "ace-cohort-a.ics" in r.headers["Content-Disposition"]


def test_detail_pages_and_404s(auth, world):
    ev = make_event([world["a"]], NOW + timedelta(days=1))
    for url in [f"/events/{ev.id}", f"/cohorts/{world['a'].id}",
                f"/students/{world['students'][0].id}", f"/contacts/{world['contact'].id}"]:
        assert auth.get(url).status_code == 200, url
    for url in ["/events/999", "/cohorts/999", "/students/999", "/contacts/999",
                "/calendar?year=2026&month=13"]:
        assert auth.get(url).status_code == 404, url


def test_calendar_shows_events_in_grid(auth, world):
    make_event([world["a"]], NOW + timedelta(days=4), title="Grid Event")
    r = auth.get("/calendar?year=2026&month=11")
    assert b"November 2026" in r.data and b"Grid Event" in r.data
