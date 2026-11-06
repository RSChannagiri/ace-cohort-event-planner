from datetime import date, datetime, timedelta

import pytest
from factories import make_event

from ace_planner.models import Event
from ace_planner.scheduling import (
    ValidationError,
    create_events,
    delete_event,
    find_conflicts,
    overlaps,
    reschedule,
    validate_event,
)

T = datetime(2026, 11, 10, 16, 0)


def test_overlap_is_half_open():
    end = T + timedelta(hours=1)
    assert overlaps(T, end, T + timedelta(minutes=30), end + timedelta(hours=1))
    assert not overlaps(T, end, end, end + timedelta(hours=1))  # back to back is fine


@pytest.mark.parametrize("kwargs, msg", [
    ({"title": "  "}, "Title"),
    ({"event_type": "party"}, "Event type"),
    ({"end": T}, "End must be after"),
    ({"end": T + timedelta(hours=13)}, "12 hours"),
    ({"capacity": 0}, "Capacity"),
    ({"cohort_ids": []}, "cohort"),
])
def test_validate_event_rejects_bad_input(kwargs, msg):
    base = {"title": "Seminar", "event_type": "weekly", "start": T,
            "end": T + timedelta(hours=1), "capacity": None, "cohort_ids": [1]}
    base.update(kwargs)
    with pytest.raises(ValidationError, match=msg):
        validate_event(**base)


def test_room_conflict_detected_across_cohorts(world):
    make_event([world["a"]], T, room_id=world["small"].id, title="A meeting")
    found = find_conflicts(T + timedelta(minutes=30), T + timedelta(hours=2),
                           world["small"].id, [world["b"].id])
    assert [(c.event.title, c.reason) for c in found] == [("A meeting", "room")]


def test_cohort_conflict_detected_in_different_rooms(world):
    make_event([world["a"]], T, room_id=world["small"].id)
    found = find_conflicts(T, T + timedelta(hours=1), world["big"].id, [world["a"].id])
    assert found[0].reason == "cohort"


def test_no_conflict_for_other_cohort_in_other_room(world):
    make_event([world["a"]], T, room_id=world["small"].id)
    assert find_conflicts(T, T + timedelta(hours=1), world["big"].id, [world["b"].id]) == []


def test_create_raises_on_conflict_and_writes_nothing(world):
    make_event([world["a"]], T + timedelta(weeks=2), room_id=world["big"].id, title="Blocker")
    with pytest.raises(ValidationError, match="Blocker"):
        create_events(title="Series", event_type="weekly", start=T, end=T + timedelta(hours=1),
                      cohort_ids=[world["a"].id], rrule="FREQ=WEEKLY;COUNT=4")
    assert Event.query.count() == 1  # nothing partial written


def test_allow_conflicts_overrides(world):
    make_event([world["a"]], T)
    make_event([world["a"]], T, allow_conflicts=True)
    assert Event.query.count() == 2


def test_series_shares_id_and_rule_and_skips_exdates(world):
    events = create_events(title="Seminar", event_type="weekly", start=T,
                           end=T + timedelta(hours=1), cohort_ids=[world["a"].id],
                           rrule="FREQ=WEEKLY;COUNT=4", exdates={date(2026, 11, 24)})
    assert len(events) == 3
    assert len({e.series_id for e in events}) == 1 and events[0].series_id
    assert events[0].recurrence_rule == "FREQ=WEEKLY;COUNT=4"


def test_bad_rrule_becomes_validation_error(world):
    with pytest.raises(ValidationError, match="Recurrence rule"):
        make_event([world["a"]], T, rrule="FREQ=WEEKLY")


def test_rule_with_no_occurrences_rejected(world):
    with pytest.raises(ValidationError, match="no occurrences"):
        make_event([world["a"]], T, rrule="FREQ=WEEKLY;UNTIL=20260101")


def test_unknown_room_cohort_and_contact_rejected(world):
    with pytest.raises(ValidationError, match="Unknown room"):
        make_event([world["a"]], T, room_id=999)
    with pytest.raises(ValidationError, match="Unknown contact"):
        make_event([world["a"]], T, contact_ids=[999])
    with pytest.raises(ValidationError, match="Unknown cohort"):
        create_events(title="X", event_type="one_off", start=T, end=T + timedelta(hours=1),
                      cohort_ids=[999])


def test_delete_future_keeps_earlier_occurrences(world):
    events = create_events(title="Seminar", event_type="weekly", start=T,
                           end=T + timedelta(hours=1), cohort_ids=[world["a"].id],
                           rrule="FREQ=WEEKLY;COUNT=5")
    assert delete_event(events[2], "future") == 3
    assert Event.query.count() == 2


def test_delete_single_and_bad_scope(world):
    ev = make_event([world["a"]], T)
    with pytest.raises(ValidationError):
        delete_event(ev, "everything")
    assert delete_event(ev) == 1
    assert Event.query.count() == 0


def test_reschedule_checks_conflicts_but_ignores_itself(world):
    ev = make_event([world["a"]], T, room_id=world["small"].id)
    make_event([world["b"]], T + timedelta(hours=3), room_id=world["small"].id, title="Later")
    reschedule(ev, T + timedelta(minutes=30), T + timedelta(hours=1, minutes=30),
               world["small"].id)
    assert ev.start == T + timedelta(minutes=30)
    with pytest.raises(ValidationError, match="Room conflict"):
        reschedule(ev, T + timedelta(hours=3), T + timedelta(hours=4), world["small"].id)
