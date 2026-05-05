import json
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
import detector


# ── diff_ratio ────────────────────────────────────────────────────────────────

def test_diff_ratio_identical_images_is_zero():
    img = np.zeros((100, 100), dtype=np.uint8)
    assert detector.diff_ratio(img, img.copy(), [0, 0, 100, 100]) == 0.0

def test_diff_ratio_fully_different_images_is_high():
    ref = np.zeros((100, 100), dtype=np.uint8)
    cur = np.full((100, 100), 200, dtype=np.uint8)  # all pixels differ by 200
    assert detector.diff_ratio(ref, cur, [0, 0, 100, 100]) > 0.05

def test_diff_ratio_respects_roi_changed_area():
    ref = np.zeros((200, 200), dtype=np.uint8)
    cur = np.zeros((200, 200), dtype=np.uint8)
    cur[0:100, 0:100] = 200  # only top-left quadrant changed

    ratio_changed   = detector.diff_ratio(ref, cur, [0,   0,   100, 100])
    ratio_unchanged = detector.diff_ratio(ref, cur, [100, 100, 200, 200])

    assert ratio_changed   > 0.05
    assert ratio_unchanged == 0.0

def test_diff_ratio_below_threshold_is_closed():
    ref = np.zeros((100, 100), dtype=np.uint8)
    cur = np.zeros((100, 100), dtype=np.uint8)
    cur[0:2, 0:2] = 50  # tiny change, well below 5% threshold
    ratio = detector.diff_ratio(ref, cur, [0, 0, 100, 100])
    assert ratio < detector.THRESHOLD

def test_diff_ratio_above_threshold_is_open():
    ref = np.zeros((100, 100), dtype=np.uint8)
    cur = np.full((100, 100), 200, dtype=np.uint8)
    ratio = detector.diff_ratio(ref, cur, [0, 0, 100, 100])
    assert ratio > detector.THRESHOLD


# ── load_rois ─────────────────────────────────────────────────────────────────

def test_load_rois_returns_dict_from_file(tmp_path):
    rois = {"door": [10, 20, 110, 120], "window": [200, 50, 350, 150]}
    (tmp_path / "rois.json").write_text(json.dumps(rois))
    with patch.object(detector, "ROIS_FILE", str(tmp_path / "rois.json")):
        result = detector.load_rois()
    assert result == rois

def test_load_rois_returns_empty_when_missing(tmp_path):
    with patch.object(detector, "ROIS_FILE", str(tmp_path / "nonexistent.json")):
        result = detector.load_rois()
    assert result == {}


# ── fetch_frame ───────────────────────────────────────────────────────────────

def _make_bgr_frame(width: int = 100, height: int = 80) -> np.ndarray:
    """Create a BGR frame as cv2 would return it."""
    return np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)


def test_fetch_frame_returns_rgb_and_gray():
    bgr = _make_bgr_frame(100, 80)
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, bgr)

    detector._cap = None
    with patch("detector.cv2.VideoCapture", return_value=mock_cap):
        rgb, gray = detector.fetch_frame()

    assert rgb  is not None
    assert gray is not None
    assert rgb.shape  == (80, 100, 3)
    assert gray.shape == (80, 100)


def test_fetch_frame_returns_none_on_read_failure():
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (False, None)

    detector._cap = None
    with patch("detector.cv2.VideoCapture", return_value=mock_cap):
        rgb, gray = detector.fetch_frame()

    assert rgb  is None
    assert gray is None
    assert detector._cap is None  # cap was reset for reconnect


def test_fetch_frame_returns_none_on_exception():
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.side_effect = RuntimeError("stream error")

    detector._cap = None
    with patch("detector.cv2.VideoCapture", return_value=mock_cap):
        rgb, gray = detector.fetch_frame()

    assert rgb  is None
    assert gray is None


def test_fetch_frame_reuses_existing_cap():
    bgr = _make_bgr_frame()
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, bgr)

    detector._cap = mock_cap
    with patch("detector.cv2.VideoCapture") as mock_ctor:
        detector.fetch_frame()
    mock_ctor.assert_not_called()  # no new VideoCapture created
    detector._cap = None


# ── detect_person ─────────────────────────────────────────────────────────────

def test_detect_person_returns_true_when_person_found():
    with patch.object(detector, "model") as mock_model:
        mock_model.predict.return_value = [MagicMock(boxes=["person_box"])]
        result = detector.detect_person(np.zeros((100, 100, 3), dtype=np.uint8))
    assert result is True

def test_detect_person_returns_false_when_empty():
    with patch.object(detector, "model") as mock_model:
        mock_model.predict.return_value = [MagicMock(boxes=[])]
        result = detector.detect_person(np.zeros((100, 100, 3), dtype=np.uint8))
    assert result is False

def test_detect_person_passes_correct_args():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    with patch.object(detector, "model") as mock_model:
        mock_model.predict.return_value = [MagicMock(boxes=[])]
        detector.detect_person(frame)
    _, kwargs = mock_model.predict.call_args
    assert kwargs["classes"] == [0]        # class 0 = person only
    assert kwargs["verbose"]  is False
    assert kwargs["conf"]     == detector.PERSON_CONF
