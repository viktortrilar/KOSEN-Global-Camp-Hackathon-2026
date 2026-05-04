"""
CoolWatch CV detector.
- YOLOv8 nano  → person detection → publishes `occupied`
- Frame diff   → door/window ROIs → publishes openings state

Both are published together on room/{ROOM}/openings so main.py
handles them in one place.

Model downloads automatically on first run (~6MB) to YOLO_CONFIG_DIR
which is mounted as a volume so it persists across restarts.
"""
import io, os, time, json, sys

os.environ.setdefault("YOLO_CONFIG_DIR", "/data/yolo")  # persist model across restarts

import numpy as np
import requests
from PIL import Image
import paho.mqtt.client as mqtt
from ultralytics import YOLO

CAMERA_URL  = os.getenv("CAMERA_URL",  "http://192.168.179.x:8080").rstrip("/")
SHOT_URL    = CAMERA_URL + "/shot.jpg"
MQTT_HOST   = os.getenv("MQTT_HOST",   "mosquitto")
MQTT_PORT   = int(os.getenv("MQTT_PORT", 1883))
ROOM        = os.getenv("ROOM",        "sendai_lab")
ROIS_FILE   = os.getenv("ROIS_FILE",   "/data/rois.json")
THRESHOLD   = float(os.getenv("DIFF_THRESHOLD", "0.05"))
INTERVAL    = float(os.getenv("INTERVAL",       "2.0"))
PERSON_CONF = float(os.getenv("PERSON_CONF",    "0.5"))

print("[CV] Loading YOLOv8n model...")
model = YOLO("yolov8n.pt")
print("[CV] Model ready.")


def load_rois() -> dict:
    try:
        with open(ROIS_FILE) as f:
            data = json.load(f)
        print(f"[CV] ROIs loaded: {list(data.keys())}")
        return data
    except FileNotFoundError:
        print(f"[CV] WARNING: {ROIS_FILE} not found — run calibrate.py first. Openings will not be detected.")
        return {}


def fetch_frame() -> tuple[np.ndarray | None, np.ndarray | None]:
    """Returns (rgb, gray) numpy arrays, or (None, None) on failure."""
    try:
        resp = requests.get(SHOT_URL, timeout=3.0)
        resp.raise_for_status()
        img  = Image.open(io.BytesIO(resp.content))
        rgb  = np.array(img.convert("RGB"),  dtype=np.uint8)
        gray = np.array(img.convert("L"),    dtype=np.uint8)
        return rgb, gray
    except Exception as e:
        print(f"[CV] Frame fetch failed: {e}")
        return None, None


def capture_reference() -> np.ndarray:
    print(f"[CV] Waiting for camera at {SHOT_URL}...")
    while True:
        _, gray = fetch_frame()
        if gray is not None:
            print("[CV] Reference frame captured.")
            return gray
        time.sleep(3)


def detect_person(rgb: np.ndarray) -> bool:
    results = model.predict(rgb, verbose=False, conf=PERSON_CONF, classes=[0])
    return len(results[0].boxes) > 0


def diff_ratio(ref: np.ndarray, cur: np.ndarray, roi: list[int]) -> float:
    x1, y1, x2, y2 = roi
    a = ref[y1:y2, x1:x2].astype(np.int16)
    b = cur[y1:y2, x1:x2].astype(np.int16)
    return float((np.abs(a - b) > 30).mean())


def main():
    rois      = load_rois()
    reference = capture_reference()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    while True:
        t0 = time.time()

        rgb, gray = fetch_frame()
        if rgb is None:
            time.sleep(2)
            continue

        occupied = detect_person(rgb)

        openings = {
            name: ("open" if diff_ratio(reference, gray, roi) > THRESHOLD else "closed")
            for name, roi in rois.items()
        }

        payload = {
            "timestamp": time.time(),
            "room":      ROOM,
            "occupied":  occupied,
            "openings":  openings,
        }
        client.publish(f"room/{ROOM}/openings", json.dumps(payload))
        print(f"[CV] {ROOM} — person: {occupied}, openings: {openings}")

        time.sleep(max(0.0, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
