"""Occurrence enumeration for recurring schedules."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta
from typing import Iterator

from .models import Recurrence, Schedule


def _iter_starts(schedule: Schedule) -> Iterator[datetime]:
    """Yield occurrence start instants in ascending order, forever if recurring."""
    start = schedule.start
    recurrence = schedule.recurrence
    if recurrence is Recurrence.NONE:
        yield start
        return
    if recurrence is Recurrence.DAILY:
        step = timedelta(days=1)
        current = start
        while True:
            yield current
            current += step
    elif recurrence is Recurrence.WEEKLY:
        step = timedelta(days=7)
        current = start
        while True:
            yield current
            current += step
    else:  # MONTHLY: keep the original day-of-month and time-of-day; skip
        # months that do not contain the day (never clamp to month end).
        year, month, day = start.year, start.month, start.day
        while True:
            if day <= monthrange(year, month)[1]:
                yield start.replace(year=year, month=month)
            month += 1
            if month == 13:
                month = 1
                year += 1


def iter_occurrences(schedule: Schedule) -> Iterator[tuple[datetime, datetime]]:
    """Yield ``(start, end)`` of every occurrence, in ascending start order.

    Each occurrence keeps the first occurrence's exact duration, so an
    occurrence may cross day or month boundaries and may overlap later
    occurrences of the same schedule.
    """
    duration = schedule.duration
    for start in _iter_starts(schedule):
        yield start, start + duration


def occurrences_between(
    schedule: Schedule, window_start: datetime, window_end: datetime
) -> list[tuple[datetime, datetime]]:
    """List occurrences overlapping the half-open window [window_start, window_end).

    An occurrence [s, e) is included iff s < window_end and e > window_start.
    """
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    result: list[tuple[datetime, datetime]] = []
    for start, end in iter_occurrences(schedule):
        if start >= window_end:
            break
        if end > window_start:
            result.append((start, end))
    return result
