# CoolWatch — Project Plan
> AI-readable project document for KOSEN Global Camp Hackathon 2026
> Last updated: 2026-05-04

---

## Project Overview

**Name:** CoolWatch  
**Tagline:** Closing the loop on energy waste — from room camera to your pocket  
**Theme:** "The Earth is Closed, Not Open" — energy is finite, waste is unacceptable  
**Context:** Mayekawa Ideathon & Hackathon 2026, Sendai Japan  

CoolWatch is a real-time room monitoring system that uses computer vision and IoT sensors to detect energy waste in cooled spaces. It identifies scenarios like empty rooms with AC running, open doors/windows while cooling is active, and abnormal power consumption — then alerts building managers via a mobile app.

---

## Problem Statement

Buildings waste enormous amounts of energy through:
- AC running in unoccupied rooms
- Doors and windows left open while cooling is active
- Overcooling rooms beyond comfort requirements
- Machines running outside of scheduled hours

CoolWatch makes this waste **visible, quantified in ¥/hr, and actionable**.

---

## System Architecture

```
Phone Camera (MJPEG stream)
        ↓
CV Service (Docker, frame diff)
        ↓ publishes JSON
MQTT Broker (Mosquitto, port 1883)
        ↑ subscribes
FastAPI Backend (port 8000)
        ├── SQLite (time-series storage)
        ├── Alert Engine (¥ cost calculation)
        └── REST API + WebSocket
                ↓
        Flutter Mobile App
```

### MQTT Topic Structure

One topic per room, one JSON payload per message, published every 5 seconds:

```
coolwatch/Lab
coolwatch/Server_Room
coolwatch/Meeting_Room
```

### MQTT Payload Schema

```json
{
  "name":      "Lab",
  "timestamp": 1746342269.0,
  "sensors": {
    "temperature": { "value": 22.5,  "unit": "°C"  },
    "humidity":    { "value": 55.0,  "unit": "%"   },
    "co2":         { "value": 450.0, "unit": "ppm" },
    "power":       { "value": 800.0, "unit": "W"   }
  },
  "openings": {
    "door":   "closed",
    "window": "closed"
  },
  "ac_on":    true,
  "occupied": true
}
```

---

## Infrastructure

**Device:** Raspberry Pi 5 (8GB RAM, Debian Trixie)  
**Hostname:** raspi-sendai  
**IP:** 192.168.179.24  
**Runtime:** Docker + Docker Compose  
**Storage:** ~469MB free on SD card (tight — avoid large images)  

### Docker Services

| Service | Image | Port | Purpose |
|---|---|---|---|
| coolwatch-mqtt | eclipse-mosquitto:latest | 1883 | MQTT broker |
| coolwatch-app | python:3.13-slim (custom) | 8000 | FastAPI + simulator + alerts |
| coolwatch-cv | python:3.13-slim (custom) | none | Computer vision service |

---

## Repository Structure

```
KOSEN-Global-Camp-Hackathon-2026/
├── PLAN.md                        ← this file
├── README.md                      ← project overview
├── .gitignore
├── backend/
│   ├── docker-compose.yml
│   ├── mosquitto/
│   │   └── config/
│   │       └── mosquitto.conf
│   └── app/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── main.py                ← FastAPI app, MQTT subscriber, WebSocket
│       ├── database.py            ← SQLite async helpers
│       ├── simulator.py           ← fake sensor data publisher
│       └── alerts.py              ← alert evaluation engine
├── cv/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── detector.py                ← frame diff CV service
└── coolwatch_app/                 ← Flutter mobile app (teammate)
    ├── pubspec.yaml
    └── lib/
        ├── main.dart
        ├── models/
        ├── services/
        ├── screens/
        └── widgets/
```

---

## REST API Reference

Base URL: `http://192.168.179.24:8000`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Health check |
| GET | `/health` | Service status |
| GET | `/rooms` | List all rooms |
| GET | `/rooms/{room}` | Latest sensor data + alerts for a room |
| GET | `/rooms/{room}/history/{sensor}?hours=24` | Historical sensor data |
| GET | `/rooms/{room}/alerts` | Active unresolved alerts |
| POST | `/alerts/{id}/resolve` | Resolve an alert |
| POST | `/simulate/opening` | Manually trigger door/window state (demo tool) |
| WS | `/ws` | WebSocket — broadcasts room updates in real time |

### Example Responses

```json
GET /rooms
{
  "rooms": ["Lab", "Server_Room", "Meeting_Room"]
}

GET /rooms/Lab
{
  "sensors": {
    "temperature": { "value": 22.4, "timestamp": "2026-05-04 07:04:29" },
    "humidity":    { "value": 57.2, "timestamp": "2026-05-04 07:04:29" },
    "co2":         { "value": 456.9, "timestamp": "2026-05-04 07:04:29" },
    "power":       { "value": 809.8, "timestamp": "2026-05-04 07:04:29" }
  },
  "openings": [
    { "name": "door",   "state": "closed", "timestamp": "..." },
    { "name": "window", "state": "closed", "timestamp": "..." }
  ],
  "alerts": []
}

GET /rooms/Lab/history/temperature
{
  "room": "Lab",
  "sensor": "temperature",
  "data": [
    { "timestamp": "2026-05-04 06:00:00", "value": 21.3 },
    { "timestamp": "2026-05-04 06:05:00", "value": 21.5 }
  ]
}
```

