"""
Global test setup.

paho and ultralytics are intercepted in sys.modules here — before any test
file can trigger their import — so that module-level code in main.py and
detector.py (mqtt.Client(), YOLO()) gets mocks instead of real objects.
"""
import sys
from unittest.mock import MagicMock

# --- paho mock (main.py does `import paho.mqtt.client as mqtt` at module level) ---
_mqtt_instance = MagicMock()
_mqtt_module   = MagicMock()
_mqtt_module.Client.return_value         = _mqtt_instance
_mqtt_module.CallbackAPIVersion          = MagicMock()
_mqtt_module.CallbackAPIVersion.VERSION2 = "v2"

sys.modules.setdefault("paho",             MagicMock())
sys.modules.setdefault("paho.mqtt",        MagicMock())
sys.modules.setdefault("paho.mqtt.client", _mqtt_module)

# --- ultralytics mock (detector.py does `from ultralytics import YOLO` + YOLO(...)) ---
sys.modules.setdefault("ultralytics", MagicMock())

# ---------------------------------------------------------------------------------
import pytest
import database


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """Temp SQLite DB, initialised and torn down per test."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    await database.init_db()


@pytest.fixture
def mqtt_mock():
    """The shared mock mqtt client instance; reset between tests."""
    _mqtt_instance.reset_mock()
    return _mqtt_instance
