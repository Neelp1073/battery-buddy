"""The pandas analysis must agree with the backend's /stats numbers."""
from datetime import datetime, timezone

import pandas as pd
import pytest

import analyze
import app as backend
import simulate_readings

END = datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def sample_rows():
    return simulate_readings.generate(seed=7, days=3, end=END)


def test_simulator_is_deterministic(sample_rows):
    again = simulate_readings.generate(seed=7, days=3, end=END)
    assert again == sample_rows
    assert {r["device_id"] for r in sample_rows} == {"demo-macbook", "demo-iphone"}
    assert all(0 <= r["battery_percent"] <= 100 for r in sample_rows)
    assert simulate_readings.generate(seed=8, days=3, end=END) != sample_rows


def test_pandas_stats_match_backend(sample_rows, tmp_path):
    csv_path = tmp_path / "readings.csv"
    simulate_readings.write_csv(sample_rows, csv_path)
    pandas_stats = analyze.device_stats(analyze.load_readings(csv_path))

    history_rows = [
        {**r, "is_charging": bool(r["is_charging"])} for r in sample_rows
    ]
    for s in backend.compute_stats(history_rows):
        p = pandas_stats.loc[s["device_id"]]
        assert p["readings"] == s["readings"]
        assert p["charge_sessions"] == s["charge_sessions"]
        assert round(p["avg_drain_per_hour"], 2) == s["avg_drain_per_hour"]
        assert round(p["equivalent_full_cycles"], 2) == s["equivalent_full_cycles"]
        assert round(p["hours_charging"], 2) == s["hours_charging"]
        assert round(p["hours_tracked"], 2) == s["hours_tracked"]
        if s["est_hours_to_empty"] is None:
            assert pd.isna(p["est_hours_to_empty"])
        else:
            assert round(p["est_hours_to_empty"], 1) == s["est_hours_to_empty"]


def test_simulated_db_round_trip(sample_rows, tmp_path, client):
    import export_csv

    db_path = tmp_path / "sample.db"
    simulate_readings.write_db(sample_rows, db_path)
    simulate_readings.write_db(sample_rows, db_path)  # re-running replaces, not duplicates
    df = export_csv.load_readings_from_db(db_path)
    assert len(df) == len(sample_rows)
    assert set(df["device_type"]) == {"mac", "iphone"}


def test_drain_by_hour_and_daily_summary(sample_rows, tmp_path):
    csv_path = tmp_path / "readings.csv"
    simulate_readings.write_csv(sample_rows, csv_path)
    df = analyze.load_readings(csv_path)
    hourly = analyze.drain_by_hour(df)
    assert set(hourly.columns) == {"demo-macbook", "demo-iphone"}
    assert hourly.index.min() >= 0 and hourly.index.max() <= 23
    daily = analyze.daily_summary(df)
    assert (daily["min_pct"] <= daily["max_pct"]).all()
