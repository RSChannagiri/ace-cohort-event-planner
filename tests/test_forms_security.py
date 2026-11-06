from datetime import date, datetime

import pytest

from ace_planner.forms import (
    FormError,
    parse_date,
    parse_datetime,
    parse_exdates,
    parse_id_list,
    parse_optional_int,
)
from ace_planner.security import is_safe_next


def test_parse_datetime():
    assert parse_datetime("2026-11-10", "16:30") == datetime(2026, 11, 10, 16, 30)
    with pytest.raises(FormError, match="Start"):
        parse_datetime("2026-13-10", "16:30", "Start")


def test_parse_date_and_exdates():
    assert parse_date(" 2026-11-26 ") == date(2026, 11, 26)
    assert parse_exdates("2026-11-26, 2026-11-27\n2026-11-26") == {date(2026, 11, 26),
                                                                   date(2026, 11, 27)}
    assert parse_exdates("") == set()
    with pytest.raises(FormError):
        parse_exdates("next tuesday")


def test_parse_ints():
    assert parse_optional_int("", "Capacity") is None
    assert parse_optional_int("40", "Capacity") == 40
    with pytest.raises(FormError, match="whole number"):
        parse_optional_int("4.5", "Capacity")
    assert parse_id_list(["3", "1", "3", ""]) == [1, 3]
    with pytest.raises(FormError):
        parse_id_list(["x"])


@pytest.mark.parametrize("target, ok", [
    ("/events/3", True), ("/participation?at_risk=1", True),
    ("https://evil.example.com", False), ("//evil.example.com", False),
    ("/\\evil.example.com", False), ("events", False), ("", False), (None, False),
])
def test_is_safe_next(target, ok):
    assert is_safe_next(target) is ok
