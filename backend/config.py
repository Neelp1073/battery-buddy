"""Runtime configuration for the Battery Buddy backend.

Every setting has a sensible default and can be overridden with an
environment variable (see .env.example in the repository root).
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent


def _bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config(env=None) -> dict:
    """Build the Flask config dict from environment variables."""
    env = os.environ if env is None else env
    return {
        # Network interface and port for the Flask server.
        # 0.0.0.0 lets an iPhone on the same Wi-Fi reach the Mac.
        "BB_HOST": env.get("BB_HOST", "0.0.0.0"),
        "BB_PORT": int(env.get("BB_PORT", "5001")),
        # SQLite database file (created on first run).
        "BB_DB_PATH": env.get("BB_DB_PATH", str(BACKEND_DIR / "battery.db")),
        # Flask debug mode. Off by default: the Werkzeug debugger should
        # never be reachable from other machines on the network.
        "BB_DEBUG": _bool(env.get("BB_DEBUG", "0")),
        # A "low battery" alert is queued at or below this percentage.
        "BB_LOW_BATTERY_THRESHOLD": int(env.get("BB_LOW_BATTERY_THRESHOLD", "20")),
        # Interval of the "hourly" status alert (use 60 only for testing).
        "BB_HOURLY_SECONDS": int(env.get("BB_HOURLY_SECONDS", "3600")),
    }
