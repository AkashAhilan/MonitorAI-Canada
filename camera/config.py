"""
Central configuration for the camera prototype.
Edit values here (or override via environment variables where noted in README).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
def _env_str(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v if v is not None and v != "" else default


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    return int(v)


def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    return float(v)


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    # --- Input ---
    INPUT_MODE: str = field(default_factory=lambda: _env_str("INPUT_MODE", "live"))
    VIDEO_PATH: str = field(default_factory=lambda: _env_str("VIDEO_PATH", "test_clip.mp4"))
    # Many Windows PCs use 0 for a phantom/disabled device; first real USB cam is often 1 (see testing.py).
    CAMERA_INDEX: int = field(default_factory=lambda: _env_int("CAMERA_INDEX", 1))
    # Try other indices/backends if the preferred index gives a black or empty stream
    CAMERA_PROBE: bool = field(default_factory=lambda: _env_bool("CAMERA_PROBE", True))
    # On Windows, MSMF (often used by "default" backend) can stop delivering frames after a few seconds
    # (OnReadSample / can't grab frame). Prefer DirectShow first for long, stable capture.
    CAMERA_WIN32_DSHOW_FIRST: bool = field(default_factory=lambda: _env_bool("CAMERA_WIN32_DSHOW_FIRST", True))
    # Live capture: retries per frame before reopening the device
    CAMERA_READ_RETRIES: int = field(default_factory=lambda: _env_int("CAMERA_READ_RETRIES", 20))
    VIDEO_LOOP: bool = field(default_factory=lambda: _env_bool("VIDEO_LOOP", True))

    # --- Serial / servo ---
    SERIAL_PORT: str = field(default_factory=lambda: _env_str("SERIAL_PORT", "COM3"))
    SERIAL_BAUD: int = field(default_factory=lambda: _env_int("SERIAL_BAUD", 115200))
    MOCK_SERIAL: bool = field(default_factory=lambda: _env_bool("MOCK_SERIAL", True))
    SERIAL_ENABLED: bool = field(default_factory=lambda: _env_bool("SERIAL_ENABLED", True))

    # --- Tracking / centering (pixels) ---
    DEADBAND_PX: int = field(default_factory=lambda: _env_int("DEADBAND_PX", 40))
    CENTER_THRESHOLD_PX: int = field(default_factory=lambda: _env_int("CENTER_THRESHOLD_PX", 25))
    LOCK_CONSECUTIVE_FRAMES: int = field(default_factory=lambda: _env_int("LOCK_CONSECUTIVE_FRAMES", 15))
    SETTLE_MS: int = field(default_factory=lambda: _env_int("SETTLE_MS", 500))
    SERVO_COOLDOWN_MS: int = field(default_factory=lambda: _env_int("SERVO_COOLDOWN_MS", 120))

    # --- Measurement ---
    MEASURE_BUFFER_FRAMES: int = field(default_factory=lambda: _env_int("MEASURE_BUFFER_FRAMES", 300))
    MEASURE_FPS_ASSUMED: float = field(default_factory=lambda: _env_float("MEASURE_FPS_ASSUMED", 30.0))
    RPPG_INFER_EVERY_MS: int = field(default_factory=lambda: _env_int("RPPG_INFER_EVERY_MS", 1000))
    FACE_CROP_SIZE: int = field(default_factory=lambda: _env_int("FACE_CROP_SIZE", 128))
    SQI_MIN: float = field(default_factory=lambda: _env_float("SQI_MIN", 0.25))
    # Counts consecutive bad rPPG *inference passes* (not camera frames)
    LOW_SQI_FRAMES_BEFORE_ABORT: int = field(default_factory=lambda: _env_int("LOW_SQI_FRAMES_BEFORE_ABORT", 8))
    MEASURE_MAX_FACE_SHIFT_PX: int = field(default_factory=lambda: _env_int("MEASURE_MAX_FACE_SHIFT_PX", 80))

    # --- MediaPipe ---
    MP_MIN_DETECTION_CONFIDENCE: float = field(
        default_factory=lambda: _env_float("MP_MIN_DETECTION_CONFIDENCE", 0.5)
    )

    # --- Smoke test / recording ---
    SMOKE_CAPTURE_DIR: str = field(default_factory=lambda: _env_str("SMOKE_CAPTURE_DIR", "camera_captures"))
    SMOKE_RECORD_PATH: str = field(default_factory=lambda: _env_str("SMOKE_RECORD_PATH", "camera_record.mp4"))

    def __post_init__(self) -> None:
        m = str(self.INPUT_MODE).strip().lower()
        if m not in ("live", "video"):
            m = "live"
        self.INPUT_MODE = m  # type: ignore[assignment]


def load_config() -> Config:
    return Config()
