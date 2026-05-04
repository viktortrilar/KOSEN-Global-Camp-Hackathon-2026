"""
ROI calibration tool — run locally (NOT in Docker), requires a display.
pip install opencv-python  (not headless)

Usage:
  CAMERA_URL=http://phone_ip:8080/video python calibrate.py

Click the top-left and bottom-right corners to define each opening region.
Regions are saved to ROIS_FILE (default: rois.json in current dir).
Then copy rois.json to the ./data/ folder before starting the CV container.

Press 's' to save at any point, 'q' to quit without saving.
"""
import cv2, json, os, sys

CAMERA_URL  = os.getenv("CAMERA_URL", "http://192.168.179.x:8080").rstrip("/")
STREAM_URL  = CAMERA_URL + "/video"   # OpenCV needs the stream path; detector.py uses /shot.jpg
ROIS_FILE   = os.getenv("ROIS_FILE",  "rois.json")
OPENINGS   = ["door", "window"]

rois: dict   = {}
clicks: list = []
idx: int     = 0


def on_mouse(event, x, y, flags, _):
    global clicks, idx
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    clicks.append((x, y))
    if len(clicks) == 2:
        name = OPENINGS[idx]
        x1, y1 = clicks[0]
        x2, y2 = clicks[1]
        rois[name] = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
        print(f"  {name}: {rois[name]}")
        clicks.clear()
        idx += 1
        if idx >= len(OPENINGS):
            save_and_exit()
        else:
            print(f"Now define: {OPENINGS[idx]}")


def save_and_exit():
    with open(ROIS_FILE, "w") as f:
        json.dump(rois, f, indent=2)
    print(f"Saved to {ROIS_FILE} — copy it to ./data/ before starting the CV container.")
    sys.exit(0)


cap = cv2.VideoCapture(STREAM_URL)
if not cap.isOpened():
    print(f"Cannot open camera: {CAMERA_URL}")
    sys.exit(1)

cv2.namedWindow("CoolWatch Calibration")
cv2.setMouseCallback("CoolWatch Calibration", on_mouse)
print(f"Define regions for: {OPENINGS}")
print(f"Starting with: {OPENINGS[0]}")

while True:
    ok, frame = cap.read()
    if not ok:
        continue

    for name, roi in rois.items():
        cv2.rectangle(frame, (roi[0], roi[1]), (roi[2], roi[3]), (0, 255, 0), 2)
        cv2.putText(frame, name, (roi[0], roi[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    if idx < len(OPENINGS):
        label = f"Click 2 corners for: {OPENINGS[idx]}"
    else:
        label = "All defined. Press 's' to save."
    cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 100, 255), 2)

    cv2.imshow("CoolWatch Calibration", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord("s") and rois:
        save_and_exit()
    if key == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
