"""Attendance-rate aggregations by event type, cohort, and month."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .models import EVENT_TYPE_LABELS, Attendance, Cohort, Event, Student, db


@dataclass(frozen=True)
class Rate:
    label: str
    present: int
    total: int

    @property
    def percent(self) -> float:
        return round(100 * self.present / self.total, 1) if self.total else 0.0


def _rows():
    return (db.session.query(Attendance.present, Event.event_type, Event.start, Cohort.name)
            .join(Event, Attendance.event_id == Event.id)
            .join(Student, Attendance.student_id == Student.id)
            .join(Cohort, Student.cohort_id == Cohort.id).all())


def attendance_rates() -> dict[str, list[Rate]]:
    """Attendance rates keyed by ``by_type``, ``by_cohort`` and ``by_month``."""
    buckets: dict[str, dict[str, list[int]]] = {
        "by_type": defaultdict(lambda: [0, 0]),
        "by_cohort": defaultdict(lambda: [0, 0]),
        "by_month": defaultdict(lambda: [0, 0]),
    }
    for present, event_type, start, cohort_name in _rows():
        keys = {"by_type": event_type, "by_cohort": cohort_name,
                "by_month": start.strftime("%Y-%m")}
        for bucket, key in keys.items():
            buckets[bucket][key][0] += int(present)
            buckets[bucket][key][1] += 1
    out: dict[str, list[Rate]] = {}
    for name, bucket in buckets.items():
        out[name] = [Rate(EVENT_TYPE_LABELS.get(k, k) if name == "by_type" else k, p, t)
                     for k, (p, t) in sorted(bucket.items())]
    return out


def overall_rate() -> Rate:
    rows = _rows()
    return Rate("Overall", sum(int(r[0]) for r in rows), len(rows))
