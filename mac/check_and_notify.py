import json
import urllib.request
from show_notification import notify

DEVICES_URL = "http://127.0.0.1:5001/devices"
MY_ID = "neels-macbook"

with urllib.request.urlopen(DEVICES_URL, timeout=10) as resp:
    data = json.loads(resp.read().decode("utf-8"))

devices = data.get("devices", [])
me = next((d for d in devices if d["device_id"] == MY_ID), None)

if not me:
    print("Mac not found in backend yet. Run send_battery.py first.")
else:
    msg = f"Your Mac battery is {me['battery_percent']}% (charging={me['is_charging']})"
    print(msg)
    notify("Battery Buddy", msg)
