from datetime import timedelta

import pytest
from conftest import NOW
from factories import make_event

from ace_planner import rsvp
from ace_planner.models import RSVP

LATER = NOW + timedelta(days=3)


@pytest.fixture
def capped(world):
    return make_event([world["a"], world["b"]], LATER, room_id=world["big"].id, capacity=2,
                      required=False)


def test_capacity_then_waitlist(world, capped):
    s = world["students"]
    statuses = [rsvp.rsvp(capped, st, NOW).status for st in s[:4]]
    assert statuses == ["going", "going", "waitlisted", "waitlisted"]
    assert rsvp.seats_left(capped) == 0


def test_effective_capacity_uses_smaller_of_room_and_limit(world):
    ev = make_event([world["a"]], LATER, room_id=world["small"].id, capacity=50)
    assert ev.effective_capacity == 2
    ev2 = make_event([world["b"]], LATER, room_id=world["big"].id)
    assert ev2.effective_capacity == 100
    ev3 = make_event([world["b"]], LATER + timedelta(days=1))
    assert ev3.effective_capacity is None and rsvp.seats_left(ev3) is None


def test_cancel_promotes_first_waitlisted(world, capped):
    s = world["students"]
    for st in s[:4]:
        rsvp.rsvp(capped, st, NOW)
    promoted = rsvp.cancel(capped, s[0])
    assert promoted.student_id == s[2].id
    assert [r.student_id for r in rsvp.waitlist(capped)] == [s[3].id]
    assert rsvp.going_count(capped) == 2


def test_cancel_from_waitlist_promotes_nobody(world, capped):
    s = world["students"]
    for st in s[:3]:
        rsvp.rsvp(capped, st, NOW)
    assert rsvp.cancel(capped, s[2]) is None
    assert rsvp.going_count(capped) == 2


def test_rsvp_is_idempotent(world, capped):
    st = world["students"][0]
    first = rsvp.rsvp(capped, st, NOW)
    assert rsvp.rsvp(capped, st, NOW).id == first.id
    assert RSVP.query.count() == 1


def test_rejoin_after_cancel_goes_to_back_of_line(world, capped):
    s = world["students"]
    for st in s[:3]:
        rsvp.rsvp(capped, st, NOW)
    rsvp.cancel(capped, s[1])  # s2 promoted
    again = rsvp.rsvp(capped, s[1], NOW)
    assert again.status == "waitlisted"


def test_uninvited_cohort_rejected(world):
    ev = make_event([world["a"]], LATER)
    with pytest.raises(rsvp.RSVPError, match="not invited"):
        rsvp.rsvp(ev, world["students"][4], NOW)


def test_closed_after_start(world):
    ev = make_event([world["a"]], NOW - timedelta(hours=1))
    with pytest.raises(rsvp.RSVPError, match="closed"):
        rsvp.rsvp(ev, world["students"][0], NOW)


def test_cancel_without_rsvp_errors(world, capped):
    with pytest.raises(rsvp.RSVPError):
        rsvp.cancel(capped, world["students"][0])


def test_raising_capacity_promotes_in_order(world, capped):
    s = world["students"]
    for st in s[:5]:
        rsvp.rsvp(capped, st, NOW)
    promoted = rsvp.set_capacity(capped, 4)
    assert [r.student_id for r in promoted] == [s[2].id, s[3].id]
    assert [r.student_id for r in rsvp.waitlist(capped)] == [s[4].id]


def test_lowering_capacity_does_not_bump_anyone(world, capped):
    s = world["students"]
    rsvp.rsvp(capped, s[0], NOW)
    rsvp.rsvp(capped, s[1], NOW)
    rsvp.set_capacity(capped, 1)
    assert rsvp.going_count(capped) == 2
    assert rsvp.rsvp(capped, s[2], NOW).status == "waitlisted"
    with pytest.raises(rsvp.RSVPError):
        rsvp.set_capacity(capped, 0)
