"""Generate SIMULATED battery readings for demos, screenshots and tests.

This is NOT real device data. It is a seeded, rule-based simulation of a
MacBook and an iPhone so the dashboard and analysis have something
realistic-looking to show. Simulated devices are named ``demo-macbook``
and ``demo-iphone`` so they are never confused with real readings.

Examples:
    # CSV only (deterministic: fixed seed and end time)
    python analysis/simulate_readings.py --csv analysis/sample_data/simulated_readings.csv \
        --end 2026-09-30T21:00:00+05:30

    # Load into a separate SQLite file and run the dashboard on it
    python analysis/simulate_readings.py --db backend/sample.db
    BB_DB_PATH=backend/sample.db python backend/app.py
"""
import argparse
import csv
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))  # the simulated "user" lives in India
DEMO_DEVICES = {"demo-macbook": "mac", "demo-iphone": "iphone"}
FIELDS = ["device_id", "device_type", "battery_percent", "is_charging", "created_at"]


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def simulate_iphone(rng, start, steps, step_min):
    """Phone: charged overnight, steady daytime drain with heavy-use bursts."""
    level, charging, plug_until = 80.0, False, None
    for i in range(steps):
        ts = start + timedelta(minutes=i * step_min)
        local = ts.astimezone(IST)
        hour = local.hour + local.minute / 60
        night = hour >= 23.5 or hour < 7
        if night and not charging and rng.random() < 0.85:
            charging, plug_until = True, None          # plugged in at bedtime
        if charging and not night and plug_until is None:
            charging = False                           # unplugged in the morning
        if not charging and not night and level <= 25 and rng.random() < 0.35:
            charging, plug_until = True, ts + timedelta(minutes=rng.randint(40, 90))
        if plug_until is not None and ts >= plug_until:
            charging, plug_until = False, None

        if charging:
            level += rng.uniform(3.0, 4.5) * step_min / 10 if level < 80 else rng.uniform(1.0, 2.0)
        elif night:
            level -= rng.uniform(0.3, 0.8) * step_min / 60
        else:
            rate = rng.choice([2.5, 3.5, 4.5, 6.0, 11.0])  # %/hour, occasional heavy use
            level -= rate * step_min / 60
        level = _clamp(level, 2)
        yield ts, round(level), charging


def simulate_mac(rng, start, steps, step_min):
    """Laptop: only reports while awake (09:00-24:00), drains faster, charged at the desk."""
    level, charging = 70.0, False
    for i in range(steps):
        ts = start + timedelta(minutes=i * step_min)
        local = ts.astimezone(IST)
        awake = local.hour >= 9
        if not awake:
            level = _clamp(level - 0.4 * step_min / 60)  # lid closed, no readings sent
            continue
        if not charging and level <= 30 and rng.random() < 0.5:
            charging = True
        if charging and level >= rng.uniform(88, 100):
            charging = False

        if charging:
            level += rng.uniform(3.0, 5.0) * step_min / 10
        else:
            work_hours = 10 <= local.hour < 19 and local.weekday() < 5
            rate = rng.uniform(9, 14) if work_hours else rng.uniform(5, 8)
            level -= rate * step_min / 60
        level = _clamp(level, 3)
        yield ts, round(level), charging


def generate(seed=42, days=7, step_min=10, end=None):
    """Return a list of reading dicts (sorted by time) for both demo devices."""
    rng = random.Random(seed)
    end = end or datetime.now(timezone.utc)
    end = end.astimezone(timezone.utc).replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % step_min)
    steps = days * 24 * 60 // step_min
    start = end - timedelta(minutes=(steps - 1) * step_min)

    rows = []
    for device_id, simulate in (("demo-macbook", simulate_mac), ("demo-iphone", simulate_iphone)):
        for ts, pct, charging in simulate(rng, start, steps, step_min):
            rows.append({
                "device_id": device_id,
                "device_type": DEMO_DEVICES[device_id],
                "battery_percent": pct,
                "is_charging": charging,
                "created_at": ts.isoformat(),
            })
    rows.sort(key=lambda r: (r["created_at"], r["device_id"]))
    return rows


def write_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "is_charging": int(r["is_charging"])})


def write_db(rows, path):
    """Load rows into a Battery Buddy SQLite DB, replacing previous demo rows only."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    import app as backend  # reuse the real schema

    backend.app.config["BB_DB_PATH"] = str(path)
    backend.init_db()
    demo_ids = tuple(DEMO_DEVICES)
    marks = ",".join("?" * len(demo_ids))
    with sqlite3.connect(path) as conn:
        conn.execute(f"DELETE FROM history WHERE device_id IN ({marks})", demo_ids)
        conn.execute(f"DELETE FROM devices WHERE device_id IN ({marks})", demo_ids)
        conn.executemany(
            "INSERT INTO history (device_id, battery_percent, is_charging, created_at) VALUES (?, ?, ?, ?)",
            [(r["device_id"], r["battery_percent"], int(r["is_charging"]), r["created_at"]) for r in rows],
        )
        latest = {r["device_id"]: r for r in rows}  # rows are time-sorted
        conn.executemany(
            "INSERT INTO devices (device_id, device_type, battery_percent, is_charging, updated_at) VALUES (?, ?, ?, ?, ?)",
            [(r["device_id"], r["device_type"], r["battery_percent"], int(r["is_charging"]), r["created_at"])
             for r in latest.values()],
        )
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Generate SIMULATED battery readings (demo data only).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--interval", type=int, default=10, help="minutes between readings")
    parser.add_argument("--end", help="ISO timestamp of the last reading (default: now)")
    parser.add_argument("--csv", help="write readings to this CSV file")
    parser.add_argument("--db", help="load readings into this SQLite file (e.g. backend/sample.db)")
    args = parser.parse_args()
    if not args.csv and not args.db:
        parser.error("give --csv and/or --db")

    end = datetime.fromisoformat(args.end) if args.end else None
    rows = generate(args.seed, args.days, args.interval, end)
    if args.csv:
        write_csv(rows, args.csv)
        print(f"Wrote {len(rows)} simulated readings to {args.csv}")
    if args.db:
        write_db(rows, args.db)
        print(f"Loaded {len(rows)} simulated readings into {args.db}")


if __name__ == "__main__":
    main()
