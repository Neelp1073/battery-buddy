from flask import Flask, request, jsonify, render_template_string
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

DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Battery Buddy</title>
  <meta http-equiv="refresh" content="15" />
  <style>
    :root {
      --bg: #0b1220;
      --card: #121a2b;
      --text: #e8eefc;
      --muted: #93a0b8;
      --line: #243049;
      --ok: #22c55e;
      --warn: #f59e0b;
      --bad: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(1200px 600px at 20% -10%, #1a2744, var(--bg));
      color: var(--text);
      min-height: 100vh;
    }
    .wrap { max-width: 980px; margin: 0 auto; padding: 28px 18px 48px; }
    header { display: flex; justify-content: space-between; align-items: end; gap: 12px; margin-bottom: 22px; }
    h1 { margin: 0; font-size: 1.6rem; letter-spacing: -0.02em; }
    .sub { color: var(--muted); font-size: 0.92rem; margin-top: 6px; }
    .pill {
      background: #18233a; border: 1px solid var(--line); color: var(--muted);
      padding: 8px 12px; border-radius: 999px; font-size: 0.85rem;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin-bottom: 22px;
    }
    .card {
      background: linear-gradient(180deg, #152038, var(--card));
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25);
    }
    .row { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
    .name { font-weight: 700; font-size: 1.05rem; }
    .type { color: var(--muted); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; }
    .pct { font-size: 2rem; font-weight: 750; letter-spacing: -0.03em; }
    .bar {
      height: 10px; background: #1c2944; border-radius: 999px; overflow: hidden; margin: 12px 0 10px;
    }
    .fill { height: 100%; border-radius: 999px; }
    .fill.ok { background: linear-gradient(90deg, #16a34a, var(--ok)); }
    .fill.warn { background: linear-gradient(90deg, #d97706, var(--warn)); }
    .fill.bad { background: linear-gradient(90deg, #dc2626, var(--bad)); }
    .badge {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 5px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 600;
      border: 1px solid var(--line);
    }
    .badge.on { background: rgba(34,197,94,0.12); color: #86efac; }
    .badge.off { background: rgba(147,160,184,0.12); color: var(--muted); }
    .meta { color: var(--muted); font-size: 0.82rem; }
    h2 { margin: 8px 0 12px; font-size: 1.1rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); font-size: 0.92rem; }
    th { color: var(--muted); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }
    tr:hover td { background: rgba(255,255,255,0.02); }
    .empty { color: var(--muted); padding: 18px 4px; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>Battery Buddy</h1>
        <div class="sub">Live devices + recent history · auto-refreshes every 15s</div>
      </div>
      <div class="pill">{{ device_count }} device{{ '' if device_count == 1 else 's' }} online</div>
    </header>

    <div class="grid">
      {% for d in devices %}
      <div class="card">
        <div class="row">
          <div>
            <div class="name">{{ d.device_id }}</div>
            <div class="type">{{ d.device_type }}</div>
          </div>
          <div class="pct">{{ d.battery_percent }}%</div>
        </div>
        <div class="bar"><div class="fill {{ d.level_class }}" style="width: {{ d.battery_percent }}%"></div></div>
        <div class="row">
          {% if d.is_charging %}
          <span class="badge on">⚡ Charging</span>
          {% else %}
          <span class="badge off">On battery</span>
          {% endif %}
          <span class="meta">{{ d.updated_at }}</span>
        </div>
      </div>
      {% else %}
      <div class="card empty">No devices yet. Run the Mac sender or iPhone app.</div>
      {% endfor %}
    </div>

    <div class="card">
      <h2>Recent history</h2>
      {% if history %}
      <table>
        <thead>
          <tr><th>When (UTC)</th><th>Device</th><th>%</th><th>Status</th></tr>
        </thead>
        <tbody>
          {% for h in history %}
          <tr>
            <td>{{ h.created_at }}</td>
            <td>{{ h.device_id }}</td>
            <td>{{ h.battery_percent }}%</td>
            <td>{{ 'Charging' if h.is_charging else 'On battery' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty">No history yet.</div>
      {% endif %}
    </div>
  </div>
</body>
</html>
"""

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

@app.get("/dashboard")
def dashboard():
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

    return render_template_string(
        DASHBOARD_HTML,
        devices=devices,
        history=history,
        device_count=len(devices),
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
