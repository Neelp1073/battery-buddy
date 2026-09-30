"""Battery analytics computed from a device's readings history.

All functions are pure (no Flask, no database) so they are easy to test
and are mirrored by the pandas version in analysis/analyze.py.

A *reading* is a dict with:
    ts           timezone-aware datetime
    percent      int, 0-100
    is_charging  bool

Readings are consecutive samples, so the interval between two readings
is attributed to the state of the *earlier* reading. Intervals longer
than ``max_gap_hours`` (device asleep, sender not running, backend down)
are ignored because we do not know what happened in between.
"""
from datetime import datetime

DEFAULT_MAX_GAP_HOURS = 1.0


def parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp as stored in the database."""
    return datetime.fromisoformat(value)


def _intervals(readings, max_gap_hours):
    """Yield (previous, current, hours) for consecutive readings within the gap limit."""
    for prev, cur in zip(readings, readings[1:]):
        hours = (cur["ts"] - prev["ts"]).total_seconds() / 3600
        if 0 < hours <= max_gap_hours:
            yield prev, cur, hours


def drain_rate_per_hour(readings, max_gap_hours=DEFAULT_MAX_GAP_HOURS):
    """Average battery drain in percentage points per hour while on battery.

    Uses intervals where both endpoints are not charging:
    total % lost / total hours on battery. Returns None if there is no
    usable on-battery interval.
    """
    lost = 0.0
    hours_total = 0.0
    for prev, cur, hours in _intervals(readings, max_gap_hours):
        if not prev["is_charging"] and not cur["is_charging"]:
            lost += prev["percent"] - cur["percent"]
            hours_total += hours
    if hours_total == 0:
        return None
    return lost / hours_total


def charge_sessions(readings):
    """Number of times the device was plugged in (off -> charging transitions).

    A history that starts while charging counts as one session.
    """
    sessions = 0
    was_charging = False
    for r in readings:
        if r["is_charging"] and not was_charging:
            sessions += 1
        was_charging = r["is_charging"]
    return sessions


def equivalent_full_cycles(readings, max_gap_hours=DEFAULT_MAX_GAP_HOURS):
    """Total percentage points gained while charging, divided by 100.

    This mirrors how Apple counts battery cycles: charging 50% -> 100%
    twice is one full cycle.
    """
    gained = 0.0
    for prev, cur, _ in _intervals(readings, max_gap_hours):
        if prev["is_charging"] and cur["percent"] > prev["percent"]:
            gained += cur["percent"] - prev["percent"]
    return gained / 100


def hours_charging(readings, max_gap_hours=DEFAULT_MAX_GAP_HOURS):
    """Hours spent plugged in (includes time held at 100%)."""
    return sum(
        (hours for prev, _, hours in _intervals(readings, max_gap_hours) if prev["is_charging"]),
        0.0,
    )


def hours_tracked(readings, max_gap_hours=DEFAULT_MAX_GAP_HOURS):
    """Hours covered by usable intervals (charging or not)."""
    return sum((hours for _, _, hours in _intervals(readings, max_gap_hours)), 0.0)


def time_to_empty_hours(current_percent, is_charging, drain_rate):
    """Estimated hours until 0% at the average drain rate.

    Returns None while charging or when no positive drain rate is known.
    """
    if is_charging or drain_rate is None or drain_rate <= 0:
        return None
    return current_percent / drain_rate


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def device_stats(readings, max_gap_hours=DEFAULT_MAX_GAP_HOURS):
    """Summary statistics for one device. ``readings`` must be sorted by time."""
    if not readings:
        return {
            "readings": 0,
            "first_reading": None,
            "last_reading": None,
            "current_percent": None,
            "is_charging": None,
            "avg_drain_per_hour": None,
            "charge_sessions": 0,
            "equivalent_full_cycles": 0.0,
            "hours_charging": 0.0,
            "hours_tracked": 0.0,
            "pct_time_charging": None,
            "est_hours_to_empty": None,
        }
    last = readings[-1]
    drain = drain_rate_per_hour(readings, max_gap_hours)
    charging_h = hours_charging(readings, max_gap_hours)
    tracked_h = hours_tracked(readings, max_gap_hours)
    return {
        "readings": len(readings),
        "first_reading": readings[0]["ts"].isoformat(),
        "last_reading": last["ts"].isoformat(),
        "current_percent": last["percent"],
        "is_charging": bool(last["is_charging"]),
        "avg_drain_per_hour": _round(drain),
        "charge_sessions": charge_sessions(readings),
        "equivalent_full_cycles": _round(equivalent_full_cycles(readings, max_gap_hours)),
        "hours_charging": _round(charging_h),
        "hours_tracked": _round(tracked_h),
        "pct_time_charging": _round(100 * charging_h / tracked_h, 1) if tracked_h else None,
        "est_hours_to_empty": _round(
            time_to_empty_hours(last["percent"], last["is_charging"], drain), 1
        ),
    }
