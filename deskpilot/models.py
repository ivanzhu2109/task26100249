"""Data model for DeskPilot recurring schedules."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MAX_DURATION = timedelta(hours=72)


class Recurrence(enum.Enum):
    """How a schedule repeats. All recurrences are open-ended (no end date)."""

    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass(frozen=True)
class Schedule:
    """A single recurring schedule.

    ``start``/``end`` describe the first occurrence; every later occurrence
    keeps the same duration. Instants are Gregorian UTC, second precision.
    """

    id: str
    start: datetime
    end: datetime
    recurrence: Recurrence

    def __post_init__(self) -> None:
        if not isinstance(self.recurrence, Recurrence):
            raise TypeError(f"recurrence must be a Recurrence, got {self.recurrence!r}")
        for field_name, value in (("start", self.start), ("end", self.end)):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime, got {value!r}")
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{field_name} must be timezone-aware UTC, got {value!r}")
            if value.microsecond:
                raise ValueError(f"{field_name} must have whole-second precision, got {value!r}")
        if not self.id:
            raise ValueError("id must be a non-empty string")
        if self.duration <= timedelta(0):
            raise ValueError("duration must be positive (end must be after start)")
        if self.duration > MAX_DURATION:
            raise ValueError("duration must not exceed 72 hours")

    @property
    def duration(self) -> timedelta:
        """Length of each occurrence; identical for every occurrence."""
        return self.end - self.start

    def first_occurrence_utc(self) -> "Schedule":
        """Return an equivalent schedule normalized to the UTC timezone object."""
        return Schedule(
            id=self.id,
            start=self.start.astimezone(timezone.utc),
            end=self.end.astimezone(timezone.utc),
            recurrence=self.recurrence,
        )
