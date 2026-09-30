from flask import Flask, request, jsonify, render_template
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
import sqlite3
import threading
import time

from config import load_config
import stats as battery_stats

app = Flask(__name__)
app.config.update(load_config())

@contextmanager
def db():
    """Open a connection, commit on success, and always close it."""
    conn = sqlite3.connect(app.config["BB_DB_PATH"])
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            device_type TEXT NOT NULL,
            battery_percent INTEGER NOT NULL,
            is_charging INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            push_token TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            battery_percent INTEGER NOT NULL,
            is_charging INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            delivered INTEGER NOT NULL DEFAULT 0
        )
        """)
        # Speeds up per-device time-range queries for /history and /stats.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_device_time ON history (device_id, created_at)"
        )
        conn.commit()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def level_class(pct):
    if pct <= 20:
        return "bad"
    if pct <= 40:
        return "warn"
    return "ok"

DEFAULT_WINDOW_HOURS = 168  # /history and /stats default to the last 7 days


def parse_hours_arg():
    """Read the optional ?hours= query arg. 0 means all history.

    Returns (hours, error_message).
    """
    raw = request.args.get("hours")
    if raw is None or raw == "":
        return DEFAULT_WINDOW_HOURS, None
    try:
        hours = float(raw)
    except ValueError:
        return None, "hours must be a number"
    if hours < 0:
        return None, "hours must be >= 0"
    return hours, None


def fetch_readings(device_id=None, hours=DEFAULT_WINDOW_HOURS):
    """Return history rows (oldest first), optionally filtered by device and window."""
    sql = "SELECT device_id, battery_percent, is_charging, created_at FROM history"
    where, params = [], []
    if device_id:
        where.append("device_id = ?")
        params.append(device_id)
    if hours:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        where.append("created_at >= ?")
        params.append(since.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at, id"
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "device_id": r["device_id"],
            "battery_percent": r["battery_percent"],
            "is_charging": bool(r["is_charging"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def readings_by_device(rows):
    """Group /history rows into {device_id: [stats reading, ...]}."""
    grouped = {}
    for r in rows:
        grouped.setdefault(r["device_id"], []).append({
            "ts": battery_stats.parse_ts(r["created_at"]),
            "percent": r["battery_percent"],
            "is_charging": r["is_charging"],
        })
    return grouped


def compute_stats(rows):
    """Per-device stats for a list of /history rows, sorted by device_id."""
    return [
        {"device_id": device_id, **battery_stats.device_stats(readings)}
        for device_id, readings in sorted(readings_by_device(rows).items())
    ]


def upsert_device(device_id, device_type, battery_percent, is_charging, push_token=None):
    ts = now_iso()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO devices (device_id, device_type, battery_percent, is_charging, updated_at, push_token)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
              device_type=excluded.device_type,
              battery_percent=excluded.battery_percent,
              is_charging=excluded.is_charging,
              updated_at=excluded.updated_at,
              push_token=COALESCE(excluded.push_token, devices.push_token)
            """,
            (device_id, device_type, battery_percent, int(is_charging), ts, push_token),
        )
        conn.execute(
            """
            INSERT INTO history (device_id, battery_percent, is_charging, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (device_id, battery_percent, int(is_charging), ts),
        )
        if battery_percent <= app.config["BB_LOW_BATTERY_THRESHOLD"] and not is_charging:
            msg = f"{device_id} is low: {battery_percent}%"
            conn.execute(
                """
                INSERT INTO alerts (device_id, kind, message, created_at, delivered)
                VALUES (?, 'low_battery', ?, ?, 0)
                """,
                (device_id, msg, ts),
            )
        conn.commit()
    return {
        "device_id": device_id,
        "device_type": device_type,
        "battery_percent": battery_percent,
        "is_charging": bool(is_charging),
        "updated_at": ts,
    }

@app.get("/")
def home():
    return jsonify({"ok": True, "message": "Battery Buddy backend running"})

@app.post("/battery")
def receive_battery():
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    device_type = data.get("device_type")
    battery_percent = data.get("battery_percent")
    is_charging = bool(data.get("is_charging", False))
    push_token = data.get("push_token")

    if not device_id or device_type not in ("mac", "iphone"):
        return jsonify({"ok": False, "error": "Need device_id and device_type (mac|iphone)"}), 400
    try:
        battery_percent = int(battery_percent)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "battery_percent must be a number"}), 400
    if battery_percent < 0 or battery_percent > 100:
        return jsonify({"ok": False, "error": "battery_percent must be 0-100"}), 400

    stored = upsert_device(device_id, device_type, battery_percent, is_charging, push_token)
    return jsonify({"ok": True, "stored": stored})

@app.get("/devices")
def list_devices():
    with db() as conn:
        rows = conn.execute(
            "SELECT device_id, device_type, battery_percent, is_charging, updated_at FROM devices"
        ).fetchall()
    devices = [
        {
            "device_id": r["device_id"],
            "device_type": r["device_type"],
            "battery_percent": r["battery_percent"],
            "is_charging": bool(r["is_charging"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]
    return jsonify({"ok": True, "devices": devices})

@app.get("/alerts/pending")
def pending_alerts():
    device_id = request.args.get("device_id")
    with db() as conn:
        if device_id:
            rows = conn.execute(
                "SELECT id, device_id, kind, message, created_at FROM alerts WHERE delivered=0 AND device_id=? ORDER BY id",
                (device_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, device_id, kind, message, created_at FROM alerts WHERE delivered=0 ORDER BY id"
            ).fetchall()
    return jsonify({"ok": True, "alerts": [dict(r) for r in rows]})

@app.post("/alerts/<int:alert_id>/delivered")
def mark_delivered(alert_id):
    with db() as conn:
        conn.execute("UPDATE alerts SET delivered=1 WHERE id=?", (alert_id,))
        conn.commit()
    return jsonify({"ok": True})

@app.get("/history")
def history():
    """Battery readings over time. Query args: device_id, hours (default 168, 0 = all)."""
    hours, error = parse_hours_arg()
    if error:
        return jsonify({"ok": False, "error": error}), 400
    rows = fetch_readings(request.args.get("device_id"), hours)
    return jsonify({"ok": True, "hours": hours, "count": len(rows), "readings": rows})

@app.get("/stats")
def stats():
    """Per-device analytics over the same window as /history."""
    hours, error = parse_hours_arg()
    if error:
        return jsonify({"ok": False, "error": error}), 400
    rows = fetch_readings(request.args.get("device_id"), hours)
    return jsonify({"ok": True, "hours": hours, "stats": compute_stats(rows)})

CHART_GAP_HOURS = 1.0  # break the chart line when readings are further apart than this
DASHBOARD_RANGES = [(24, "24h"), (168, "7d"), (720, "30d"), (0, "All")]


def chart_series(rows):
    """{device_id: [{x: epoch ms, y: percent, c: charging}, ...]} for Chart.js.

    A null point is inserted across long gaps so the line is not drawn
    through periods with no data.
    """
    series = {}
    for device_id, readings in readings_by_device(rows).items():
        points, prev_ts = [], None
        for r in readings:
            ms = int(r["ts"].timestamp() * 1000)
            if prev_ts and (r["ts"] - prev_ts).total_seconds() > CHART_GAP_HOURS * 3600:
                points.append({"x": ms - 1, "y": None, "c": False})
            points.append({"x": ms, "y": r["percent"], "c": r["is_charging"]})
            prev_ts = r["ts"]
        series[device_id] = points
    return series


@app.template_filter("hours")
def format_hours(value):
    """Format a number of hours as e.g. '3h 12m'; '—' when unknown."""
    if value is None:
        return "—"
    minutes = int(round(value * 60))
    h, m = divmod(minutes, 60)
    if h >= 48:
        return f"{h / 24:.1f} days"
    return f"{h}h {m:02d}m" if h else f"{m}m"


@app.get("/dashboard")
def dashboard():
    hours, error = parse_hours_arg()
    if error:
        hours = DEFAULT_WINDOW_HOURS
    readings = fetch_readings(hours=hours)
    with db() as conn:
        rows = conn.execute(
            "SELECT device_id, device_type, battery_percent, is_charging, updated_at FROM devices ORDER BY device_id"
        ).fetchall()
        history = conn.execute(
            "SELECT device_id, battery_percent, is_charging, created_at FROM history ORDER BY id DESC LIMIT 50"
        ).fetchall()

    devices = []
    for r in rows:
        devices.append({
            "device_id": r["device_id"],
            "device_type": r["device_type"],
            "battery_percent": r["battery_percent"],
            "is_charging": bool(r["is_charging"]),
            "updated_at": r["updated_at"],
            "level_class": level_class(r["battery_percent"]),
        })

    return render_template(
        "dashboard.html",
        devices=devices,
        history=history,
        device_count=len(devices),
        stats=compute_stats(readings),
        chart_data=chart_series(readings),
        hours=hours,
        ranges=DASHBOARD_RANGES,
    )

def hourly_worker():
    while True:
        time.sleep(app.config["BB_HOURLY_SECONDS"])
        ts = now_iso()
        with db() as conn:
            rows = conn.execute(
                "SELECT device_id, battery_percent, is_charging FROM devices"
            ).fetchall()
            for r in rows:
                msg = f"Hourly: {r['device_id']} is {r['battery_percent']}% (charging={bool(r['is_charging'])})"
                conn.execute(
                    "INSERT INTO alerts (device_id, kind, message, created_at, delivered) VALUES (?, 'hourly', ?, ?, 0)",
                    (r["device_id"], msg, ts),
                )
            conn.commit()

if __name__ == "__main__":
    init_db()
    debug = app.config["BB_DEBUG"]
    # In debug mode the reloader runs this file twice; only start the
    # background worker in the process that actually serves requests.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=hourly_worker, daemon=True).start()
    app.run(host=app.config["BB_HOST"], port=app.config["BB_PORT"], debug=debug)
