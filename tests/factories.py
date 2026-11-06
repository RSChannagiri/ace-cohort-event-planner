from __future__ import annotations

from datetime import datetime, timedelta

from ace_planner.models import Event
from ace_planner.scheduling import create_events


def make_event(cohorts, start: datetime, hours: float = 1, **kw) -> Event:
    kw.setdefault("title", "Test Event")
    kw.setdefault("event_type", "one_off")
    return create_events(start=start, end=start + timedelta(hours=hours),
                         cohort_ids=[c.id for c in cohorts], **kw)[0]