---

## Alert Engine

**Electricity cost:** ¥28.93/kWh (Japan commercial rate, 2025)  
**Cost formula:** `power_W × 0.02893 = ¥/hr`  

| Alert Type | Condition | Severity |
|---|---|---|
| `heat_leak` | door or window OPEN + AC on | high |
| `empty_room` | not occupied + AC on + power > 200W | medium |
| `co2_high` | CO₂ > 1000ppm | medium |
| `co2_critical` | CO₂ > 1500ppm | high |
| `power_spike` | power > 1500W | high |
| `overcooling` | temp < 18°C + AC on | low |
| `humidity_high` | humidity > 70% | medium |

---

## Computer Vision Service

**Goal:** Detect whether doors and windows are open or closed from a phone camera stream.  
**Method:** Frame differencing (OpenCV) — no model training required.  
**Input:** MJPEG stream from phone (IP Webcam app on Android, port 8080).  
**Output:** Publishes to `coolwatch/{room}` MQTT topic, updating `openings.door` and `openings.window`.  

### How Frame Differencing Works

1. Capture a reference frame at startup (baseline = all closed)
2. Every 2 seconds, capture current frame
3. Compare ROI (region of interest) around door/window area
4. If pixel diff ratio exceeds threshold → state = "open"
5. Publish updated payload to MQTT

### Phone Camera Setup

- Android: Install **IP Webcam** app, start server, note the IP
- Stream URL: `http://{PHONE_IP}:8080/video`
- OpenCV reads: `cv2.VideoCapture("http://{PHONE_IP}:8080/video")`

### ROI Calibration

Run the detector once with `CALIBRATE=true` env var to display the camera feed and click to define door/window regions. Coordinates saved to `rois.json`.

---

## Flutter App

**Framework:** Flutter (iOS + Android)  
**State management:** Provider  
**Charts:** fl_chart  
**MQTT:** mqtt_client package (direct connection to broker)  
**REST:** http package (for history + alerts)  

### Data Flow in Flutter

```
Live tiles  → MQTT direct (coolwatch/#)
History     → REST GET /rooms/{room}/history/{sensor}
Alerts      → REST GET /rooms/{room}/alerts
Resolve     → REST POST /alerts/{id}/resolve
```

### Screen Structure

```
HomeScreen
└── RoomCard (per room)
    └── RoomDetailScreen
        ├── SensorChart (fl_chart, 24h history)
        ├── OpeningsStatus (door/window)
        └── AlertsList
```

---

## Simulated Rooms

| Room | Base Temp | Base Power | AC | Occupied |
|---|---|---|---|---|
| Lab | 22°C | 800W | on | true |
| Server Room | 18°C | 2400W | on | false |
| Meeting Room | 24°C | 400W | off | false |

Sensor values follow a sinusoidal day/night cycle with Gaussian noise.  
Server Room intentionally has `ac_on=true` + `occupied=false` to trigger `empty_room` alert.

---

## Demo Story (Presentation)

1. Open Flutter app — show 3 rooms live updating
2. Tap Lab — show sensor history chart
3. Trigger door open via CV (or `/simulate/opening` endpoint)
4. Alert fires: "Door OPEN while AC running — ¥23.1/hr wasted"
5. Show Server Room — `empty_room` alert already active
6. Resolve alert — disappears from app
7. Close with carbon impact calculation

---

## Task Status

### Done ✅
- MQTT broker (Mosquitto) running in Docker
- FastAPI backend with SQLite storage
- Sensor simulator (3 rooms, realistic data)
- Alert engine with ¥ cost calculation
- REST API (rooms, history, alerts, resolve)
- WebSocket broadcast
- Docker Compose stack

### In Progress 🔄
- Flutter app (teammate — MQTT + REST integration)

### Todo 📋
- CV service container (frame diff, phone MJPEG)
- `/simulate/opening` demo endpoint
- ROI calibration tool for CV
- README.md
- Presentation slides
- Full end-to-end demo dry run

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MQTT_HOST` | `mosquitto` | MQTT broker hostname |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `DB_PATH` | `/data/coolwatch.db` | SQLite database path |
| `CAMERA_URL` | `http://192.168.179.x:8080/video` | Phone MJPEG stream URL |

---

## Running the Stack

```bash
# On the Pi
cd ~/coolwatch
docker compose up -d

# Check logs
docker compose logs -f

# Restart after code changes
docker compose restart app

# From laptop — verify
curl http://192.168.179.24:8000/rooms
curl http://192.168.179.24:8000/rooms/Lab
```

---

## Key Design Decisions

- **SQLite over InfluxDB** — SD card space is tight (~469MB free), SQLite adds zero overhead
- **No Grafana** — Flutter handles all charts via fl_chart
- **Frame diff over YOLO** — no training data, runs on Pi 5 without GPU
- **Single JSON payload per MQTT topic** — atomic, easy to parse, one message per room per tick
- **Phone as camera** — no Pi camera module available; IP Webcam app streams MJPEG over LAN
- **¥28.93/kWh** — Japan commercial electricity rate (2025, GlobalPetrolPrices)