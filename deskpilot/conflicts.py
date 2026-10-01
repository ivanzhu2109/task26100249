"""Conflict checking between a candidate schedule and stored schedules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Recurrence, Schedule
from .occurrences import iter_occurrences

# The Gregorian calendar repeats every 400 years (146097 days, a whole number
# of weeks), so any combination involving MONTHLY recurrences has an overlap
# pattern with this period.
_GREGORIAN_CYCLE = timedelta(days=146097)

_PERIOD = {
    Recurrence.DAILY: timedelta(days=1),
    Recurrence.WEEKLY: timedelta(days=7),
}


@dataclass(frozen=True)
class Conflict:
    """Evidence of the earliest overlap with one stored schedule."""

    schedule_id: str
    overlap_start: datetime
    candidate_occurrence: tuple[datetime, datetime]
    existing_occurrence: tuple[datetime, datetime]


def _cycle(a: Schedule, b: Schedule) -> timedelta:
    """Period after which the joint occurrence pattern of a and b repeats."""
    if a.recurrence is Recurrence.NONE or b.recurrence is Recurrence.NONE:
        return timedelta(0)
    pa = _PERIOD.get(a.recurrence)
    pb = _PERIOD.get(b.recurrence)
    if pa is not None and pb is not None:
        seconds = math.lcm(int(pa.total_seconds()), int(pb.total_seconds()))
        return timedelta(seconds=seconds)
    return _GREGORIAN_CYCLE


def earliest_overlap(a: Schedule, b: Schedule):
    """Earliest overlap between two schedules.

    Returns ``(overlap_start, occurrence_of_a, occurrence_of_b)`` for the
    chronologically first overlapping pair of occurrences, or ``None`` if the
    two schedules never overlap at any future instant.
    """
    # If any overlap exists, one occurs with overlap time no later than
    # max(starts) + cycle + durations: the joint pattern is periodic with
    # `cycle`, and any later overlapping pair can be shifted back one full
    # cycle into a still-valid earlier pair. So scanning past this horizon
    # proves there is no conflict, ever.
    horizon = max(a.start, b.start) + _cycle(a, b) + a.duration + b.duration

    occ_a = iter_occurrences(a)
    occ_b = iter_occurrences(b)
    try:
        cur_a = next(occ_a)
        cur_b = next(occ_b)
    except StopIteration:
        return None
    while True:
        a_start, a_end = cur_a
        b_start, b_end = cur_b
        if a_start < b_end and b_start < a_end:
            return max(a_start, b_start), cur_a, cur_b
        if min(a_start, b_start) > horizon:
            return None
        # No overlap yet: discard the occurrence that ends first; it can
        # never overlap any future occurrence of the other schedule.
        try:
            if a_end <= b_end:
                cur_a = next(occ_a)
            else:
                cur_b = next(occ_b)
        except StopIteration:
            return None


class ConflictChecker:
    """Holds existing schedules in memory and checks candidates against them.

    Checking never mutates the stored schedules, and stored schedules are
    not checked against each other.
    """

    def __init__(self, schedules: list[Schedule] | None = None) -> None:
        self._schedules: dict[str, Schedule] = {}
        for schedule in schedules or []:
            self.add(schedule)

    def add(self, schedule: Schedule) -> None:
        if schedule.id in self._schedules:
            raise ValueError(f"duplicate schedule id: {schedule.id!r}")
        self._schedules[schedule.id] = schedule

    def check(self, candidate: Schedule) -> list[Conflict]:
        """Return one Conflict per conflicting stored schedule; empty if none.

        Each Conflict carries the earliest overlap instant and the two
        occurrence intervals producing it.
        """
        conflicts: list[Conflict] = []
        for existing in self._schedules.values():
            if existing.id == candidate.id:
                continue
            result = earliest_overlap(candidate, existing)
            if result is not None:
                overlap_start, candidate_occ, existing_occ = result
                conflicts.append(
                    Conflict(
                        schedule_id=existing.id,
                        overlap_start=overlap_start,
                        candidate_occurrence=candidate_occ,
                        existing_occurrence=existing_occ,
                    )
                )
        conflicts.sort(key=lambda c: (c.overlap_start, c.schedule_id))
        return conflicts
