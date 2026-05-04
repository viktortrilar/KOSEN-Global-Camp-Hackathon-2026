import json
import pytest
import database
import main as main_module
from httpx import AsyncClient, ASGITransport
from main import app

ROOMS = ["sendai_lab", "server_room", "meeting_room1", "meeting_room2", "office"]


@pytest.fixture
async def client(db, monkeypatch):
    """FastAPI test client wired to the temp DB; simulator disabled."""
    monkeypatch.setenv("RUN_SIMULATOR", "false")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── basic health ──────────────────────────────────────────────────────────────

async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


# ── rooms ─────────────────────────────────────────────────────────────────────

async def test_list_rooms(client):
    r = await client.get("/rooms")
    assert r.status_code == 200
    assert set(r.json()["rooms"]) == set(ROOMS)

async def test_room_status_structure(client):
    r = await client.get("/rooms/sendai_lab")
    assert r.status_code == 200
    body = r.json()
    assert "sensors"  in body
    assert "openings" in body
    assert "alerts"   in body

async def test_room_status_empty_initially(client):
    r = await client.get("/rooms/sendai_lab")
    body = r.json()
    assert body["sensors"]["temperature"] is None
    assert body["openings"] == []
    assert body["alerts"]   == []


# ── sensor history ────────────────────────────────────────────────────────────

async def test_history_empty(client):
    r = await client.get("/rooms/sendai_lab/history/temperature")
    assert r.status_code == 200
    body = r.json()
    assert body["room"]   == "sendai_lab"
    assert body["sensor"] == "temperature"
    assert body["data"]   == []

async def test_history_returns_inserted_data(client):
    await database.insert_reading("sendai_lab", "temperature", 22.5)
    r = await client.get("/rooms/sendai_lab/history/temperature?hours=1")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["value"] == 22.5

async def test_history_multiple_sensors_independent(client):
    await database.insert_reading("sendai_lab", "temperature", 22.5)
    await database.insert_reading("sendai_lab", "humidity",    55.0)
    temp_data = (await client.get("/rooms/sendai_lab/history/temperature?hours=1")).json()["data"]
    hum_data  = (await client.get("/rooms/sendai_lab/history/humidity?hours=1")).json()["data"]
    assert len(temp_data) == 1
    assert len(hum_data)  == 1


# ── alerts ────────────────────────────────────────────────────────────────────

async def test_room_alerts_empty(client):
    r = await client.get("/rooms/sendai_lab/alerts")
    assert r.status_code == 200
    assert r.json()["alerts"] == []

async def test_room_alerts_returns_active(client):
    await database.insert_alert("sendai_lab", "heat_leak", "high", "door open")
    r = await client.get("/rooms/sendai_lab/alerts")
    alerts = r.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["type"] == "heat_leak"

async def test_resolve_alert(client):
    await database.insert_alert("sendai_lab", "heat_leak", "high", "msg")
    alert_id = (await database.get_active_alerts("sendai_lab"))[0]["id"]
    r = await client.post(f"/alerts/{alert_id}/resolve")
    assert r.status_code == 200
    assert r.json()["resolved"] == alert_id
    assert await database.get_active_alerts("sendai_lab") == []


# ── simulate opening ──────────────────────────────────────────────────────────

async def test_simulate_opening_publishes_to_mqtt(client):
    from unittest.mock import MagicMock
    mock_publish = MagicMock()
    main_module.mqtt_client.publish = mock_publish

    r = await client.post("/simulate/opening", json={
        "room":    "sendai_lab",
        "opening": "door",
        "state":   "open",
    })
    assert r.status_code == 200
    mock_publish.assert_called_once()
    topic, payload_str = mock_publish.call_args[0]
    assert topic == "room/sendai_lab/openings"
    payload = json.loads(payload_str)
    assert payload["openings"]["door"] == "open"
    assert payload["room"]             == "sendai_lab"

async def test_simulate_opening_window_closed(client):
    from unittest.mock import MagicMock
    mock_publish = MagicMock()
    main_module.mqtt_client.publish = mock_publish

    r = await client.post("/simulate/opening", json={
        "room":    "meeting_room1",
        "opening": "window",
        "state":   "closed",
    })
    assert r.status_code == 200
    _, payload_str = mock_publish.call_args[0]
    assert json.loads(payload_str)["openings"]["window"] == "closed"

async def test_simulate_opening_returns_triggered_payload(client, mqtt_mock):
    r = await client.post("/simulate/opening", json={
        "room": "sendai_lab", "opening": "door", "state": "open"
    })
    body = r.json()
    assert "triggered" in body
    assert body["triggered"]["room"]             == "sendai_lab"
    assert body["triggered"]["openings"]["door"] == "open"
