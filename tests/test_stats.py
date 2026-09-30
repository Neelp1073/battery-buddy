from datetime import datetime, timedelta, timezone

import pytest

import stats

T0 = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


def series(*points, step_min=30):
    """Build readings from (percent, charging) tuples spaced step_min apart."""
    return [
        {"ts": T0 + timedelta(minutes=i * step_min), "percent": pct, "is_charging": ch}
        for i, (pct, ch) in enumerate(points)
    ]


def test_drain_rate_on_battery_only():
    r = series((100, False), (95, False), (90, False), (95, True), (100, True))
    # Only the first two intervals are on battery: 10% over 1 hour
    assert stats.drain_rate_per_hour(r) == pytest.approx(10.0)


def test_drain_rate_ignores_interval_where_charger_is_unplugged():
    # 100% (charging) -> 98% (unplugged): interval started while charging
    r = series((100, True), (98, False), (96, False))
    assert stats.drain_rate_per_hour(r) == pytest.approx(4.0)


def test_drain_rate_ignores_long_gaps():
    r = [
        {"ts": T0, "percent": 80, "is_charging": False},
        {"ts": T0 + timedelta(hours=1), "percent": 75, "is_charging": False},
        {"ts": T0 + timedelta(hours=9), "percent": 70, "is_charging": False},  # 8 h gap
    ]
    assert stats.drain_rate_per_hour(r) == pytest.approx(5.0)
    assert stats.hours_tracked(r) == pytest.approx(1.0)
    assert stats.drain_rate_per_hour(r, max_gap_hours=10) == pytest.approx(10 / 9)


def test_drain_rate_none_without_battery_intervals():
    assert stats.drain_rate_per_hour([]) is None
    assert stats.drain_rate_per_hour(series((50, False))) is None
    assert stats.drain_rate_per_hour(series((50, True), (60, True))) is None


def test_charge_sessions():
    r = series((50, False), (60, True), (70, True), (65, False), (70, True), (60, False))
    assert stats.charge_sessions(r) == 2
    assert stats.charge_sessions(series((50, True), (60, True))) == 1
    assert stats.charge_sessions(series((50, False), (40, False))) == 0


def test_equivalent_full_cycles():
    # Gains count only on intervals that *start* while charging:
    # 50->80 (+30) and 80->100 (+20). 70->80 starts unplugged; 100->100 adds nothing.
    r = series((50, False), (50, True), (80, True), (70, False), (80, True), (100, True), (100, True))
    assert stats.equivalent_full_cycles(r) == pytest.approx(0.5)


def test_hours_charging_and_tracked():
    r = series((50, True), (60, True), (70, False), (65, False))
    assert stats.hours_charging(r) == pytest.approx(1.0)
    assert stats.hours_tracked(r) == pytest.approx(1.5)


def test_time_to_empty():
    assert stats.time_to_empty_hours(50, False, 10.0) == pytest.approx(5.0)
    assert stats.time_to_empty_hours(50, True, 10.0) is None
    assert stats.time_to_empty_hours(50, False, None) is None
    assert stats.time_to_empty_hours(50, False, 0) is None
    assert stats.time_to_empty_hours(50, False, -2.0) is None


def test_device_stats_summary():
    r = series((100, False), (95, False), (90, False), (95, True), (100, True), (98, False), (96, False))
    s = stats.device_stats(r)
    assert s["readings"] == 7
    assert s["current_percent"] == 96
    assert s["is_charging"] is False
    # on-battery intervals: 100->95, 95->90, 98->96 = 12% over 1.5 h
    assert s["avg_drain_per_hour"] == 8.0
    assert s["charge_sessions"] == 1
    assert s["equivalent_full_cycles"] == 0.05  # 95->100 while charging
    assert s["hours_charging"] == 1.0
    assert s["hours_tracked"] == 3.0
    assert s["pct_time_charging"] == 33.3
    assert s["est_hours_to_empty"] == 12.0


def test_device_stats_empty():
    s = stats.device_stats([])
    assert s["readings"] == 0
    assert s["avg_drain_per_hour"] is None
    assert s["est_hours_to_empty"] is None
