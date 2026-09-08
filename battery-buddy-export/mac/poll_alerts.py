import json
import time
import urllib.request
from show_notification import notify

MY_ID = "neels-macbook"
BASE = "http://127.0.0.1:5001"

def get_pending():
    url = f"{BASE}/alerts/pending?device_id={MY_ID}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8")).get("alerts", [])

def mark_done(alert_id):
    req = urllib.request.Request(
        f"{BASE}/alerts/{alert_id}/delivered",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()

print("Polling for alerts. Control+C to stop.")
while True:
    try:
        for alert in get_pending():
            print(alert["message"])
            notify("Battery Buddy", alert["message"])
            mark_done(alert["id"])
    except Exception as e:
        print("Poll error:", e)
    time.sleep(10)
