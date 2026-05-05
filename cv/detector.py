"""
CoolWatch CV detector.
- Camera reader thread  → feeds raw frames at camera FPS
- Inference loop        → YOLO on 640×360 resized frames, updates box state
- Stream encoder thread → overlays boxes on raw frames, encodes at ~30fps
- MJPEG server          → serves annotated stream on :STREAM_PORT

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
INTERVAL    = float(os.getenv("INTERVAL",       "0.0"))   # 0 = as fast as possible
PERSON_CONF = float(os.getenv("PERSON_CONF",    "0.5"))
STREAM_PORT = int(os.getenv("STREAM_PORT",      "8001"))
INFER_W     = 640
INFER_H     = 360

print("[CV] Loading YOLOv8n model...")
model = YOLO("yolov8n.pt")
print("[CV] Model ready.")

# ── shared state ──────────────────────────────────────────────────────────────

_raw_lock  = threading.Lock()
_raw_frame: np.ndarray | None = None
_raw_gray:  np.ndarray | None = None

_det_lock        = threading.Lock()
_person_count: int        = 0
_opening_states: dict     = {}
_yolo_boxes: list         = []   # [(x1,y1,x2,y2,conf), ...] at full resolution

_frame_lock            = threading.Lock()
_latest_jpeg: bytes | None = None

_cap = None


# ── camera I/O ────────────────────────────────────────────────────────────────

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
            return None, None
        return frame, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    except Exception:
        _cap = None
        return None, None


# ── kept for unit tests ───────────────────────────────────────────────────────

def detect_person(bgr: np.ndarray) -> tuple[int, np.ndarray]:
    """Returns (person_count, annotated_bgr_frame). Used by tests."""
    results = model.predict(bgr, verbose=False, conf=PERSON_CONF, classes=[0])
    return len(results[0].boxes), results[0].plot()


def diff_ratio(ref: np.ndarray, cur: np.ndarray, roi: list[int]) -> float:
    x1, y1, x2, y2 = roi
    a = ref[y1:y2, x1:x2].astype(np.int16)
    b = cur[y1:y2, x1:x2].astype(np.int16)
    return float((np.abs(a - b) > 30).mean())


# ── threads ───────────────────────────────────────────────────────────────────

def camera_reader():
    """Continuously reads frames from the camera into shared state."""
    global _raw_frame, _raw_gray
    while True:
        bgr, gray = fetch_frame()
        if bgr is not None:
            with _raw_lock:
                _raw_frame = bgr
                _raw_gray  = gray
        else:
            time.sleep(0.05)


def stream_encoder(rois: dict):
    """Renders raw frames with the latest detection overlay at ~30fps."""
    global _latest_jpeg
    while True:
        with _raw_lock:
            if _raw_frame is None:
                time.sleep(0.033)
                continue
            frame = _raw_frame.copy()

        with _det_lock:
            count  = _person_count
            boxes  = list(_yolo_boxes)
            states = dict(_opening_states)

        # YOLO person boxes
        for (x1, y1, x2, y2, conf) in boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"person {conf:.2f}", (x1, max(y1 - 6, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # Door/window ROI boxes (red = open, green = closed)
        for name, state in states.items():
            if name in rois:
                x1, y1, x2, y2 = rois[name]
                color = (0, 0, 255) if state == "open" else (0, 200, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"{name}: {state}", (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.putText(frame, f"People: {count}", (10, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 2)

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with _frame_lock:
                _latest_jpeg = buf.tobytes()

        time.sleep(0.033)  # ~30fps cap


# ── MJPEG server ──────────────────────────────────────────────────────────────

class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

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
                time.sleep(0.033)
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


# ── inference loop (main thread) ──────────────────────────────────────────────

def inference_loop(rois: dict, client: mqtt.Client):
    global _person_count, _opening_states, _yolo_boxes

    # Wait for first camera frame
    print(f"[CV] Waiting for stream at {CAMERA_URL}...")
    while True:
        with _raw_lock:
            if _raw_gray is not None:
                reference = _raw_gray.copy()
                break
        time.sleep(0.05)
    print("[CV] Reference frame captured.")

    while True:
        t0 = time.time()

        with _raw_lock:
            if _raw_frame is None:
                time.sleep(0.05)
                continue
            bgr  = _raw_frame.copy()
            gray = _raw_gray.copy()

        # Resize for faster inference, scale boxes back to full resolution
        h, w   = bgr.shape[:2]
        small  = cv2.resize(bgr, (INFER_W, INFER_H))
        sx, sy = w / INFER_W, h / INFER_H

        results = model.predict(small, verbose=False, conf=PERSON_CONF, classes=[0])
        boxes   = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            boxes.append((int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy), conf))
        count = len(boxes)

        openings = {
            name: ("open" if diff_ratio(reference, gray, roi) > THRESHOLD else "closed")
            for name, roi in rois.items()
        }

        with _det_lock:
            _person_count   = count
            _opening_states = openings
            _yolo_boxes     = boxes

        payload = {
            "timestamp":    time.time(),
            "room":         ROOM,
            "occupied":     count > 0,
            "person_count": count,
            "openings":     openings,
        }
        client.publish(f"room/{ROOM}/openings", json.dumps(payload))
        print(f"[CV] {ROOM} — people: {count}, openings: {openings}, "
              f"inference: {(time.time()-t0)*1000:.0f}ms")

        elapsed = time.time() - t0
        if INTERVAL > 0:
            time.sleep(max(0.0, INTERVAL - elapsed))


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    global _latest_jpeg
    rois = load_rois()

    threading.Thread(target=camera_reader,          daemon=True).start()
    threading.Thread(target=stream_encoder, args=(rois,), daemon=True).start()

    start_stream_server()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    inference_loop(rois, client)


if __name__ == "__main__":
    main()
