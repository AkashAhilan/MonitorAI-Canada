"""
open-rppg inference isolated behind a small API.

The installed library expects uint8 RGB tensors:
  - process_faces_tensor(tensor, fps=30.0) with shape (T, H, W, 3)
  - process_video_tensor(tensor, fps=30.0) full frames RGB

We use face crops + process_faces_tensor so the model matches our MediaPipe box
(no second internal face detector). See rppg.main.Model.process_faces_tensor.

BGR frames from OpenCV are converted to RGB before stacking.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

_model = None


def get_model():
    """Lazy-init (first load downloads / compiles weights; can be slow)."""
    global _model
    if _model is None:
        import rppg

        _model = rppg.Model()
        log.info("open-rppg Model loaded: input meta=%s", getattr(_model, "meta", {}))
    return _model


def bgr_crops_to_rgb_tensor(crops_bgr: list) -> np.ndarray:
    """Stack BGR crops into (T, H, W, 3) uint8 RGB."""
    if not crops_bgr:
        raise ValueError("empty crops")
    rgb = [cv2.cvtColor(c, cv2.COLOR_BGR2RGB) for c in crops_bgr]
    return np.stack(rgb, axis=0).astype(np.uint8)


def infer_from_face_crops_bgr(crops_bgr: list, fps: float) -> Optional[Dict[str, Any]]:
    """
    Run one offline-style inference on a buffer of face crops (BGR).
    Returns the dict from Model.hr() after process_faces_tensor, or None on failure.
    """
    if len(crops_bgr) < 2:
        return None
    tensor = bgr_crops_to_rgb_tensor(crops_bgr)
    model = get_model()
    try:
        out = model.process_faces_tensor(tensor, fps=float(fps))
        return out
    except Exception:
        log.exception("process_faces_tensor failed")
        return None


def format_hr_display(result: Optional[Dict[str, Any]]) -> Tuple[str, Optional[float], Optional[float], Optional[float]]:
    """
    Human-readable line + parsed hr, SQI, breathing rate if present in hrv.
    """
    if not result:
        return "HR: —  SQI: —", None, None, None
    hr = result.get("hr")
    sqi = result.get("SQI")
    hrv = result.get("hrv") or {}
    br = hrv.get("breathingrate") if isinstance(hrv, dict) else None
    hr_s = f"{hr:.1f}" if hr is not None else "—"
    sqi_s = f"{sqi:.2f}" if sqi is not None else "—"
    br_s = f" RR:{br:.2f}" if br is not None else ""
    return f"HR:{hr_s} BPM  SQI:{sqi_s}{br_s}", hr, sqi, float(br) if br is not None else None
