"""
CoolWatch CV detector.
Grabs a frame every INTERVAL seconds, runs YOLO, blurs faces, publishes MQTT,
and serves the annotated frame as an MJPEG stream / snapshot on :STREAM_PORT.
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
INTERVAL    = float(os.getenv("INTERVAL",       "3.0"))
PERSON_CONF = float(os.getenv("PERSON_CONF",    "0.5"))
STREAM_PORT = int(os.getenv("STREAM_PORT",      "8001"))
FACE_BLUR   = os.getenv("FACE_BLUR", "true").lower() == "true"
INFER_W     = 640
INFER_H     = 360

print("[CV] Loading YOLOv8n model...")
model = YOLO("yolov8n.pt")
print("[CV] Model ready.")

# try OpenCV Haar cascade for more accurate face localization; fallback to box-heuristic
_FACE_CASCADE = None
try:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    _FACE_CASCADE = cv2.CascadeClassifier(cascade_path)
    if _FACE_CASCADE.empty():
        print(f"[CV] WARNING: face cascade not found at {cascade_path} — will use box heuristic")
        _FACE_CASCADE = None
    else:
        print(f"[CV] Face cascade loaded: {cascade_path}")
except Exception:
    _FACE_CASCADE = None

# ── shared state ──────────────────────────────────────────────────────────────

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


def blur_faces(frame: np.ndarray, person_boxes: list) -> np.ndarray:
    """Blur faces for privacy.

    Strategy:
    - If OpenCV Haar cascade is available, detect faces and pixelate a trimmed central region
      (trim top to avoid hair being blurred).
    - Otherwise fall back to the previous person-box top-quarter heuristic with a small
      downward offset to reduce hair capture.
    """
    if not FACE_BLUR:
        return frame

    h_frame, w_frame = frame.shape[:2]

    # First attempt: Haar cascade
    if _FACE_CASCADE is not None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = _FACE_CASCADE.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(30, 30),
        )
        if len(faces) > 0:
            for (x, y, w, h) in faces:
                # trim top (hair) and bottom slightly to focus on face center
                top_crop = int(h * 0.15)
                bottom_crop = int(h * 0.10)
                y1 = max(0, y + top_crop)
                y2 = min(h_frame, y + h - bottom_crop)
                x1 = max(0, x)
                x2 = min(w_frame, x + w)
                roi = frame[y1:y2, x1:x2]
                if roi.size == 0:
                    continue
                small_w = max(1, (x2 - x1) // 12)
                small_h = max(1, (y2 - y1) // 12)
                tiny = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
                frame[y1:y2, x1:x2] = cv2.resize(
                    tiny, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST
                )
            return frame

    # Fallback: person-box heuristic (top region, shifted slightly down to avoid hair)
    for (x1, y1, x2, y2, _) in person_boxes:
        box_h = max(1, y2 - y1)
        # start a little below the top (8% of box) and take ~22% of height
        start_y = y1 + int(box_h * 0.08)
        face_h = max(1, int(box_h * 0.22))
        fy1 = max(0, start_y)
        fy2 = min(h_frame, start_y + face_h)
        fx1 = max(0, x1)
        fx2 = min(w_frame, x2)
        roi = frame[fy1:fy2, fx1:fx2]
        if roi.size == 0:
            continue
        small_w = max(1, (fx2 - fx1) // 12)
        small_h = max(1, (fy2 - fy1) // 12)
        tiny = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        frame[fy1:fy2, fx1:fx2] = cv2.resize(
            tiny, (fx2 - fx1, fy2 - fy1), interpolation=cv2.INTER_NEAREST
        )
    return frame


def diff_ratio(ref: np.ndarray, cur: np.ndarray, roi: list[int]) -> float:
    x1, y1, x2, y2 = roi
    a = ref[y1:y2, x1:x2].astype(np.int16)
    b = cur[y1:y2, x1:x2].astype(np.int16)
    return float((np.abs(a - b) > 30).mean())


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
                time.sleep(0.1)
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
    global _latest_jpeg

    print(f"[CV] Waiting for stream at {CAMERA_URL}...")
    reference = None

    while True:
        t0 = time.time()

        bgr, gray = fetch_frame()
        if bgr is None:
            time.sleep(0.5)
            continue

        if reference is None:
            reference = gray.copy()
            print("[CV] Reference frame captured.")

        h, w  = bgr.shape[:2]
        small = cv2.resize(bgr, (INFER_W, INFER_H))
        sx, sy = w / INFER_W, h / INFER_H

        results = model.predict(small, verbose=False, conf=PERSON_CONF, classes=[0])
        boxes = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            boxes.append((int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy), conf))
        count = len(boxes)

        openings = {
            name: ("open" if diff_ratio(reference, gray, roi) > THRESHOLD else "closed")
            for name, roi in rois.items()
        }

        frame = bgr.copy()
        blur_faces(frame, boxes)

        for (x1, y1, x2, y2, conf) in boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"person {conf:.2f}", (x1, max(y1 - 6, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        for name, state in openings.items():
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

        payload = {
            "timestamp":    time.time(),
            "room":         ROOM,
            "occupied":     count > 0,
            "person_count": count,
            "openings":     openings,
        }
        client.publish(f"room/{ROOM}/openings", json.dumps(payload))
        print(f"[CV] {ROOM} — people: {count}, openings: {openings}, "
              f"total: {(time.time()-t0)*1000:.0f}ms")

        elapsed = time.time() - t0
        time.sleep(max(0.0, INTERVAL - elapsed))


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    rois = load_rois()
    start_stream_server()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    inference_loop(rois, client)


if __name__ == "__main__":
    main()
