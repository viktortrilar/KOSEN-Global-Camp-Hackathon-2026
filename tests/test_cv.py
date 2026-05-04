import io
import json
import pytest
import numpy as np
from PIL import Image
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

def _make_jpeg(width: int = 100, height: int = 80) -> bytes:
    img = Image.new("RGB", (width, height), color=(120, 60, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

def test_fetch_frame_returns_rgb_and_gray():
    mock_resp = MagicMock()
    mock_resp.content = _make_jpeg(100, 80)
    mock_resp.raise_for_status = MagicMock()

    with patch("detector.requests.get", return_value=mock_resp):
        rgb, gray = detector.fetch_frame()

    assert rgb  is not None
    assert gray is not None
    assert rgb.shape  == (80, 100, 3)
    assert gray.shape == (80, 100)

def test_fetch_frame_returns_none_on_network_error():
    with patch("detector.requests.get", side_effect=ConnectionError("refused")):
        rgb, gray = detector.fetch_frame()
    assert rgb  is None
    assert gray is None

def test_fetch_frame_returns_none_on_bad_status():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("404")
    with patch("detector.requests.get", return_value=mock_resp):
        rgb, gray = detector.fetch_frame()
    assert rgb  is None
    assert gray is None


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
