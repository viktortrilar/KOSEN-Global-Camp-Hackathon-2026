# CoolWatch

> Closing the loop on energy waste — from room camera to your pocket

**KOSEN Global Camp Hackathon 2026 — Mayekawa Ideathon, Sendai Japan**  
Theme: *"The Earth is Closed, Not Open"* — energy is finite, waste is unacceptable

CoolWatch is a real-time room monitoring system that detects energy waste in cooled spaces. It combines computer vision (person detection + door/window state) with simulated IoT sensors to identify empty rooms with AC running, heat leaks through open doors/windows, and abnormal power consumption — then alerts building managers via a mobile app.

Sensor, database, and camera inputs can run on a Raspberry Pi or a phone camera, depending on the demo setup.

---

## Architecture

```
Pi (sensor publisher)          Laptop
      │                           │
simulator.py ──MQTT──► Mosquitto (1883)
                             │
                        FastAPI :8000
                        ├── SQLite
                        ├── Alert Engine (¥/hr cost)
                        ├── REST API
                        └── WebSocket
                             │
                    ┌────────┴────────┐
               Flutter App       CV Service
               (phone)           ├── YOLOv8n → occupied
                             Phone cam │   └── frame diff → door/window
                         /shot.jpg ◄──┘
```

### MQTT Topics

```
room/{room}/sensors   — temperature, humidity, CO₂, power, ac_on, occupied
room/{room}/openings  — door/window state + CV-detected occupied
```

### Rooms

| Room | Base Temp | Base Power | AC | Occupied | Notes |
|---|---|---|---|---|---|
| sendai_lab | 22°C | 800W | on | yes | CV target room |
| server_room | 18°C | 2400W | on | **no** | Permanent alerts (demo) |
| meeting_room1 | 23°C | 500W | on | yes | |
| meeting_room2 | 25°C | 150W | off | no | Quiet room, no alerts |
| office | 21°C | 1200W | on | yes | |

---

## Quick Start

### Option A — Everything on laptop (dev mode)

```bash
docker compose up -d
# Simulator runs inside the app container (RUN_SIMULATOR=true default)
```

### Option B — Pi as sensor publisher, laptop as server (demo mode)

```bash
# Laptop
RUN_SIMULATOR=false docker compose up -d

# Pi — only needs paho-mqtt
pip install paho-mqtt
MQTT_HOST=<laptop-LAN-ip> python app/simulator.py
```

### Phone camera (CV)

1. Install **IP Webcam** (Android, Pavel Khlebovich) from Google Play
2. Open → scroll to bottom → **Start server**
3. Note the IP shown, e.g. `192.168.1.42`
4. Verify stream: open `http://192.168.1.42:8080/video` in your browser (MJPEG preview)
5. Set `CAMERA_URL=http://192.168.1.42:8080/video` in `docker-compose.yml` or as an env var

### CV calibration (defines door/window regions)

Run locally — requires `pip install opencv-python`:

```bash
CAMERA_URL=http://<phone-ip>:8080/video python cv/calibrate.py
# Click 2 corners for door, then 2 corners for window
# Saves rois.json — copy it to ./data/ before starting the CV container
```

---

## Services

### Backend (`app/`)

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, MQTT subscriber, WebSocket broadcast |
| `database.py` | Async SQLite helpers (aiosqlite) |
| `alerts.py` | Alert evaluation engine with ¥/hr cost calculation |
| `simulator.py` | Sensor data publisher — runs in Docker or standalone on Pi |

### CV Service (`cv/`)

| File | Purpose |
|---|---|
| `detector.py` | YOLOv8n person detection + frame diff for door/window — publishes person count to MQTT |
| `calibrate.py` | GUI tool to define door/window ROIs — run locally before demo |

**Privacy & Stability:**
- Face blur enabled by default (`FACE_BLUR=true`) using Haar cascade + temporal smoothing to reduce jitter
- Detects faces on downscaled frame (fast) and smooths detection history over 3 frames (default `SMOOTH_WINDOW`)
- Publishes `person_count` in `room/{room}/openings` payload for Flutter app to display

**Performance Tuning:**
- `INFER_W=640, INFER_H=360` — inference frame size (resize input before YOLO)
- `STREAM_W/STREAM_H` — optional resize of output MJPEG stream for lower bandwidth
- `HAAR_MIN_NEIGHBORS=4, HAAR_MIN_SIZE=24` — Haar cascade sensitivity
- Customize via `docker-compose.yml` env vars or command-line

