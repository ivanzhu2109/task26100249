"""Automated tests for the DeskPilot conflict-checking library."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deskpilot import (
    ConflictChecker,
    Recurrence,
    Schedule,
    iter_occurrences,
    occurrences_between,
)
from deskpilot.conflicts import earliest_overlap

UTC = timezone.utc


def dt(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def sched(id, start, hours, recurrence):
    return Schedule(id, start, start + timedelta(hours=hours), recurrence)


def brute_force_earliest_overlap(a, b, window_start, window_end):
    """Independently enumerate occurrences in a bounded window and find the
    earliest overlap by pairwise comparison."""
    best = None
    for a_occ in occurrences_between(a, window_start, window_end):
        for b_occ in occurrences_between(b, window_start, window_end):
            lo = max(a_occ[0], b_occ[0])
            hi = min(a_occ[1], b_occ[1])
            if lo < hi and (best is None or lo < best[0]):
                best = (lo, a_occ, b_occ)
    return best


def assert_matches_brute_force(a, b, window_start, window_end):
    """The library's earliest-overlap evidence must agree with an explicit
    occurrence-by-occurrence enumeration over a bounded check window."""
    expected = brute_force_earliest_overlap(a, b, window_start, window_end)
    result = earliest_overlap(a, b)
    if expected is None:
        assert result is None
    else:
        assert result is not None
        overlap_start, a_occ, b_occ = result
        assert overlap_start == expected[0]
        assert a_occ == expected[1]
        assert b_occ == expected[2]
        # Evidence must be a genuine overlap.
        assert a_occ[0] < b_occ[1] and b_occ[0] < a_occ[1]
        assert overlap_start == max(a_occ[0], b_occ[0])


# ---------------------------------------------------------------------------
# Required scenario: monthly on the 31st vs weekly on Thursday.
# ---------------------------------------------------------------------------

def test_monthly_31st_vs_weekly_thursday_first_conflict_2022_03_31():
    existing = sched("monthly-31", dt(2021, 1, 31, 9), 1, Recurrence.MONTHLY)
    candidate = sched("weekly-thu", dt(2021, 2, 4, 9, 30), 1, Recurrence.WEEKLY)

    conflicts = ConflictChecker([existing]).check(candidate)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.schedule_id == "monthly-31"
    assert conflict.overlap_start == dt(2022, 3, 31, 9, 30)
    assert conflict.existing_occurrence == (dt(2022, 3, 31, 9), dt(2022, 3, 31, 10))
    assert conflict.candidate_occurrence == (dt(2022, 3, 31, 9, 30), dt(2022, 3, 31, 10, 30))


def test_check_does_not_mutate_and_ignores_existing_pairs():
    # Two stored schedules that conflict with each other; the checker must
    # not report their mutual conflict, only candidate-vs-stored ones.
    a = sched("a", dt(2024, 1, 1, 9), 2, Recurrence.DAILY)
    b = sched("b", dt(2024, 1, 1, 10), 2, Recurrence.DAILY)
    checker = ConflictChecker([a, b])
    far_away = sched("c", dt(2030, 6, 1, 13), 1, Recurrence.NONE)
    assert checker.check(far_away) == []
    # Stored data is unchanged by checks.
    checker.check(a)
    assert checker.check(sched("d", dt(2024, 1, 1, 9, 30), 1, Recurrence.NONE))
    assert [s.id for s in checker._schedules.values()] == ["a", "b"]


# ---------------------------------------------------------------------------
# Occurrence enumeration rules.
# ---------------------------------------------------------------------------

def test_monthly_skips_missing_months_without_clamping():
    m = sched("m", dt(2021, 1, 31, 9), 1, Recurrence.MONTHLY)
    starts = [s for s, _ in occurrences_between(m, dt(2021, 1, 1), dt(2022, 1, 1))]
    assert [s.date().isoformat() for s in starts] == [
        "2021-01-31", "2021-03-31", "2021-05-31", "2021-07-31",
        "2021-08-31", "2021-10-31", "2021-12-31",
    ]
    # Day-of-month is preserved after skipped months (no drift to the 30th).
    assert all(s.day == 31 for s in starts)


def test_monthly_feb_2100_is_not_a_leap_year():
    m = sched("m", dt(2099, 1, 29, 8), 1, Recurrence.MONTHLY)
    starts = [s for s, _ in occurrences_between(m, dt(2100, 1, 1), dt(2101, 1, 1))]
    feb = [s for s in starts if s.month == 2]
    assert feb == []  # 2100 is divisible by 100 but not 400: no Feb 29.
    assert dt(2100, 1, 29, 8) in starts and dt(2100, 3, 29, 8) in starts


def test_monthly_feb_2000_leap_year_keeps_feb_29():
    m = sched("m", dt(2000, 1, 29, 8), 1, Recurrence.MONTHLY)
    starts = [s for s, _ in occurrences_between(m, dt(2000, 1, 1), dt(2001, 1, 1))]
    assert dt(2000, 2, 29, 8) in starts


def test_no_occurrences_before_first_start():
    d = sched("d", dt(2024, 3, 3, 12), 1, Recurrence.DAILY)
    assert occurrences_between(d, dt(2020, 1, 1), dt(2024, 3, 3, 12)) == []


def test_none_recurs_exactly_once():
    n = sched("n", dt(2024, 1, 1), 1, Recurrence.NONE)
    assert len(list(iter_occurrences(n))) == 1


# ---------------------------------------------------------------------------
# Half-open interval semantics.
# ---------------------------------------------------------------------------

def test_touching_intervals_do_not_conflict():
    a = sched("a", dt(2024, 1, 1, 9), 1, Recurrence.DAILY)
    b = sched("b", dt(2024, 1, 1, 10), 1, Recurrence.DAILY)
    assert earliest_overlap(a, b) is None
    assert ConflictChecker([a]).check(b) == []


def test_one_second_overlap_conflicts():
    a = sched("a", dt(2024, 1, 1, 9), 1, Recurrence.DAILY)
    b = sched("b", dt(2024, 1, 1, 9, 59, 59), 1, Recurrence.DAILY)
    result = earliest_overlap(a, b)
    assert result is not None
    assert result[0] == dt(2024, 1, 1, 9, 59, 59)


# ---------------------------------------------------------------------------
# Self-overlap and long durations.
# ---------------------------------------------------------------------------

def test_self_overlap_does_not_create_phantom_conflict():
    # 72-hour duration with daily recurrence overlaps itself heavily, but a
    # disjoint candidate must still be reported conflict-free.
    a = sched("a", dt(2024, 1, 1, 0), 72, Recurrence.DAILY)
    b = sched("b", dt(2024, 1, 10, 4), 1, Recurrence.NONE)
    # b sits inside a's occurrences? a covers everything from Jan 1 on with
    # only 0-gap... use a candidate before a starts instead.
    before = sched("c", dt(2023, 12, 31, 20), 1, Recurrence.NONE)
    assert ConflictChecker([a]).check(before) == []
    assert ConflictChecker([a]).check(b) != []


def test_72h_duration_crossing_month_boundary():
    # Occurrence starting Jan 31 09:00 lasts 72h, ending Feb 3 09:00.
    a = sched("a", dt(2021, 1, 31, 9), 72, Recurrence.MONTHLY)
    b = sched("b", dt(2021, 2, 2, 12), 1, Recurrence.NONE)
    result = earliest_overlap(a, b)
    assert result is not None
    assert result[0] == dt(2021, 2, 2, 12)
    assert result[1] == (dt(2021, 1, 31, 9), dt(2021, 2, 3, 9))


# ---------------------------------------------------------------------------
# Combined scenario cross-checked against brute-force enumeration.
# ---------------------------------------------------------------------------

def test_combined_scenarios_match_brute_force():
    cases = [
        # Monthly on the 31st (skips months) vs weekly Thursday.
        (
            sched("m31", dt(2021, 1, 31, 9), 1, Recurrence.MONTHLY),
            sched("wthu", dt(2021, 2, 4, 9, 30), 1, Recurrence.WEEKLY),
            dt(2021, 1, 1), dt(2023, 1, 1),
        ),
        # 72-hour monthly occurrence crossing month ends vs daily.
        (
            sched("m72", dt(2021, 1, 30, 10), 72, Recurrence.MONTHLY),
            sched("d1", dt(2021, 1, 15, 12), 1, Recurrence.DAILY),
            dt(2021, 1, 1), dt(2021, 7, 1),
        ),
        # Feb 2100 (not a leap year): monthly on the 29th vs weekly.
        (
            sched("m29", dt(2099, 11, 29, 7), 2, Recurrence.MONTHLY),
            sched("w1", dt(2099, 11, 1, 8), 2, Recurrence.WEEKLY),
            dt(2099, 11, 1), dt(2101, 1, 1),
        ),
        # Touching intervals: weekly ending exactly when monthly starts.
        (
            sched("mt", dt(2024, 2, 5, 10), 1, Recurrence.MONTHLY),
            sched("wt", dt(2024, 1, 1, 9), 1, Recurrence.WEEKLY),
            dt(2024, 1, 1), dt(2025, 1, 1),
        ),
        # Never conflicting: daily schedules at different hours.
        (
            sched("d9", dt(2024, 1, 1, 9), 1, Recurrence.DAILY),
            sched("d12", dt(2024, 1, 1, 12), 1, Recurrence.DAILY),
            dt(2024, 1, 1), dt(2025, 1, 1),
        ),
        # Single occurrence vs open-ended monthly.
        (
            sched("once", dt(2021, 4, 30, 9, 30), 1, Recurrence.NONE),
            sched("m30", dt(2021, 1, 30, 9), 1, Recurrence.MONTHLY),
            dt(2021, 1, 1), dt(2022, 1, 1),
        ),
    ]
    for a, b, lo, hi in cases:
        assert_matches_brute_force(a, b, lo, hi)
        assert_matches_brute_force(b, a, lo, hi)


def test_checker_reports_each_conflicting_schedule_once():
    existing = [
        sched("m31", dt(2021, 1, 31, 9), 1, Recurrence.MONTHLY),
        sched("d10", dt(2021, 1, 1, 10), 1, Recurrence.DAILY),
        sched("d20", dt(2021, 1, 1, 20), 1, Recurrence.DAILY),  # never hit
    ]
    candidate = sched("wthu", dt(2021, 2, 4, 9, 30), 1, Recurrence.WEEKLY)
    conflicts = ConflictChecker(existing).check(candidate)
    by_id = {c.schedule_id: c for c in conflicts}
    assert set(by_id) == {"m31", "d10"}
    assert by_id["m31"].overlap_start == dt(2022, 3, 31, 9, 30)
    # d10 (10:00-11:00 daily) first meets the Thursday 09:30-10:30 slot at
    # 10:00 on the candidate's first day.
    assert by_id["d10"].overlap_start == dt(2021, 2, 4, 10)


# ---------------------------------------------------------------------------
# Validation.
# ---------------------------------------------------------------------------

def test_validation_rejects_bad_schedules():
    with pytest.raises(ValueError):
        sched("x", dt(2024, 1, 1), 0, Recurrence.DAILY)
    with pytest.raises(ValueError):
        sched("x", dt(2024, 1, 1), 73, Recurrence.DAILY)
    with pytest.raises(ValueError):
        Schedule("x", datetime(2024, 1, 1), dt(2024, 1, 1, 1), Recurrence.DAILY)
    with pytest.raises(ValueError):
        Schedule("x", dt(2024, 1, 1), dt(2024, 1, 1, 1), Recurrence.DAILY).__class__(
            "", dt(2024, 1, 1), dt(2024, 1, 1, 1), Recurrence.DAILY)
    with pytest.raises(ValueError):
        ConflictChecker([sched("dup", dt(2024, 1, 1), 1, Recurrence.NONE),
                         sched("dup", dt(2024, 1, 2), 1, Recurrence.NONE)])
