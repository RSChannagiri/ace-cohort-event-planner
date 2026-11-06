from datetime import date, datetime

import pytest
from conftest import NOW
from factories import make_event

from ace_planner import calendar_view, followups
from ace_planner.ics import escape, fold, to_ics
from ace_planner.models import FollowUp

TODAY = NOW.date()


@pytest.fixture
def speaker_event(world):
    return make_event([world["a"]], datetime(2026, 11, 2, 18), contact_ids=[world["contact"].id],
                      title="Recruiter Panel")


def test_thank_you_created_once_due_two_days_after(speaker_event):
    created = followups.ensure_thank_yous(speaker_event)
    assert len(created) == 1 and created[0].due == date(2026, 11, 4)
    assert followups.ensure_thank_yous(speaker_event) == []
    assert FollowUp.query.count() == 1


def test_status_buckets(speaker_event, world):
    fu = followups.ensure_thank_yous(speaker_event)[0]
    assert followups.status(fu, TODAY) == "overdue"
    assert followups.status(fu, date(2026, 11, 2)) == "due_soon"
    assert followups.status(fu, date(2026, 10, 20)) == "upcoming"
    followups.complete(fu, TODAY, "Sent card")
    assert followups.status(fu, TODAY) == "done"
    assert fu.completed_on == TODAY and fu.notes == "Sent card"


def test_complete_twice_errors_and_reopen(speaker_event):
    fu = followups.ensure_thank_yous(speaker_event)[0]
    followups.complete(fu, TODAY)
    with pytest.raises(followups.FollowUpError):
        followups.complete(fu, TODAY)
    followups.reopen(fu)
    assert not fu.done and fu.completed_on is None
    assert followups.overdue(TODAY) == [fu]


def test_grouped_and_manual_followup(speaker_event, world):
    followups.ensure_thank_yous(speaker_event)
    followups.add_followup(world["contact"], speaker_event, date(2026, 11, 20), "Send resumes")
    groups = followups.grouped(TODAY)
    assert [len(groups[k]) for k in ("overdue", "due_soon", "upcoming", "done")] == [1, 0, 1, 0]


def test_manual_followup_validation(speaker_event, world):
    with pytest.raises(followups.FollowUpError, match="before the event"):
        followups.add_followup(world["contact"], speaker_event, date(2026, 10, 1))
    with pytest.raises(followups.FollowUpError, match="Kind"):
        followups.add_followup(world["contact"], speaker_event, date(2026, 11, 9), kind="gift")


def test_ics_escape_and_fold():
    assert escape("a, b; c\\d\ne") == r"a\, b\; c\\d\ne"
    long = "DESCRIPTION:" + "é" * 80
    folded = fold(long)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == long


def test_to_ics_structure(world):
    ev = make_event([world["a"]], datetime(2026, 11, 10, 16), room_id=world["big"].id,
                    title="Seminar, week 8", description="Bring laptops")
    body = to_ics([ev], "ACE Cohort A", stamp=datetime(2026, 11, 1, 12))
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;TZID=America/Los_Angeles:20261110T160000" in body
    assert "SUMMARY:Seminar\\, week 8" in body
    assert "LOCATION:Big Hall" in body and "BEGIN:VTIMEZONE" in body
    assert f"UID:ace-event-{ev.id}@ace-planner" in body
    assert body.count("BEGIN:VEVENT") == 1


def test_month_grid_weeks_and_events(world):
    ev = make_event([world["a"]], datetime(2026, 11, 10, 16))
    weeks = calendar_view.month_grid(2026, 11, [ev])
    assert all(len(w) == 7 for w in weeks) and weeks[0][0]["date"].weekday() == 0
    cells = {c["date"]: c for w in weeks for c in w}
    assert cells[date(2026, 11, 10)]["events"] == [ev]
    assert not cells[weeks[0][0]["date"]]["in_month"]  # Oct 26 spill-over


def test_month_helpers():
    assert calendar_view.shift_month(2026, 12, 1) == (2027, 1)
    assert calendar_view.shift_month(2026, 1, -1) == (2025, 12)
    assert calendar_view.month_bounds(2026, 12) == (datetime(2026, 12, 1), datetime(2027, 1, 1))
    assert calendar_view.months_between(date(2026, 9, 21), date(2026, 12, 11)) == [
        (2026, 9), (2026, 10), (2026, 11), (2026, 12)]
    assert calendar_view.months_between(date(2026, 9, 1), date(2026, 8, 1)) == []