YOLOv8n model (~6MB) downloads automatically on first run and is cached in `./data/yolo/`.

### Flutter App (`coolwatcher/`)

**Real-time MQTT subscriptions:**
- Subscribes to `room/+/sensors` — receives temperature, humidity, CO₂, power, AC status
- Subscribes to `room/+/openings` — receives door/window state and **person count**

**Dashboard display:**
- Lists all 5 rooms with live occupancy: `"ID: sendai_lab • 3 people • ACTIVE"`
- Tap room → detailed view with sensor history charts (1-hour window)
- Tap chart buttons to switch between temperature, humidity, CO₂, and power consumption

**Build & run:**
```bash
cd coolwatcher
flutter pub get
flutter run -d <device>
```

Broker IP is hardcoded to `192.168.179.24` in `lib/main.dart`; update for your network.

---

## API

Base URL: `http://localhost:8000`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Health check |
| GET | `/rooms` | List all rooms |
| GET | `/rooms/{room}` | Latest sensors + openings + active alerts |
| GET | `/rooms/{room}/history/{sensor}?hours=24` | Historical sensor data |
| GET | `/rooms/{room}/alerts` | Active unresolved alerts |
| POST | `/alerts/{id}/resolve` | Resolve an alert |
| POST | `/simulate/opening` | Trigger door/window state (demo tool) |
| WS | `/ws` | Real-time room updates |

**Simulate opening** (demo fallback when CV isn't running):
```bash
curl -X POST http://localhost:8000/simulate/opening \
  -H 'Content-Type: application/json' \
  -d '{"room": "sendai_lab", "opening": "door", "state": "open"}'
```

---

## Alert Engine

Electricity cost: **¥28.93/kWh** (Japan commercial rate, 2025)  
Cost formula: `power_W × 0.02893 = ¥/hr`

| Alert | Condition | Severity |
|---|---|---|
| `heat_leak` | door or window open + AC on | high |
| `empty_room` | not occupied + AC on + power > 200W | medium |
| `co2_critical` | CO₂ > 1500ppm | high |
| `co2_high` | CO₂ > 1000ppm | medium |
| `power_spike` | power > 1500W | high |
| `overcooling` | temp < 18°C + AC on | low |
| `humidity_high` | humidity > 70% | medium |

Alerts deduplicate — only one active alert per type per room at a time. Resolving one allows it to re-fire if conditions persist.

---

## Testing

```bash
pip install -r app/requirements.txt -r requirements-dev.txt
python -m pytest tests/ -v
```

77 tests across 5 files:

| File | Coverage |
|---|---|
| `test_alerts.py` | All 7 alert types, boundary conditions, severity, ¥ cost in messages |
| `test_database.py` | CRUD, alert deduplication, resolve/refire cycle, room isolation |
| `test_api.py` | All REST endpoints, MQTT publish verification, history queries |
| `test_simulator.py` | `noisy()`/`day_cycle()` math, payload schema, 5-room coverage |
| `test_cv.py` | `diff_ratio()` with controlled arrays, ROI loading, frame fetch, YOLO args |

---

## Demo Story

1. Open Flutter app — 5 rooms, live updating via WebSocket
2. Tap **Server Room** — `empty_room` alert already active (AC on, nobody home)
3. Point phone camera at lab door, open the door
4. Alert fires: *"Door OPEN while AC running — ¥23.1/hr wasted"*
5. Resolve alert — disappears from app
6. Close with carbon impact calculation

---

## Design Decisions

- **SQLite over InfluxDB** — SD card on Pi is ~469MB free; SQLite is zero overhead
- **No Grafana** — Flutter handles charts via fl_chart
- **Pillow+numpy over OpenCV in CV container** — saves ~90MB on the Pi; `shot.jpg` polling is sufficient for 2s detection interval
- **YOLOv8n for person, frame diff for doors** — COCO doesn't have "door open/closed"; frame diff is reliable and needs no training data
- **Phone as camera** — no Pi camera module available; IP Webcam streams MJPEG over LAN
- **Single JSON payload per MQTT topic** — atomic, easy to parse, one message per room per tick
