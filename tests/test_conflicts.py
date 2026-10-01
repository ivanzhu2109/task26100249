from datetime import datetime, timedelta, timezone
from itertools import islice

import pytest

from deskpilot import ConflictChecker, Recurrence, Schedule
from deskpilot.core import _occurrences

UTC = timezone.utc


def dt(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def brute_force_first_overlap(a, b, window_start, window_end):
    """Enumerate occurrences inside [window_start, window_end] and find the
    earliest overlapping pair by exhaustive comparison."""
    limit = window_end + timedelta(hours=72)
    occs_a = [o for o in _occurrences(a, limit) if o.end > window_start]
    occs_b = [o for o in _occurrences(b, limit) if o.end > window_start]
    best = None
    for oa in occs_a:
        for ob in occs_b:
            if oa.start < ob.end and ob.start < oa.end:
                moment = max(oa.start, ob.start)
                if moment >= window_end:
                    continue
                if best is None or moment < best[0]:
                    best = (moment, oa, ob)
    return best


def test_spec_monthly31_vs_weekly_thursday():
    existing = Schedule("monthly-31", dt(2021, 1, 31, 9), dt(2021, 1, 31, 10), Recurrence.MONTHLY)
    candidate = Schedule("weekly", dt(2021, 2, 4, 9, 30), dt(2021, 2, 4, 10, 30), Recurrence.WEEKLY)
    result = ConflictChecker([existing]).check(candidate)
    assert result.has_conflict
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.schedule_id == "monthly-31"
    assert conflict.overlap_start == dt(2022, 3, 31, 9, 30)
    assert conflict.existing_occurrence.start == dt(2022, 3, 31, 9)
    assert conflict.existing_occurrence.end == dt(2022, 3, 31, 10)
    assert conflict.candidate_occurrence.start == dt(2022, 3, 31, 9, 30)
    assert conflict.candidate_occurrence.end == dt(2022, 3, 31, 10, 30)


def test_monthly_skips_months_without_day_31():
    s = Schedule("m", dt(2021, 1, 31, 9), dt(2021, 1, 31, 10), Recurrence.MONTHLY)
    starts = [o.start for o in islice(_occurrences(s), 6)]
    assert starts == [
        dt(2021, 1, 31, 9),
        dt(2021, 3, 31, 9),
        dt(2021, 5, 31, 9),
        dt(2021, 7, 31, 9),
        dt(2021, 8, 31, 9),
        dt(2021, 10, 31, 9),
    ]


def test_monthly_29_skips_feb_2100_not_leap_year():
    s = Schedule("m29", dt(2100, 1, 29, 8), dt(2100, 1, 29, 9), Recurrence.MONTHLY)
    starts = [o.start for o in islice(_occurrences(s), 4)]
    assert starts == [dt(2100, 1, 29, 8), dt(2100, 3, 29, 8), dt(2100, 4, 29, 8), dt(2100, 5, 29, 8)]
    # 2400 is a leap year (divisible by 400): Feb 29 occurs.
    s2 = Schedule("m29b", dt(2400, 1, 29, 8), dt(2400, 1, 29, 9), Recurrence.MONTHLY)
    starts2 = [o.start for o in islice(_occurrences(s2), 2)]
    assert starts2 == [dt(2400, 1, 29, 8), dt(2400, 2, 29, 8)]


def test_touching_endpoints_are_not_conflict():
    a = Schedule("a", dt(2021, 1, 31, 9), dt(2021, 1, 31, 10), Recurrence.NONE)
    b = Schedule("b", dt(2021, 1, 31, 10), dt(2021, 1, 31, 11), Recurrence.NONE)
    assert not ConflictChecker([a]).check(b).has_conflict
    assert not ConflictChecker([b]).check(a).has_conflict
    # Recurring back-to-back: weekly 09:00-10:00 vs weekly 10:00-11:00 same day.
    c = Schedule("c", dt(2021, 2, 4, 9), dt(2021, 2, 4, 10), Recurrence.WEEKLY)
    d = Schedule("d", dt(2021, 2, 4, 10), dt(2021, 2, 4, 11), Recurrence.WEEKLY)
    assert not ConflictChecker([c]).check(d).has_conflict


def test_72h_duration_crosses_month_boundary():
    existing = Schedule("long", dt(2021, 1, 30, 9), dt(2021, 2, 2, 9), Recurrence.MONTHLY)
    assert existing.duration == timedelta(hours=72)
    candidate = Schedule("one-off", dt(2021, 2, 1, 0), dt(2021, 2, 1, 1), Recurrence.NONE)
    result = ConflictChecker([existing]).check(candidate)
    assert result.has_conflict
    conflict = result.conflicts[0]
    assert conflict.overlap_start == dt(2021, 2, 1, 0)
    assert conflict.existing_occurrence.start == dt(2021, 1, 30, 9)
    assert conflict.existing_occurrence.end == dt(2021, 2, 2, 9)


def test_self_overlapping_schedule_still_checked_correctly():
    # Daily with 48h duration overlaps itself; a weekly candidate far from the
    # first occurrence still collides once the dense coverage begins.
    existing = Schedule("dense", dt(2021, 1, 1, 9), dt(2021, 1, 3, 9), Recurrence.DAILY)
    candidate = Schedule("weekly", dt(2021, 6, 3, 9, 30), dt(2021, 6, 3, 10, 30), Recurrence.WEEKLY)
    result = ConflictChecker([existing]).check(candidate)
    assert result.has_conflict
    assert result.conflicts[0].overlap_start == dt(2021, 6, 3, 9, 30)


def test_definite_no_conflict():
    existing = Schedule("m", dt(2021, 1, 31, 9), dt(2021, 1, 31, 10), Recurrence.MONTHLY)
    candidate = Schedule("d", dt(2021, 2, 1, 12), dt(2021, 2, 1, 13), Recurrence.DAILY)
    result = ConflictChecker([existing]).check(candidate)
    assert not result.has_conflict
    assert result.conflicts == ()


def test_multiple_existing_each_reported_once_with_earliest_evidence():
    e1 = Schedule("e1", dt(2021, 1, 1, 9), dt(2021, 1, 1, 10), Recurrence.DAILY)
    e2 = Schedule("e2", dt(2021, 1, 1, 9, 30), dt(2021, 1, 1, 10, 30), Recurrence.DAILY)
    e3 = Schedule("e3", dt(2021, 1, 1, 20), dt(2021, 1, 1, 21), Recurrence.DAILY)
    candidate = Schedule("c", dt(2021, 1, 1, 9, 45), dt(2021, 1, 1, 10, 45), Recurrence.NONE)
    result = ConflictChecker([e1, e2, e3]).check(candidate)
    assert [c.schedule_id for c in result.conflicts] == ["e1", "e2"]
    assert result.conflicts[0].overlap_start == dt(2021, 1, 1, 9, 45)
    assert result.conflicts[1].overlap_start == dt(2021, 1, 1, 9, 45)


def test_check_does_not_mutate_and_ignores_existing_vs_existing():
    e1 = Schedule("e1", dt(2021, 1, 1, 9), dt(2021, 1, 1, 10), Recurrence.DAILY)
    e2 = Schedule("e2", dt(2021, 1, 1, 9, 30), dt(2021, 1, 1, 10, 30), Recurrence.DAILY)
    checker = ConflictChecker([e1, e2])  # e1/e2 conflict with each other; never reported
    free = Schedule("c", dt(2021, 1, 1, 12), dt(2021, 1, 1, 13), Recurrence.NONE)
    result = checker.check(free)
    assert not result.has_conflict
    again = checker.check(free)
    assert not again.has_conflict


def test_validation():
    with pytest.raises(ValueError):
        Schedule("x", dt(2021, 1, 1), dt(2021, 1, 1), Recurrence.NONE)  # zero duration
    with pytest.raises(ValueError):
        Schedule("x", dt(2021, 1, 1), dt(2021, 1, 4, 0, 0, 1), Recurrence.NONE)  # > 72h
    with pytest.raises(ValueError):
        Schedule("x", datetime(2021, 1, 1), datetime(2021, 1, 1, 1), Recurrence.NONE)  # naive
    with pytest.raises(ValueError):
        Schedule(  # sub-second precision rejected
            "x",
            datetime(2021, 1, 1, 0, 0, 0, 1, tzinfo=UTC),
            dt(2021, 1, 1, 1),
            Recurrence.NONE,
        )
    ok = Schedule("x", dt(2021, 1, 1), dt(2021, 1, 4), Recurrence.NONE)  # exactly 72h
    assert ok.duration == timedelta(hours=72)


def test_combo_cross_checked_against_enumeration():
    """Month-end gaps + 72h cross-month duration + Feb 2100 + touching
    intervals, verified against brute-force occurrence enumeration."""
    existing = [
        # Monthly on the 31st, 72h: skips Feb/Apr/..., spills into next month.
        Schedule("m31-long", dt(2021, 1, 30, 9), dt(2021, 2, 2, 9), Recurrence.MONTHLY),
        # Monthly on the 29th across the non-leap Feb 2100; collides with the
        # weekly candidate whenever the 29th falls on a Thursday.
        Schedule("m29-2100", dt(2099, 12, 29, 9), dt(2099, 12, 29, 10), Recurrence.MONTHLY),
        # Weekly, back-to-back with the candidate's first occurrence.
        Schedule("w-touch", dt(2021, 2, 4, 10, 30), dt(2021, 2, 4, 11, 30), Recurrence.WEEKLY),
    ]
    candidate = Schedule(
        "cand", dt(2021, 2, 4, 9, 30), dt(2021, 2, 4, 10, 30), Recurrence.WEEKLY
    )
    checker = ConflictChecker(existing)
    result = checker.check(candidate)

    window_start = dt(2021, 1, 1)
    window_end = dt(2101, 1, 1)
    for conflict in result.conflicts:
        matched = next(s for s in existing if s.schedule_id == conflict.schedule_id)
        expected = brute_force_first_overlap(matched, candidate, window_start, window_end)
        assert expected is not None, conflict.schedule_id
        moment, occ_existing, occ_candidate = expected
        assert conflict.overlap_start == moment
        assert conflict.existing_occurrence == occ_existing
        assert conflict.candidate_occurrence == occ_candidate

    # w-touch only ever touches the candidate's endpoints: no conflict, and
    # brute force agrees there is none inside the window.
    assert "w-touch" not in {c.schedule_id for c in result.conflicts}
    touch = existing[2]
    assert brute_force_first_overlap(touch, candidate, window_start, window_end) is None

    # The two real conflicts, confirmed by enumeration.
    assert {c.schedule_id for c in result.conflicts} == {"m31-long", "m29-2100"}
