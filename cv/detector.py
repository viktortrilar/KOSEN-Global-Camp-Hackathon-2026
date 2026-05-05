"""
CoolWatch CV detector.
- YOLOv8 nano  → person count + bounding boxes
- Frame diff   → door/window ROI state
- MJPEG server → annotated stream on :STREAM_PORT/stream

Publishes room/{ROOM}/openings with person_count (int) and occupied (bool).
"""
import os, time, json, socketserver, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

os.environ.setdefault("YOLO_CONFIG_DIR", "/data/yolo")

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from ultralytics import YOLO

CAMERA_URL  = os.getenv("CAMERA_URL",  "http://192.168.179.18:8080/video")
MQTT_HOST   = os.getenv("MQTT_HOST",   "mosquitto")
MQTT_PORT   = int(os.getenv("MQTT_PORT", 1883))
ROOM        = os.getenv("ROOM",        "sendai_lab")
ROIS_FILE   = os.getenv("ROIS_FILE",   "/data/rois.json")
THRESHOLD   = float(os.getenv("DIFF_THRESHOLD", "0.05"))
INTERVAL    = float(os.getenv("INTERVAL",       "2.0"))
PERSON_CONF = float(os.getenv("PERSON_CONF",    "0.5"))
STREAM_PORT = int(os.getenv("STREAM_PORT",      "8001"))

print("[CV] Loading YOLOv8n model...")
model = YOLO("yolov8n.pt")
print("[CV] Model ready.")

_cap               = None
_frame_lock        = threading.Lock()
_latest_jpeg: bytes | None = None


def load_rois() -> dict:
    try:
        with open(ROIS_FILE) as f:
            data = json.load(f)
        print(f"[CV] ROIs loaded: {list(data.keys())}")
        return data
    except FileNotFoundError:
        print(f"[CV] WARNING: {ROIS_FILE} not found — run calibrate.py first.")
        return {}


def _get_cap() -> cv2.VideoCapture:
    global _cap
    if _cap is None or not _cap.isOpened():
        if _cap is not None:
            _cap.release()
        _cap = cv2.VideoCapture(CAMERA_URL)
    return _cap


def fetch_frame() -> tuple[np.ndarray | None, np.ndarray | None]:
    """Returns (bgr, gray) numpy arrays, or (None, None) on failure."""
    global _cap
    try:
        cap = _get_cap()
        ret, frame = cap.read()
        if not ret or frame is None:
            _cap = None
            print("[CV] Frame read failed, will reconnect")
            return None, None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return frame, gray
    except Exception as e:
        _cap = None
        print(f"[CV] Frame fetch failed: {e}")
        return None, None


def capture_reference() -> np.ndarray:
    print(f"[CV] Waiting for stream at {CAMERA_URL}...")
    while True:
        _, gray = fetch_frame()
        if gray is not None:
            print("[CV] Reference frame captured.")
            return gray
        time.sleep(3)


def detect_person(bgr: np.ndarray) -> tuple[int, np.ndarray]:
    """Returns (person_count, annotated_bgr_frame)."""
    results = model.predict(bgr, verbose=False, conf=PERSON_CONF, classes=[0])
    count     = len(results[0].boxes)
    annotated = results[0].plot()  # BGR array with YOLO boxes drawn
    return count, annotated


def diff_ratio(ref: np.ndarray, cur: np.ndarray, roi: list[int]) -> float:
    x1, y1, x2, y2 = roi
    a = ref[y1:y2, x1:x2].astype(np.int16)
    b = cur[y1:y2, x1:x2].astype(np.int16)
    return float((np.abs(a - b) > 30).mean())


# ── MJPEG stream server ───────────────────────────────────────────────────────

class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # suppress per-request logs

    def do_GET(self):
        if self.path in ("/stream", "/"):
            self._serve_mjpeg()
        elif self.path == "/snapshot":
            self._serve_snapshot()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_mjpeg(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                with _frame_lock:
                    frame = _latest_jpeg
                if frame:
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    )
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_snapshot(self):
        with _frame_lock:
            frame = _latest_jpeg
        if frame is None:
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.end_headers()
        self.wfile.write(frame)


def start_stream_server():
    server = _ThreadedHTTPServer(("0.0.0.0", STREAM_PORT), _StreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[CV] Stream at http://0.0.0.0:{STREAM_PORT}/stream")


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    rois      = load_rois()
    reference = capture_reference()

    start_stream_server()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    while True:
        t0 = time.time()

        bgr, gray = fetch_frame()
        if bgr is None:
            time.sleep(2)
            continue

        count, annotated = detect_person(bgr)

        openings = {
            name: ("open" if diff_ratio(reference, gray, roi) > THRESHOLD else "closed")
            for name, roi in rois.items()
        }

        # Draw door/window ROI boxes (red = open, green = closed)
        for name, state in openings.items():
            if name in rois:
                x1, y1, x2, y2 = rois[name]
                color = (0, 0, 255) if state == "open" else (0, 200, 0)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                cv2.putText(annotated, f"{name}: {state}", (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Person count overlay (top-left)
        cv2.putText(annotated, f"People: {count}", (10, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 2)

        _, jpeg_buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with _frame_lock:
            _latest_jpeg = jpeg_buf.tobytes()

        payload = {
            "timestamp":    time.time(),
            "room":         ROOM,
            "occupied":     count > 0,
            "person_count": count,
            "openings":     openings,
        }
        client.publish(f"room/{ROOM}/openings", json.dumps(payload))
        print(f"[CV] {ROOM} — people: {count}, openings: {openings}")

        time.sleep(max(0.0, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
