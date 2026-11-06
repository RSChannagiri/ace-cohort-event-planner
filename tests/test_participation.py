from datetime import timedelta

import pytest
from conftest import NOW
from factories import make_event

from ace_planner import analytics, participation
from ace_planner.models import Attendance, Student

PAST = NOW - timedelta(days=7)


def _past_events(world, n, cohorts=None, **kw):
    return [make_event(cohorts or [world["a"]], PAST + timedelta(days=i), **kw)
            for i in range(n)]


def test_mark_attendance_records_every_invited_student(world):
    ev = make_event([world["a"]], PAST)
    s = world["students"]
    assert participation.mark_attendance(ev, {s[0].id, s[1].id}, NOW) == 2
    marks = {a.student_id: a.present for a in Attendance.query.all()}
    assert marks == {s[0].id: True, s[1].id: True, s[2].id: False}


def test_remarking_overwrites(world):
    ev = make_event([world["a"]], PAST)
    s = world["students"]
    participation.mark_attendance(ev, {s[0].id}, NOW)
    participation.mark_attendance(ev, {s[2].id}, NOW)
    assert Attendance.query.count() == 3
    assert {a.student_id for a in Attendance.query.filter_by(present=True)} == {s[2].id}


def test_cannot_mark_future_event_or_uninvited_student(world):
    future = make_event([world["a"]], NOW + timedelta(days=1))
    with pytest.raises(participation.AttendanceError, match="started"):
        participation.mark_attendance(future, set(), NOW)
    past = make_event([world["a"]], PAST)
    with pytest.raises(participation.AttendanceError, match="not invited"):
        participation.mark_attendance(past, {world["students"][5].id}, NOW)


def test_rate_and_at_risk_threshold(world):
    events = _past_events(world, 5)
    s = world["students"]
    for i, ev in enumerate(events):
        present = {s[0].id} | ({s[1].id} if i < 3 else set()) | ({s[2].id} if i < 2 else set())
        participation.mark_attendance(ev, present, NOW)
    rows = {p.student.id: p for p in participation.roster_participation(s[:3], NOW)}
    assert rows[s[0].id].rate == 1.0 and not rows[s[0].id].at_risk
    assert rows[s[1].id].rate == 0.6 and not rows[s[1].id].at_risk  # exactly 60% is OK
    assert rows[s[2].id].percent == 40.0 and rows[s[2].id].at_risk
    assert rows[s[2].id].missed == 3


def test_optional_and_future_events_do_not_count(world):
    s = world["students"]
    req = make_event([world["a"]], PAST)
    opt = make_event([world["a"]], PAST + timedelta(days=1), required=False)
    make_event([world["a"]], NOW + timedelta(days=2))
    participation.mark_attendance(req, {s[0].id}, NOW)
    participation.mark_attendance(opt, set(), NOW)
    p = participation.participation_for(s[0], NOW)
    assert (p.required_events, p.attended) == (1, 1)


def test_unmarked_past_required_event_counts_as_missed(world):
    _past_events(world, 2)
    p = participation.participation_for(world["students"][0], NOW)
    assert (p.required_events, p.attended, p.at_risk) == (2, 0, True)


def test_multi_cohort_event_counted_once_per_student(world):
    ev = make_event([world["a"], world["b"]], PAST)
    participation.mark_attendance(ev, {s.id for s in world["students"]}, NOW)
    rows = participation.roster_participation(world["students"], NOW)
    assert all((r.required_events, r.attended) == (1, 1) for r in rows)


def test_no_required_events_means_no_flag_and_sorts_last(world):
    s = world["students"]
    _past_events(world, 1, cohorts=[world["a"]])
    rows = participation.roster_participation([s[3], s[0]], NOW)
    assert rows[0].student.id == s[0].id and rows[0].at_risk
    assert rows[1].rate is None and not rows[1].at_risk


def test_at_risk_helper(world):
    _past_events(world, 2)
    assert len(participation.at_risk(Student.query.all(), NOW)) == 3


def test_analytics_by_type_cohort_month(world):
    s = world["students"]
    weekly = make_event([world["a"]], PAST, event_type="weekly")
    pd = make_event([world["b"]], NOW - timedelta(days=40), event_type="professional_development")
    participation.mark_attendance(weekly, {s[0].id, s[1].id}, NOW)
    participation.mark_attendance(pd, {s[3].id}, NOW)
    rates = analytics.attendance_rates()
    by_type = {r.label: r.percent for r in rates["by_type"]}
    assert by_type == {"Professional development": 33.3, "Weekly cohort meeting": 66.7}
    assert {r.label: (r.present, r.total) for r in rates["by_cohort"]} == {
        "Cohort A": (2, 3), "Cohort B": (1, 3)}
    assert [r.label for r in rates["by_month"]] == ["2026-09", "2026-10"]
    assert analytics.overall_rate().percent == 50.0


def test_analytics_empty(app):
    rates = analytics.attendance_rates()
    assert rates == {"by_type": [], "by_cohort": [], "by_month": []}
    assert analytics.Rate("x", 0, 0).percent == 0.0
