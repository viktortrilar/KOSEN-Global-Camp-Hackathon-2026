import pytest
import database


# ── readings ──────────────────────────────────────────────────────────────────

async def test_insert_and_get_reading(db):
    await database.insert_reading("lab", "temperature", 22.5)
    rows = await database.get_readings("lab", "temperature", hours=1)
    assert len(rows) == 1
    assert rows[0]["value"] == 22.5

async def test_get_readings_returns_empty_before_insert(db):
    rows = await database.get_readings("lab", "temperature", hours=1)
    assert rows == []

async def test_multiple_readings_ordered_asc(db):
    await database.insert_reading("lab", "temperature", 20.0)
    await database.insert_reading("lab", "temperature", 21.0)
    await database.insert_reading("lab", "temperature", 22.0)
    rows = await database.get_readings("lab", "temperature", hours=1)
    values = [r["value"] for r in rows]
    assert values == sorted(values)

async def test_readings_isolated_by_room(db):
    await database.insert_reading("lab",    "temperature", 22.0)
    await database.insert_reading("office", "temperature", 19.0)
    assert len(await database.get_readings("lab",    "temperature", hours=1)) == 1
    assert len(await database.get_readings("office", "temperature", hours=1)) == 1

async def test_readings_isolated_by_sensor(db):
    await database.insert_reading("lab", "temperature", 22.0)
    await database.insert_reading("lab", "humidity",    55.0)
    assert len(await database.get_readings("lab", "temperature", hours=1)) == 1
    assert len(await database.get_readings("lab", "humidity",    hours=1)) == 1


# ── openings ──────────────────────────────────────────────────────────────────

async def test_insert_opening(db):
    await database.insert_opening("lab", "door", "open")
    latest = await database.get_latest("lab")
    opening = next(o for o in latest["openings"] if o["name"] == "door")
    assert opening["state"] == "open"

async def test_latest_opening_reflects_most_recent(db):
    await database.insert_opening("lab", "door", "open")
    await database.insert_opening("lab", "door", "closed")
    latest = await database.get_latest("lab")
    opening = next(o for o in latest["openings"] if o["name"] == "door")
    assert opening["state"] == "closed"


# ── alerts ────────────────────────────────────────────────────────────────────

async def test_insert_and_get_alert(db):
    await database.insert_alert("lab", "heat_leak", "high", "test message")
    alerts = await database.get_active_alerts("lab")
    assert len(alerts) == 1
    assert alerts[0]["type"] == "heat_leak"
    assert alerts[0]["severity"] == "high"
    assert alerts[0]["message"] == "test message"

async def test_alert_deduplication_blocks_second_insert(db):
    await database.insert_alert("lab", "heat_leak", "high", "first")
    await database.insert_alert("lab", "heat_leak", "high", "second")
    alerts = await database.get_active_alerts("lab")
    assert len(alerts) == 1

async def test_different_alert_types_both_inserted(db):
    await database.insert_alert("lab", "heat_leak",  "high",   "msg1")
    await database.insert_alert("lab", "empty_room", "medium", "msg2")
    types = {a["type"] for a in await database.get_active_alerts("lab")}
    assert types == {"heat_leak", "empty_room"}

async def test_resolve_alert(db):
    await database.insert_alert("lab", "heat_leak", "high", "msg")
    alert_id = (await database.get_active_alerts("lab"))[0]["id"]
    await database.resolve_alert(alert_id)
    assert await database.get_active_alerts("lab") == []

async def test_resolved_alert_allows_reinsertion(db):
    await database.insert_alert("lab", "heat_leak", "high", "msg")
    alert_id = (await database.get_active_alerts("lab"))[0]["id"]
    await database.resolve_alert(alert_id)
    await database.insert_alert("lab", "heat_leak", "high", "msg again")
    assert len(await database.get_active_alerts("lab")) == 1

async def test_alerts_isolated_by_room(db):
    await database.insert_alert("lab",    "heat_leak",  "high",   "lab alert")
    await database.insert_alert("office", "empty_room", "medium", "office alert")
    lab_types    = {a["type"] for a in await database.get_active_alerts("lab")}
    office_types = {a["type"] for a in await database.get_active_alerts("office")}
    assert lab_types    == {"heat_leak"}
    assert office_types == {"empty_room"}

async def test_only_unresolved_alerts_returned(db):
    await database.insert_alert("lab", "heat_leak",  "high",   "1")
    await database.insert_alert("lab", "empty_room", "medium", "2")
    alert_id = (await database.get_active_alerts("lab"))[0]["id"]
    await database.resolve_alert(alert_id)
    assert len(await database.get_active_alerts("lab")) == 1


# ── get_latest structure ──────────────────────────────────────────────────────

async def test_get_latest_returns_correct_structure(db):
    await database.insert_reading("lab", "temperature", 21.5)
    await database.insert_reading("lab", "power",       750.0)
    latest = await database.get_latest("lab")
    assert set(latest.keys()) == {"sensors", "openings", "alerts"}
    assert latest["sensors"]["temperature"]["value"] == 21.5
    assert latest["sensors"]["power"]["value"]       == 750.0

async def test_get_latest_empty_room(db):
    latest = await database.get_latest("lab")
    assert latest["sensors"]["temperature"] is None
    assert latest["openings"] == []
    assert latest["alerts"]   == []
