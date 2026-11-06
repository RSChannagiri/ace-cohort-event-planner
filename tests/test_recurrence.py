from datetime import date, datetime

import pytest

from ace_planner.recurrence import RecurrenceError, describe, expand, nth_weekday, parse_rrule

TUE = datetime(2026, 9, 22, 16, 0)  # a Tuesday


def test_weekly_until_is_inclusive():
    out = expand(TUE, "FREQ=WEEKLY;UNTIL=20261013")
    assert [d.date() for d in out] == [date(2026, 9, 22), date(2026, 9, 29), date(2026, 10, 6),
                                       date(2026, 10, 13)]
    assert all(d.time() == TUE.time() for d in out)


def test_weekly_byday_multiple_days_with_count():
    out = expand(TUE, "FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4")
    assert [d.strftime("%a %d") for d in out] == ["Tue 22", "Thu 24", "Tue 29", "Thu 01"]


def test_weekly_byday_skips_days_before_start_in_first_week():
    out = expand(TUE, "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=3")
    assert [d.date() for d in out] == [date(2026, 9, 23), date(2026, 9, 28), date(2026, 9, 30)]


def test_biweekly_interval():
    out = expand(TUE, "FREQ=WEEKLY;INTERVAL=2;COUNT=3")
    assert [d.day for d in out] == [22, 6, 20]


def test_daily_count():
    assert len(expand(TUE, "FREQ=DAILY;COUNT=5")) == 5


def test_monthly_first_thursday():
    out = expand(datetime(2026, 10, 1, 18), "FREQ=MONTHLY;BYDAY=1TH;COUNT=3")
    assert [d.date() for d in out] == [date(2026, 10, 1), date(2026, 11, 5), date(2026, 12, 3)]


def test_monthly_last_friday():
    out = expand(datetime(2026, 9, 1, 12), "FREQ=MONTHLY;BYDAY=-1FR;COUNT=2")
    assert [d.date() for d in out] == [date(2026, 9, 25), date(2026, 10, 30)]


def test_monthly_by_date_skips_short_months():
    out = expand(datetime(2027, 1, 31, 9), "FREQ=MONTHLY;UNTIL=20270430")
    assert [d.date() for d in out] == [date(2027, 1, 31), date(2027, 3, 31)]


def test_exdates_are_skipped_but_count_toward_count():
    out = expand(TUE, "FREQ=WEEKLY;COUNT=3", exdates={date(2026, 9, 29)})
    assert [d.day for d in out] == [22, 6]


def test_rrule_prefix_and_lowercase_accepted():
    assert parse_rrule("RRULE:freq=weekly;count=2")["FREQ"] == "WEEKLY"


def test_nth_weekday_missing_fifth_returns_none():
    assert nth_weekday(2026, 2, 0, 5) is None
    assert nth_weekday(2026, 3, 0, 5) == date(2026, 3, 30)


@pytest.mark.parametrize("rule, msg", [
    ("", "empty"),
    ("FREQ=YEARLY;COUNT=2", "FREQ"),
    ("FREQ=WEEKLY", "bounded"),
    ("FREQ=WEEKLY;COUNT=2;UNTIL=20261231", "not both"),
    ("FREQ=WEEKLY;COUNT=0", "positive"),
    ("FREQ=WEEKLY;COUNT=abc", "positive"),
    ("FREQ=WEEKLY;INTERVAL=-1;COUNT=2", "positive"),
    ("FREQ=WEEKLY;BYDAY=XX;COUNT=2", "BYDAY"),
    ("FREQ=WEEKLY;BYDAY=1MO;COUNT=2", "ordinal"),
    ("FREQ=MONTHLY;BYDAY=TH;COUNT=2", "ordinal weekday"),
    ("FREQ=DAILY;BYDAY=MO;COUNT=2", "DAILY"),
    ("FREQ=WEEKLY;UNTIL=2026-12", "YYYYMMDD"),
    ("FREQ=WEEKLY;COUNT=501", "exceed"),
    ("FREQ=WEEKLY;garbage", "Malformed"),
])
def test_invalid_rules_rejected(rule, msg):
    with pytest.raises(RecurrenceError, match=msg):
        parse_rrule(rule)


def test_until_before_start_yields_nothing():
    assert expand(TUE, "FREQ=WEEKLY;UNTIL=20260901") == []


def test_describe():
    assert describe("FREQ=WEEKLY;BYDAY=TU;UNTIL=20261208") == "Weekly on TU until 2026-12-08"
    assert describe("FREQ=WEEKLY;INTERVAL=2;COUNT=4") == "Every 2 weeks, 4 times"
