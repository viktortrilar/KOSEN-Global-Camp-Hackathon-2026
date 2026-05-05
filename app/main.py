import asyncio, json, os, time
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
from database import init_db, insert_reading, insert_opening, get_readings, get_latest, get_active_alerts, resolve_alert
from alerts import evaluate
from simulator import simulate

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))

ROOMS = ["sendai_lab", "server_room", "meeting_room1", "meeting_room2", "office"]

_room_state: dict[str, dict] = {}  # latest sensor payload per room, used for heat_leak eval on opening events

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        for ws in self.active:
            try:
                await ws.send_json(data)
            except:
                pass

manager = ConnectionManager()
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
_loop: asyncio.AbstractEventLoop = None

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        room    = payload.get("room")
        topic   = msg.topic
        if "sensors" in topic:
            asyncio.run_coroutine_threadsafe(handle_sensors(room, payload), _loop)
        elif "openings" in topic:
            asyncio.run_coroutine_threadsafe(handle_openings(room, payload), _loop)
    except Exception as e:
        print(f"MQTT error: {e}")

async def handle_sensors(room: str, payload: dict):
    _room_state[room] = payload
    for key in ["temperature", "humidity", "co2", "power"]:
        if key in payload:
            await insert_reading(room, key, payload[key])
    latest = await get_latest(room)
    openings = {o["name"]: o["state"] for o in latest["openings"]}
    await evaluate(room, payload, openings)
    latest = await get_latest(room)
    await manager.broadcast({"event": "update", "room": room, "data": latest})

async def handle_openings(room: str, payload: dict):
    for name, state in payload.get("openings", {}).items():
        await insert_opening(room, name, state)
    if room in _room_state:
        if "occupied" in payload:
            _room_state[room]["occupied"] = payload["occupied"]
        if "person_count" in payload:
            _room_state[room]["person_count"] = payload["person_count"]
        latest = await get_latest(room)
        openings = {o["name"]: o["state"] for o in latest["openings"]}
        person_count = _room_state[room].get("person_count", 0)
        await evaluate(room, _room_state[room], openings, person_count)
    latest = await get_latest(room)
    await manager.broadcast({"event": "update", "room": room, "data": latest})

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_event_loop()
    await init_db()
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.subscribe("room/+/sensors")
    mqtt_client.subscribe("room/+/openings")
    mqtt_client.loop_start()
    if os.getenv("RUN_SIMULATOR", "true").lower() == "true":
        asyncio.create_task(simulate(mqtt_client))
    yield
    mqtt_client.loop_stop()

app = FastAPI(title="CoolWatch API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def root():
    return {"status": "ok", "project": "CoolWatch"}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "mqtt": "connected",
        "db": "connected",
        "cv_stream": os.getenv("CV_STREAM_URL", ""),
    }

@app.get("/rooms")
async def list_rooms():
    return {"rooms": ROOMS}

@app.get("/rooms/{room}")
async def room_status(room: str):
    return await get_latest(room)

@app.get("/rooms/{room}/history/{sensor}")
async def sensor_history(room: str, sensor: str, hours: int = 24):
    data = await get_readings(room, sensor, hours)
    return {"room": room, "sensor": sensor, "data": data}

@app.get("/rooms/{room}/alerts")
async def room_alerts(room: str):
    return {"alerts": await get_active_alerts(room)}

@app.post("/alerts/{alert_id}/resolve")
async def resolve(alert_id: int):
    await resolve_alert(alert_id)
    return {"resolved": alert_id}

class OpeningUpdate(BaseModel):
    room: str
    opening: str   # "door" or "window"
    state: str     # "open" or "closed"

@app.post("/simulate/opening")
async def simulate_opening(update: OpeningUpdate):
    payload = {
        "timestamp": time.time(),
        "room":      update.room,
        "openings":  {update.opening: update.state},
    }
    mqtt_client.publish(f"room/{update.room}/openings", json.dumps(payload))
    return {"triggered": payload}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        for room in ROOMS:
            latest = await get_latest(room)
            await ws.send_json({"event": "update", "room": room, "data": latest})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
