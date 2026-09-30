"""Battery analytics with pandas.

Computes the same per-device stats as the backend's /stats endpoint
(backend/stats.py) from a readings CSV, plus two extra views that are
easier in pandas: drain by hour of day and a daily summary.

    python analysis/analyze.py                                   # simulated sample CSV
    python analysis/analyze.py --csv analysis/output/readings.csv  # your exported data
    python analysis/analyze.py --out analysis/output               # also save result CSVs
"""
import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "analysis" / "sample_data" / "simulated_readings.csv"
MAX_GAP_HOURS = 1.0  # same rule as backend/stats.py
LOCAL_TZ = "Asia/Kolkata"


def load_readings(csv_path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, format="ISO8601")
    df["is_charging"] = df["is_charging"].astype(bool)
    return df.sort_values(["device_id", "created_at"]).reset_index(drop=True)


def add_intervals(df: pd.DataFrame, max_gap_hours=MAX_GAP_HOURS) -> pd.DataFrame:
    """Attach the previous reading of the same device and the interval length.

    An interval is attributed to the state of its earlier reading and is
    only 'valid' if it is shorter than max_gap_hours.
    """
    df = df.copy()
    g = df.groupby("device_id")
    df["prev_percent"] = g["battery_percent"].shift()
    df["prev_charging"] = g["is_charging"].shift().astype("boolean")
    df["hours"] = g["created_at"].diff().dt.total_seconds() / 3600
    df["valid"] = (df["hours"] > 0) & (df["hours"] <= max_gap_hours)
    df["on_battery"] = df["valid"] & ~df["prev_charging"].fillna(True) & ~df["is_charging"]
    df["drop"] = df["prev_percent"] - df["battery_percent"]
    return df


def device_stats(df: pd.DataFrame, max_gap_hours=MAX_GAP_HOURS) -> pd.DataFrame:
    """One row per device with the same metrics as GET /stats."""
    iv = add_intervals(df, max_gap_hours)
    charging_iv = iv["valid"] & iv["prev_charging"].fillna(False)
    iv["battery_hours"] = iv["hours"].where(iv["on_battery"], 0.0)
    iv["battery_drop"] = iv["drop"].where(iv["on_battery"], 0.0)
    iv["charging_hours"] = iv["hours"].where(charging_iv, 0.0)
    iv["gained"] = (-iv["drop"]).clip(lower=0).where(charging_iv, 0.0)
    iv["tracked_hours"] = iv["hours"].where(iv["valid"], 0.0)
    iv["session_start"] = iv["is_charging"] & ~iv["prev_charging"].fillna(False)

    out = iv.groupby("device_id").agg(
        readings=("battery_percent", "size"),
        current_percent=("battery_percent", "last"),
        is_charging=("is_charging", "last"),
        battery_hours=("battery_hours", "sum"),
        battery_drop=("battery_drop", "sum"),
        charge_sessions=("session_start", "sum"),
        gained=("gained", "sum"),
        hours_charging=("charging_hours", "sum"),
        hours_tracked=("tracked_hours", "sum"),
    )
    out["avg_drain_per_hour"] = (out["battery_drop"] / out["battery_hours"]).where(out["battery_hours"] > 0)
    out["equivalent_full_cycles"] = out["gained"] / 100
    out["pct_time_charging"] = 100 * out["hours_charging"] / out["hours_tracked"]
    out["est_hours_to_empty"] = (out["current_percent"] / out["avg_drain_per_hour"]).where(
        ~out["is_charging"] & (out["avg_drain_per_hour"] > 0)
    )
    cols = [
        "readings", "current_percent", "is_charging", "avg_drain_per_hour",
        "charge_sessions", "equivalent_full_cycles", "hours_charging",
        "hours_tracked", "pct_time_charging", "est_hours_to_empty",
    ]
    return out[cols].astype({"charge_sessions": int})


def drain_by_hour(df: pd.DataFrame, max_gap_hours=MAX_GAP_HOURS) -> pd.DataFrame:
    """Average on-battery drain (%/h) for each local hour of the day, per device."""
    iv = add_intervals(df, max_gap_hours)
    iv = iv[iv["on_battery"]].copy()
    iv["hour"] = iv["created_at"].dt.tz_convert(LOCAL_TZ).dt.hour
    grouped = iv.groupby(["device_id", "hour"])[["drop", "hours"]].sum()
    rate = (grouped["drop"] / grouped["hours"]).rename("drain_per_hour")
    return rate.unstack("device_id").round(2)


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Min / mean / max battery % and share of readings on charge, per local day."""
    d = df.copy()
    d["date"] = d["created_at"].dt.tz_convert(LOCAL_TZ).dt.date
    return (
        d.groupby(["device_id", "date"])
        .agg(
            min_pct=("battery_percent", "min"),
            mean_pct=("battery_percent", "mean"),
            max_pct=("battery_percent", "max"),
            pct_readings_charging=("is_charging", lambda s: 100 * s.mean()),
        )
        .round(1)
    )


def main():
    parser = argparse.ArgumentParser(description="Battery analytics with pandas.")
    parser.add_argument("--csv", default=SAMPLE_CSV, help="readings CSV (default: simulated sample)")
    parser.add_argument("--out", help="folder to save stats CSVs into")
    args = parser.parse_args()

    df = load_readings(args.csv)
    if Path(args.csv).resolve() == SAMPLE_CSV.resolve():
        print("NOTE: using SIMULATED sample data (analysis/simulate_readings.py), not real readings.\n")

    stats = device_stats(df)
    hourly = drain_by_hour(df)
    daily = daily_summary(df)
    with pd.option_context("display.width", 120, "display.max_columns", 20):
        print("Per-device stats\n", stats.round(2).T, "\n", sep="")
        print("Drain by hour of day (%/h, on battery, local time)\n", hourly, "\n", sep="")
        print("Daily summary\n", daily, sep="")

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stats.round(2).to_csv(out / "device_stats.csv")
        hourly.to_csv(out / "drain_by_hour.csv")
        daily.to_csv(out / "daily_summary.csv")
        print(f"\nSaved results to {out}/")


if __name__ == "__main__":
    main()
