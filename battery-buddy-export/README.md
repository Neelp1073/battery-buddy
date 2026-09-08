# Battery Buddy

Mac + iPhone battery tracking with a shared Flask backend.

## Folders
- `backend/` — Flask server (port 5001), SQLite store, dashboard
- `mac/` — Mac battery sender + local notifications
- `ios/` — put your Xcode `Batterybuddy` project here (create on Mac)

## Start backend
```bash
cd backend
pip3 install flask
python3 app.py
```

Dashboard: http://127.0.0.1:5001/dashboard

## Send Mac battery
```bash
cd mac
python3 send_battery.py
```

## Optional Mac alerts (can spam if HOURLY_SECONDS is 60)
```bash
cd mac
python3 poll_alerts.py
```

## iPhone
Open the Xcode project, set `baseURL` to your Mac's Wi‑Fi IP, enable App Transport Security Allow Arbitrary Loads, run on a real iPhone.
