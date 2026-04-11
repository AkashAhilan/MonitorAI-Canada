"""MediaPipe face detection: largest face, tie-break closest to frame center. No identity."""

from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

try:
    import mediapipe as mp
except ImportError as e:
    raise ImportError("mediapipe is required for face tracking") from e


def _legacy_solutions_available() -> bool:
    return hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection")


# Official task models (not shipped inside the slim PyPI wheel; downloaded once to .cache/)
_MODEL_URLS = {
    0: (
        "blaze_face_short_range.tflite",
        "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
    ),
    1: (
        "blaze_face_full_range.tflite",
        "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite",
    ),
}


def _ensure_face_model_tflite(model_selection: int, cache_dir: Path) -> str:
    """Download BlazeFace TFLite if missing (MediaPipe Tasks requires a model file on disk)."""
    fname, url = _MODEL_URLS.get(model_selection, _MODEL_URLS[0])
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / fname
    if path.is_file() and path.stat().st_size > 8000:
        return str(path)
    log.info("Downloading MediaPipe face detector model (%s) ...", fname)
    tmp = path.with_suffix(".tmp")
    req = urllib.request.Request(url, headers={"User-Agent": "MonitorAI-camera/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not download face model from {url}. "
            "Save the .tflite next to the app or see camera/README.md."
        ) from None
    log.info("Face model saved to %s", path)
    return str(path)


@dataclass
class FaceBox:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def area(self) -> float:
        return float(max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1))


def _pick_largest(boxes: list[FaceBox], w: int, h: int) -> Optional[FaceBox]:
    fc_x, fc_y = w / 2.0, h / 2.0
    best_key: Optional[Tuple[float, float]] = None
    best_box: Optional[FaceBox] = None
    for box in boxes:
        dist = (box.cx - fc_x) ** 2 + (box.cy - fc_y) ** 2
        key = (-box.area, dist)
        if best_key is None or key < best_key:
            best_key = key
            best_box = box
    return best_box


class FaceTracker:
    """
    Face detection using MediaPipe.

    - **Legacy** (`mediapipe.solutions.face_detection`): older wheels.
    - **Tasks** (`mediapipe.tasks.python.vision.FaceDetector`): current PyPI builds that omit `solutions`.
    """

    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        model_selection: int = 0,
        model_cache_dir: Optional[Path] = None,
    ) -> None:
        self._legacy = _legacy_solutions_available()
        self._video_ts_ms = 0
        self._detector: Any = None

        if self._legacy:
            self._detector = mp.solutions.face_detection.FaceDetection(
                model_selection=model_selection,
                min_detection_confidence=min_detection_confidence,
            )
            log.info("FaceTracker: using legacy mediapipe.solutions.face_detection")
            return

        cache = model_cache_dir or (Path(__file__).resolve().parent / ".cache")
        model_path = _ensure_face_model_tflite(model_selection, cache)

        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core import base_options as base_options_module
        from mediapipe.tasks.python.vision.core import image as mp_image_module
        from mediapipe.tasks.python.vision.core import vision_task_running_mode as running_mode_module

        base_options = base_options_module.BaseOptions(model_asset_path=model_path)
        options = vision.FaceDetectorOptions(
            base_options=base_options,
            running_mode=running_mode_module.VisionTaskRunningMode.VIDEO,
            min_detection_confidence=min_detection_confidence,
            min_suppression_threshold=0.3,
        )
        self._detector = vision.FaceDetector.create_from_options(options)
        self._mp_image_module = mp_image_module
        log.info("FaceTracker: using MediaPipe Tasks FaceDetector (VIDEO mode)")

    def close(self) -> None:
        if self._detector is None:
            return
        if self._legacy:
            self._detector.close()
        else:
            self._detector.close()

    def pick_target(self, frame_bgr: np.ndarray) -> Optional[FaceBox]:
        """Return largest face; tie-break by distance to frame center."""
        if self._legacy:
            return self._pick_target_legacy(frame_bgr)
        return self._pick_target_tasks(frame_bgr)

    def _pick_target_legacy(self, frame_bgr: np.ndarray) -> Optional[FaceBox]:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        res = self._detector.process(rgb)
        if not res.detections:
            return None
        boxes: list[FaceBox] = []
        for det in res.detections:
            r = det.location_data.relative_bounding_box
            x1 = int(r.xmin * w)
            y1 = int(r.ymin * h)
            x2 = int((r.xmin + r.width) * w)
            y2 = int((r.ymin + r.height) * h)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append(FaceBox(x1, y1, x2, y2))
        return _pick_largest(boxes, w, h) if boxes else None

    def _pick_target_tasks(self, frame_bgr: np.ndarray) -> Optional[FaceBox]:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if not rgb.flags["C_CONTIGUOUS"]:
            rgb = np.ascontiguousarray(rgb)
        mp_img = self._mp_image_module.Image(self._mp_image_module.ImageFormat.SRGB, rgb)
        self._video_ts_ms += 33
        result = self._detector.detect_for_video(mp_img, self._video_ts_ms)
        if not result.detections:
            return None
        boxes: list[FaceBox] = []
        for det in result.detections:
            bb = det.bounding_box
            x1 = int(bb.origin_x)
            y1 = int(bb.origin_y)
            x2 = int(bb.origin_x + bb.width)
            y2 = int(bb.origin_y + bb.height)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append(FaceBox(x1, y1, x2, y2))
        return _pick_largest(boxes, w, h) if boxes else None


def crop_face_bgr(frame_bgr: np.ndarray, box: FaceBox, out_size: int) -> np.ndarray:
    """Square crop around face box, resized to out_size (BGR)."""
    h, w = frame_bgr.shape[:2]
    bw = box.x2 - box.x1
    bh = box.y2 - box.y1
    side = int(max(bw, bh) * 1.25)
    cx, cy = int(box.cx), int(box.cy)
    half = side // 2
    x1 = max(0, cx - half)
    y1 = max(0, cy - half)
    x2 = min(w, x1 + side)
    y2 = min(h, y1 + side)
    x1 = max(0, x2 - side)
    y1 = max(0, y2 - side)
    roi = frame_bgr[y1:y2, x1:x2]
    if roi.size == 0:
        return np.zeros((out_size, out_size, 3), dtype=np.uint8)
    return cv2.resize(roi, (out_size, out_size), interpolation=cv2.INTER_AREA)
