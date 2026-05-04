import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "/data/coolwatch.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                room        TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                value       REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS openings (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                room      TEXT NOT NULL,
                name      TEXT NOT NULL,
                state     TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                room      TEXT NOT NULL,
                type      TEXT NOT NULL,
                severity  TEXT NOT NULL,
                message   TEXT NOT NULL,
                resolved  INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_room_time
            ON sensor_readings(room, timestamp)
        """)
        await db.commit()

async def insert_reading(room: str, sensor_type: str, value: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sensor_readings (room, sensor_type, value) VALUES (?,?,?)",
            (room, sensor_type, value)
        )
        await db.commit()

async def insert_opening(room: str, name: str, state: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO openings (room, name, state) VALUES (?,?,?)",
            (room, name, state)
        )
        await db.commit()

async def insert_alert(room: str, type: str, severity: str, message: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO alerts (room, type, severity, message) VALUES (?,?,?,?)",
            (room, type, severity, message)
        )
        await db.commit()

async def get_readings(room: str, sensor_type: str, hours: int = 24):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT timestamp, value FROM sensor_readings
            WHERE room = ? AND sensor_type = ?
            AND timestamp >= datetime('now', ? || ' hours')
            ORDER BY timestamp ASC
        """, (room, sensor_type, f"-{hours}"))
        rows = await cursor.fetchall()
        return [{"timestamp": r["timestamp"], "value": r["value"]} for r in rows]

async def get_latest(room: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sensors = {}
        for s in ["temperature", "humidity", "co2", "power"]:
            cursor = await db.execute("""
                SELECT value, timestamp FROM sensor_readings
                WHERE room = ? AND sensor_type = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (room, s))
            row = await cursor.fetchone()
            sensors[s] = {"value": row["value"], "timestamp": row["timestamp"]} if row else None

        cursor = await db.execute("""
            SELECT name, state, timestamp FROM openings
            WHERE room = ?
            AND timestamp = (
                SELECT MAX(timestamp) FROM openings o2
                WHERE o2.room = openings.room AND o2.name = openings.name
            )
        """, (room,))
        openings = await cursor.fetchall()

        cursor = await db.execute("""
            SELECT type, severity, message, timestamp FROM alerts
            WHERE room = ? AND resolved = 0
            ORDER BY timestamp DESC LIMIT 10
        """, (room,))
        alerts = await cursor.fetchall()

        return {
            "sensors": sensors,
            "openings": [{"name": r["name"], "state": r["state"], "timestamp": r["timestamp"]} for r in openings],
            "alerts":   [{"type": r["type"], "severity": r["severity"], "message": r["message"], "timestamp": r["timestamp"]} for r in alerts]
        }

async def get_active_alerts(room: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT id, type, severity, message, timestamp FROM alerts
            WHERE room = ? AND resolved = 0
            ORDER BY timestamp DESC
        """, (room,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def resolve_alert(alert_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE alerts SET resolved=1 WHERE id=?", (alert_id,))
        await db.commit()
