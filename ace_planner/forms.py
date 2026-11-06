"""Pure helpers that turn raw form strings into typed values (no Flask imports)."""

from __future__ import annotations

from datetime import date, datetime


class FormError(ValueError):
    """Raised when a submitted form field cannot be parsed."""


def parse_datetime(day: str, time: str, label: str = "Date") -> datetime:
    try:
        return datetime.strptime(f"{day.strip()} {time.strip()}", "%Y-%m-%d %H:%M")
    except (ValueError, AttributeError) as exc:
        raise FormError(f"{label} must be a valid date and time") from exc


def parse_date(value: str, label: str = "Date") -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError) as exc:
        raise FormError(f"{label} must be YYYY-MM-DD") from exc


def parse_optional_int(value: str | None, label: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise FormError(f"{label} must be a whole number") from exc


def parse_id_list(values: list[str]) -> list[int]:
    try:
        return sorted({int(v) for v in values if v.strip()})
    except ValueError as exc:
        raise FormError("Invalid selection") from exc


def parse_exdates(value: str) -> set[date]:
    """Comma or newline separated YYYY-MM-DD dates to skip (holidays, breaks)."""
    tokens = [t.strip() for t in value.replace("\n", ",").split(",") if t.strip()]
    return {parse_date(t, "Skip date") for t in tokens}
