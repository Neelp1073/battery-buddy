"""Mac scripts: env-based settings and pmset parsing (no macOS needed)."""
import importlib
import sys
from pathlib import Path

import pytest

MAC_DIR = Path(__file__).resolve().parents[1] / "mac"


@pytest.fixture
def mac_module(monkeypatch):
    monkeypatch.syspath_prepend(str(MAC_DIR))

    def _load(name):
        for mod in (name, "settings"):
            sys.modules.pop(mod, None)
        return importlib.import_module(name)
    yield _load
    for mod in ("settings", "send_battery"):
        sys.modules.pop(mod, None)


def test_settings_defaults(monkeypatch, mac_module):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.delenv("DEVICE_ID", raising=False)
    settings = mac_module("settings")
    assert settings.BACKEND_URL == "http://127.0.0.1:5001"
    assert settings.DEVICE_ID == "neels-macbook"


def test_settings_from_env(monkeypatch, mac_module):
    monkeypatch.setenv("BACKEND_URL", "http://10.0.0.5:5001/")
    monkeypatch.setenv("DEVICE_ID", "work-mac")
    send_battery = mac_module("send_battery")
    assert send_battery.BATTERY_ENDPOINT == "http://10.0.0.5:5001/battery"
    assert send_battery.DEVICE_ID == "work-mac"


@pytest.mark.parametrize("output, expected", [
    ("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=123)\t76%; discharging; 4:12 remaining present: true", (76, False)),
    ("Now drawing from 'AC Power'\n -InternalBattery-0 (id=123)\t41%; charging; 1:05 remaining present: true", (41, True)),
    ("Now drawing from 'AC Power'\n -InternalBattery-0 (id=123)\t100%; charged; 0:00 remaining present: true", (100, False)),
])
def test_read_mac_battery_parses_pmset(monkeypatch, mac_module, output, expected):
    send_battery = mac_module("send_battery")
    monkeypatch.setattr(send_battery.subprocess, "check_output", lambda *a, **k: output)
    assert send_battery.read_mac_battery() == expected
