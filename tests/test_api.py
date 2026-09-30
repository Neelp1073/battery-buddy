"""Endpoint tests. The request/response shapes checked here are the ones
the iOS app (ContentView.swift) and the Mac scripts depend on."""
import sqlite3
from datetime import datetime, timedelta, timezone

import app as backend


def insert_reading(device_id, percent, charging, ts):
    with sqlite3.connect(backend.app.config["BB_DB_PATH"]) as conn:
        conn.execute(
            "INSERT INTO history (device_id, battery_percent, is_charging, created_at) VALUES (?, ?, ?, ?)",
            (device_id, percent, int(charging), ts.isoformat()),
        )
    conn.close()


def test_home(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "message": "Battery Buddy backend running"}


def test_post_battery_stores_device(client, post_battery):
    r = post_battery("neels-macbook", "mac", 87, True)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    stored = body["stored"]
    assert stored["device_id"] == "neels-macbook"
    assert stored["battery_percent"] == 87
    assert stored["is_charging"] is True
    assert datetime.fromisoformat(stored["updated_at"]).tzinfo is not None


def test_post_battery_accepts_numeric_string(client, post_battery):
    assert post_battery(percent="42").get_json()["stored"]["battery_percent"] == 42


def test_post_battery_validation(client, post_battery):
    assert post_battery(device_id="").status_code == 400
    assert post_battery(device_type="android").status_code == 400
    assert post_battery(percent="abc").status_code == 400
    assert post_battery(percent=None).status_code == 400
    assert post_battery(percent=101).status_code == 400
    assert post_battery(percent=-1).status_code == 400
    r = client.post("/battery", data="not json", content_type="text/plain")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_devices_matches_ios_model(client, post_battery):
    post_battery("neels-iphone", "iphone", 64, False)
    post_battery("neels-iphone", "iphone", 63, False)  # upsert, not a second device
    body = client.get("/devices").get_json()
    assert body["ok"] is True
    assert len(body["devices"]) == 1
    device = body["devices"][0]
    # Exactly the fields decoded by DeviceInfo in ContentView.swift
    assert set(device) == {"device_id", "device_type", "battery_percent", "is_charging", "updated_at"}
    assert device["battery_percent"] == 63
    assert isinstance(device["is_charging"], bool)


def test_push_token_is_kept_when_omitted(client, post_battery):
    post_battery(push_token="abc123")
    post_battery(percent=40)
    with sqlite3.connect(backend.app.config["BB_DB_PATH"]) as conn:
        token = conn.execute("SELECT push_token FROM devices").fetchone()[0]
    conn.close()
    assert token == "abc123"


def test_low_battery_alert_flow(client, post_battery):
    post_battery("neels-macbook", percent=15, charging=False)
    post_battery("neels-macbook", percent=15, charging=True)   # charging: no alert
    post_battery("other-mac", percent=90, charging=False)       # not low: no alert

    alerts = client.get("/alerts/pending?device_id=neels-macbook").get_json()["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["kind"] == "low_battery"
    assert alert["message"] == "neels-macbook is low: 15%"
    assert set(alert) == {"id", "device_id", "kind", "message", "created_at"}

    assert client.post(f"/alerts/{alert['id']}/delivered", json={}).get_json() == {"ok": True}
    assert client.get("/alerts/pending").get_json()["alerts"] == []


def test_low_battery_threshold_is_configurable(client, post_battery):
    backend.app.config["BB_LOW_BATTERY_THRESHOLD"] = 50
    try:
        post_battery(percent=45)
        assert len(client.get("/alerts/pending").get_json()["alerts"]) == 1
    finally:
        backend.app.config["BB_LOW_BATTERY_THRESHOLD"] = 20


def test_every_post_is_recorded_in_history(client, post_battery):
    for pct in (80, 79, 78):
        post_battery(percent=pct)
    body = client.get("/history").get_json()
    assert body["ok"] is True
    assert body["count"] == 3
    assert [r["battery_percent"] for r in body["readings"]] == [80, 79, 78]  # oldest first
    assert set(body["readings"][0]) == {"device_id", "battery_percent", "is_charging", "created_at"}


def test_history_filters(client, post_battery):
    now = datetime.now(timezone.utc)
    insert_reading("mac", 90, False, now - timedelta(hours=30))
    insert_reading("mac", 80, False, now - timedelta(hours=2))
    insert_reading("phone", 70, False, now - timedelta(hours=1))

    assert client.get("/history?hours=24").get_json()["count"] == 2
    assert client.get("/history?hours=0").get_json()["count"] == 3
    only_mac = client.get("/history?hours=0&device_id=mac").get_json()["readings"]
    assert [r["battery_percent"] for r in only_mac] == [90, 80]


def test_history_rejects_bad_hours(client):
    assert client.get("/history?hours=abc").status_code == 400
    assert client.get("/history?hours=-5").status_code == 400
    assert client.get("/stats?hours=abc").status_code == 400


def test_stats_endpoint(client):
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    # 100 -> 90 over one hour on battery, then plugged in back to 100
    points = [(0, 100, False), (30, 95, False), (60, 90, False), (90, 95, True), (120, 100, True)]
    for minutes, pct, charging in points:
        insert_reading("mac", pct, charging, start + timedelta(minutes=minutes))

    stats = client.get("/stats").get_json()["stats"]
    assert len(stats) == 1
    s = stats[0]
    assert s["device_id"] == "mac"
    assert s["readings"] == 5
    assert s["avg_drain_per_hour"] == 10.0
    assert s["charge_sessions"] == 1
    assert s["equivalent_full_cycles"] == 0.05
    assert s["hours_charging"] == 0.5
    assert s["hours_tracked"] == 2.0
    assert s["is_charging"] is True
    assert s["est_hours_to_empty"] is None


def test_dashboard_renders(client, post_battery):
    post_battery("neels-macbook", "mac", 15, False)
    r = client.get("/dashboard")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "neels-macbook" in html
    assert "15%" in html
    assert "Battery over time" in html
    assert "chart.js" in html.lower()


def test_dashboard_empty_and_bad_range(client):
    assert client.get("/dashboard").status_code == 200
    assert client.get("/dashboard?hours=nonsense").status_code == 200
