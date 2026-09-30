import json
import re
import subprocess
import urllib.request

from settings import BACKEND_URL, DEVICE_ID

BATTERY_ENDPOINT = f"{BACKEND_URL}/battery"
DEVICE_TYPE = "mac"

def read_mac_battery():
    raw = subprocess.check_output(["pmset", "-g", "batt"], text=True)
    match = re.search(r"(\d+)%", raw)
    if not match:
        raise RuntimeError(f"Could not find battery percent in:\n{raw}")

    percent = int(match.group(1))
    lower = raw.lower()
    is_charging = ("charging" in lower) and ("discharging" not in lower)
    return percent, is_charging

def send_to_backend(percent, is_charging):
    payload = {
        "device_id": DEVICE_ID,
        "device_type": DEVICE_TYPE,
        "battery_percent": percent,
        "is_charging": is_charging,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BATTERY_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")

if __name__ == "__main__":
    percent, charging = read_mac_battery()
    print(f"Mac battery: {percent}% | charging={charging}")
    status, body = send_to_backend(percent, charging)
    print(f"Backend reply ({status}): {body}")
