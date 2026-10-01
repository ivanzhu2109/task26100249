"""DeskPilot recurring-schedule conflict checking library.

Schedules live only in process memory. The upper layer calls this library
before saving a schedule to learn which existing schedules conflict with a
candidate and to obtain evidence of the first collision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterator, Optional

UTC = timezone.utc

MAX_DURATION = timedelta(hours=72)
_GREGORIAN_CYCLE_DAYS = 146097  # 400-year Gregorian leap cycle


class Recurrence(Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    start: datetime
    end: datetime
    recurrence: Recurrence

    def __post_init__(self) -> None:
        for field_name, value in (("start", self.start), ("end", self.end)):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{field_name} must be timezone-aware UTC")
            if value.microsecond != 0:
                raise ValueError(f"{field_name} must be precise to whole seconds")
        if not self.schedule_id:
            raise ValueError("schedule_id must be non-empty")
        if not isinstance(self.recurrence, Recurrence):
            raise ValueError("recurrence must be a Recurrence")
        if self.end <= self.start:
            raise ValueError("duration must be positive")
        if self.end - self.start > MAX_DURATION:
            raise ValueError("duration must not exceed 72 hours")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class Occurrence:
    """One concrete occurrence interval: [start, end)."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class Conflict:
    schedule_id: str
    overlap_start: datetime
    existing_occurrence: Occurrence
    candidate_occurrence: Occurrence


@dataclass(frozen=True)
class CheckResult:
    candidate_id: str
    conflicts: tuple[Conflict, ...]

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=UTC)
    cur = datetime(year, month, 1, tzinfo=UTC)
    return (nxt - cur).days


def _occurrences(schedule: Schedule, limit: Optional[datetime] = None) -> Iterator[Occurrence]:
    """Yield occurrence intervals [start, end) in ascending order.

    Stops once an occurrence starts at or after limit (if given).
    """
    duration = schedule.duration
    start = schedule.start

    if schedule.recurrence is Recurrence.NONE:
        if limit is None or start < limit:
            yield Occurrence(start, start + duration)
        return

    if schedule.recurrence is Recurrence.MONTHLY:
        year, month = start.year, start.month
        day = start.day
        while True:
            if day <= _days_in_month(year, month):
                occ_start = start.replace(year=year, month=month)
                if limit is not None and occ_start >= limit:
                    return
                yield Occurrence(occ_start, occ_start + duration)
            month += 1
            if month == 13:
                month = 1
                year += 1
        return

    step = timedelta(days=1) if schedule.recurrence is Recurrence.DAILY else timedelta(days=7)
    occ_start = start
    while limit is None or occ_start < limit:
        yield Occurrence(occ_start, occ_start + duration)
        occ_start += step


def _pair_period(a: Schedule, b: Schedule) -> timedelta:
    """Combined repeat period of two recurring (non-NONE) schedules.

    Daily/weekly patterns repeat every lcm(1, 7) = 1 or 7 days. Anything
    involving a monthly schedule repeats every 400-year Gregorian cycle.
    """
    if Recurrence.MONTHLY in (a.recurrence, b.recurrence):
        return timedelta(days=_GREGORIAN_CYCLE_DAYS)
    days_a = 1 if a.recurrence is Recurrence.DAILY else 7
    days_b = 1 if b.recurrence is Recurrence.DAILY else 7
    return timedelta(days=max(days_a, days_b) if days_a != days_b else days_a)


def _first_overlap(a: Schedule, b: Schedule) -> Optional[tuple]:
    """Earliest overlap between occurrences of a and b.

    Returns (overlap_start, occurrence_of_a, occurrence_of_b) or None when
    the two schedules provably never overlap. Half-open intervals: touching
    endpoints do not count as overlap.
    """
    if a.recurrence is Recurrence.NONE and b.recurrence is Recurrence.NONE:
        limit_a = limit_b = None
    elif a.recurrence is Recurrence.NONE:
        limit_a, limit_b = None, a.end
    elif b.recurrence is Recurrence.NONE:
        limit_a, limit_b = b.end, None
    else:
        horizon = max(a.start, b.start) + _pair_period(a, b)
        limit_a = limit_b = horizon

    iter_a = _occurrences(a, limit_a)
    iter_b = _occurrences(b, limit_b)
    occ_a = next(iter_a, None)
    occ_b = next(iter_b, None)
    while occ_a is not None and occ_b is not None:
        if occ_a.end <= occ_b.start:
            occ_a = next(iter_a, None)
        elif occ_b.end <= occ_a.start:
            occ_b = next(iter_b, None)
        else:
            return (max(occ_a.start, occ_b.start), occ_a, occ_b)
    return None


class ConflictChecker:
    """Holds existing schedules in memory and checks candidates against them.

    Checking never mutates existing data, and existing schedules are never
    checked against each other.
    """

    def __init__(self, existing: Optional[list] = None) -> None:
        self._existing: list[Schedule] = []
        if existing:
            self.load_existing(existing)

    def load_existing(self, schedules: list) -> None:
        ids = {s.schedule_id for s in self._existing}
        for schedule in schedules:
            if not isinstance(schedule, Schedule):
                raise TypeError("expected Schedule instances")
            if schedule.schedule_id in ids:
                raise ValueError(f"duplicate schedule_id: {schedule.schedule_id}")
            ids.add(schedule.schedule_id)
            self._existing.append(schedule)

    def check(self, candidate: Schedule) -> CheckResult:
        if not isinstance(candidate, Schedule):
            raise TypeError("expected a Schedule instance")
        conflicts = []
        for existing in self._existing:
            if existing.schedule_id == candidate.schedule_id:
                continue
            hit = _first_overlap(existing, candidate)
            if hit is not None:
                overlap_start, occ_existing, occ_candidate = hit
                conflicts.append(
                    Conflict(
                        schedule_id=existing.schedule_id,
                        overlap_start=overlap_start,
                        existing_occurrence=occ_existing,
                        candidate_occurrence=occ_candidate,
                    )
                )
        conflicts.sort(key=lambda c: (c.overlap_start, c.schedule_id))
        return CheckResult(candidate_id=candidate.schedule_id, conflicts=tuple(conflicts))
