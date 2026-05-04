import pytest
from unittest.mock import AsyncMock, patch
from alerts import evaluate

NORMAL = {
    "temperature": 22.0, "humidity": 55.0,
    "co2": 450.0, "power": 800.0,
    "ac_on": True, "occupied": True,
}


@pytest.fixture(autouse=True)
def mock_db():
    with patch("alerts.insert_alert", new_callable=AsyncMock):
        yield


# ── heat_leak ────────────────────────────────────────────────────────────────

async def test_heat_leak_door_open():
    alerts = await evaluate("lab", NORMAL, {"door": "open"})
    assert any(a["type"] == "heat_leak" for a in alerts)

async def test_heat_leak_window_open():
    alerts = await evaluate("lab", NORMAL, {"window": "open"})
    assert any(a["type"] == "heat_leak" for a in alerts)

async def test_heat_leak_both_open_fires_twice():
    alerts = await evaluate("lab", NORMAL, {"door": "open", "window": "open"})
    assert sum(1 for a in alerts if a["type"] == "heat_leak") == 2

async def test_heat_leak_no_fire_when_ac_off():
    sensors = {**NORMAL, "ac_on": False}
    alerts = await evaluate("lab", sensors, {"door": "open"})
    assert not any(a["type"] == "heat_leak" for a in alerts)

async def test_heat_leak_no_fire_when_closed():
    alerts = await evaluate("lab", NORMAL, {"door": "closed"})
    assert not any(a["type"] == "heat_leak" for a in alerts)

async def test_heat_leak_message_contains_cost():
    alerts = await evaluate("lab", NORMAL, {"door": "open"})
    hl = next(a for a in alerts if a["type"] == "heat_leak")
    assert "¥" in hl["message"]
    assert hl["severity"] == "high"


# ── empty_room ────────────────────────────────────────────────────────────────

async def test_empty_room_fires():
    sensors = {**NORMAL, "occupied": False}
    alerts = await evaluate("lab", sensors, {})
    assert any(a["type"] == "empty_room" for a in alerts)

async def test_empty_room_no_fire_when_occupied():
    alerts = await evaluate("lab", NORMAL, {})
    assert not any(a["type"] == "empty_room" for a in alerts)

async def test_empty_room_no_fire_when_ac_off():
    sensors = {**NORMAL, "occupied": False, "ac_on": False}
    alerts = await evaluate("lab", sensors, {})
    assert not any(a["type"] == "empty_room" for a in alerts)

async def test_empty_room_no_fire_below_power_threshold():
    sensors = {**NORMAL, "occupied": False, "power": 100.0}
    alerts = await evaluate("lab", sensors, {})
    assert not any(a["type"] == "empty_room" for a in alerts)


# ── co2 ───────────────────────────────────────────────────────────────────────

async def test_co2_high_fires():
    sensors = {**NORMAL, "co2": 1200.0}
    alerts = await evaluate("lab", sensors, {})
    assert any(a["type"] == "co2_high" for a in alerts)

async def test_co2_critical_fires():
    sensors = {**NORMAL, "co2": 1600.0}
    alerts = await evaluate("lab", sensors, {})
    assert any(a["type"] == "co2_critical" for a in alerts)

async def test_co2_critical_not_both():
    """Above 1500 should produce critical only, not high as well."""
    sensors = {**NORMAL, "co2": 1600.0}
    types = [a["type"] for a in await evaluate("lab", sensors, {})]
    assert "co2_critical" in types
    assert "co2_high" not in types

async def test_co2_normal_no_alert():
    alerts = await evaluate("lab", NORMAL, {})
    assert not any(a["type"] in ("co2_high", "co2_critical") for a in alerts)


# ── power_spike ───────────────────────────────────────────────────────────────

async def test_power_spike_fires():
    sensors = {**NORMAL, "power": 2000.0}
    alerts = await evaluate("lab", sensors, {})
    assert any(a["type"] == "power_spike" for a in alerts)

async def test_power_spike_boundary():
    sensors = {**NORMAL, "power": 1500.0}
    alerts = await evaluate("lab", sensors, {})
    assert not any(a["type"] == "power_spike" for a in alerts)

async def test_power_spike_severity():
    sensors = {**NORMAL, "power": 2000.0}
    spike = next(a for a in await evaluate("lab", sensors, {}) if a["type"] == "power_spike")
    assert spike["severity"] == "high"


# ── overcooling ───────────────────────────────────────────────────────────────

async def test_overcooling_fires():
    sensors = {**NORMAL, "temperature": 16.0}
    alerts = await evaluate("lab", sensors, {})
    assert any(a["type"] == "overcooling" for a in alerts)

async def test_overcooling_no_fire_ac_off():
    sensors = {**NORMAL, "temperature": 16.0, "ac_on": False}
    alerts = await evaluate("lab", sensors, {})
    assert not any(a["type"] == "overcooling" for a in alerts)

async def test_overcooling_boundary():
    sensors = {**NORMAL, "temperature": 18.0}
    alerts = await evaluate("lab", sensors, {})
    assert not any(a["type"] == "overcooling" for a in alerts)

async def test_overcooling_severity():
    sensors = {**NORMAL, "temperature": 16.0}
    alert = next(a for a in await evaluate("lab", sensors, {}) if a["type"] == "overcooling")
    assert alert["severity"] == "low"


# ── humidity_high ─────────────────────────────────────────────────────────────

async def test_humidity_high_fires():
    sensors = {**NORMAL, "humidity": 75.0}
    alerts = await evaluate("lab", sensors, {})
    assert any(a["type"] == "humidity_high" for a in alerts)

async def test_humidity_boundary():
    sensors = {**NORMAL, "humidity": 70.0}
    alerts = await evaluate("lab", sensors, {})
    assert not any(a["type"] == "humidity_high" for a in alerts)


# ── clean conditions ──────────────────────────────────────────────────────────

async def test_no_alerts_normal_conditions():
    alerts = await evaluate("lab", NORMAL, {"door": "closed", "window": "closed"})
    assert alerts == []

async def test_multiple_alerts_can_fire_together():
    sensors = {**NORMAL, "occupied": False, "co2": 1200.0}
    types = [a["type"] for a in await evaluate("lab", sensors, {"door": "open"})]
    assert "heat_leak"  in types
    assert "empty_room" in types
    assert "co2_high"   in types
