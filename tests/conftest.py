import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "analysis"))

import app as backend  # noqa: E402


@pytest.fixture
def client(tmp_path):
    """Flask test client backed by a fresh SQLite file."""
    backend.app.config.update(TESTING=True, BB_DB_PATH=str(tmp_path / "test.db"))
    backend.init_db()
    with backend.app.test_client() as c:
        yield c


@pytest.fixture
def post_battery(client):
    def _post(device_id="test-mac", device_type="mac", percent=50, charging=False, **extra):
        payload = {
            "device_id": device_id,
            "device_type": device_type,
            "battery_percent": percent,
            "is_charging": charging,
            **extra,
        }
        return client.post("/battery", json=payload)
    return _post
