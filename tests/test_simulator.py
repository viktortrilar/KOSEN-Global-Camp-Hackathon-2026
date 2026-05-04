import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import simulator


# ── helper functions ──────────────────────────────────────────────────────────

def test_noisy_stays_close_to_value():
    for _ in range(100):
        result = simulator.noisy(20.0, noise=0.5)
        assert 15.0 < result < 25.0  # well within 10-sigma

def test_noisy_default_noise():
    for _ in range(50):
        result = simulator.noisy(100.0)
        assert 95.0 < result < 105.0

def test_day_cycle_stays_within_amplitude():
    base, amp = 22.0, 3.0
    for _ in range(50):
        result = simulator.day_cycle(base, amp)
        assert (base - amp - 0.001) <= result <= (base + amp + 0.001)

def test_day_cycle_base_zero_amplitude():
    """With amplitude=0 the value should equal the base exactly."""
    assert simulator.day_cycle(20.0, 0) == 20.0


# ── payload structure ─────────────────────────────────────────────────────────

async def test_simulate_publishes_to_all_rooms():
    mock_client = MagicMock()
    with patch("simulator.asyncio.sleep", new_callable=AsyncMock,
               side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await simulator.simulate(mock_client)

    published_topics = [call[0][0] for call in mock_client.publish.call_args_list]
    for room in simulator.ROOMS:
        assert f"room/{room}/sensors"  in published_topics
        assert f"room/{room}/openings" in published_topics

async def test_simulate_sensor_payload_has_required_fields():
    mock_client = MagicMock()
    with patch("simulator.asyncio.sleep", new_callable=AsyncMock,
               side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await simulator.simulate(mock_client)

    sensors_calls = [
        json.loads(call[0][1])
        for call in mock_client.publish.call_args_list
        if "sensors" in call[0][0]
    ]
    required = {"timestamp", "room", "temperature", "humidity", "co2", "power", "ac_on", "occupied"}
    for payload in sensors_calls:
        assert required.issubset(payload.keys())

async def test_simulate_openings_payload_has_door_and_window():
    mock_client = MagicMock()
    with patch("simulator.asyncio.sleep", new_callable=AsyncMock,
               side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await simulator.simulate(mock_client)

    openings_calls = [
        json.loads(call[0][1])
        for call in mock_client.publish.call_args_list
        if "openings" in call[0][0]
    ]
    for payload in openings_calls:
        assert "door"   in payload["openings"]
        assert "window" in payload["openings"]

async def test_simulate_server_room_unoccupied():
    """server_room must publish occupied=False to keep the empty_room alert active."""
    mock_client = MagicMock()
    with patch("simulator.asyncio.sleep", new_callable=AsyncMock,
               side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await simulator.simulate(mock_client)

    server_sensors = next(
        json.loads(call[0][1])
        for call in mock_client.publish.call_args_list
        if call[0][0] == "room/server_room/sensors"
    )
    assert server_sensors["occupied"] is False
    assert server_sensors["ac_on"]    is True

async def test_simulate_five_rooms_published():
    mock_client = MagicMock()
    with patch("simulator.asyncio.sleep", new_callable=AsyncMock,
               side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await simulator.simulate(mock_client)

    rooms_published = {
        json.loads(call[0][1])["room"]
        for call in mock_client.publish.call_args_list
    }
    assert rooms_published == set(simulator.ROOMS.keys())
