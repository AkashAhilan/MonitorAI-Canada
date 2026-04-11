"""Unified video source: live USB camera or file (for repeatable debugging)."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import cv2

log = logging.getLogger(__name__)


@dataclass
class FrameSourceStats:
    width: int = 0
    height: int = 0
    camera_index: Optional[int] = None
    path: Optional[str] = None
    fps_hint: float = 30.0
    backend_name: str = ""


def _frame_looks_live(frame: Any) -> bool:
    """Reject empty, None, or all-black buffers (common when wrong index/backend 'opens' but never streams)."""
    if frame is None:
        return False
    try:
        if frame.size == 0:
            return False
    except Exception:
        return False
    mx = float(frame.max())
    if mx < 2.0:
        return False
    return True


def _warmup_and_validate(cap: cv2.VideoCapture, max_attempts: int = 24) -> bool:
    """Read a few frames — some drivers need warmup; validate we are not stuck on black."""
    for _ in range(max_attempts):
        ok, frame = cap.read()
        if ok and _frame_looks_live(frame):
            return True
        time.sleep(0.03)
    return False


def _backend_candidates(dshow_first: bool) -> List[Tuple[Optional[int], str]]:
    """
    Windows: MSMF (often selected by the "default" backend) can run for a few seconds then fail with
    OnReadSample / can't grab frame (-1072873822). Prefer DirectShow first when dshow_first is True
    for more stable USB webcams.
    """
    if sys.platform != "win32":
        return [(None, "default")]

    dshow = (cv2.CAP_DSHOW, "DSHOW") if hasattr(cv2, "CAP_DSHOW") else None
    msfm = (cv2.CAP_MSMF, "MSMF") if hasattr(cv2, "CAP_MSMF") else None
    default = (None, "default")

    if dshow_first and dshow is not None:
        order: List[Tuple[Optional[int], str]] = [dshow, default]
        if msfm is not None:
            order.append(msfm)
        return order

    order = [default]
    if dshow is not None:
        order.append(dshow)
    if msfm is not None:
        order.append(msfm)
    return order


def _open_capture(index: int, api: Optional[int]) -> cv2.VideoCapture:
    if api is None:
        return cv2.VideoCapture(index)
    return cv2.VideoCapture(index, api)


def open_live_camera(
    preferred_index: int = 1,
    probe: bool = True,
    dshow_first: bool = True,
) -> Tuple[cv2.VideoCapture, int, str, Optional[int]]:
    """
    Open a working camera. Tries preferred_index first, then 0..3 (unique), with multiple backends.
    Returns (cap, index_used, backend_name, api_used).
    """
    indices: List[int] = [preferred_index]
    if probe:
        for i in (0, 1, 2, 3):
            if i not in indices:
                indices.append(i)

    last_err: Optional[str] = None
    cands = _backend_candidates(dshow_first)
    for idx in indices:
        for api, api_name in cands:
            cap = _open_capture(idx, api)
            if not cap.isOpened():
                cap.release()
                last_err = f"index={idx} {api_name} did not open"
                log.debug(last_err)
                continue
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            if _warmup_and_validate(cap):
                log.info(
                    "Using camera index=%s backend=%s (preferred was %s)",
                    idx,
                    api_name,
                    preferred_index,
                )
                return cap, idx, api_name, api
            cap.release()
            last_err = f"index={idx} {api_name} opened but no valid frames"

    raise RuntimeError(
        "Could not open a working camera. Tried indices %s with backends %s. Last: %s. "
        "Set CAMERA_INDEX, try CAMERA_WIN32_DSHOW_FIRST=false, or set CAMERA_PROBE=false."
        % (indices, [n for _, n in cands], last_err)
    )


class FrameSource:
    """read() -> (ok, bgr_frame). release() when done."""

    def __init__(
        self,
        mode: str,
        camera_index: int = 1,
        video_path: str = "",
        loop_video: bool = True,
        camera_probe: bool = True,
        camera_win32_dshow_first: bool = True,
        camera_read_retries: int = 20,
    ) -> None:
        self.mode = mode
        self.stats = FrameSourceStats()
        self._cap: Optional[cv2.VideoCapture] = None
        self._last_t = time.perf_counter()
        self._ema_dt: Optional[float] = None
        self._loop_video = loop_video
        self._camera_probe = camera_probe
        self._preferred_index = camera_index
        self._win_dshow_first = camera_win32_dshow_first
        self._read_retries = max(1, int(camera_read_retries))
        self._live_api: Optional[int] = None
        self._reopen_failures = 0

        if mode == "video":
            self._cap = cv2.VideoCapture(video_path)
            if not self._cap.isOpened():
                raise FileNotFoundError(f"Could not open video: {video_path}")
            self.stats.path = video_path
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0)
            self.stats.width, self.stats.height = w, h
            self.stats.fps_hint = fps if fps > 1.0 else 30.0
            log.info("Video file: %s size=%sx%s fps_hint=%.2f", video_path, w, h, self.stats.fps_hint)
        else:
            self._cap, used_index, backend_name, api = open_live_camera(
                camera_index,
                probe=camera_probe,
                dshow_first=camera_win32_dshow_first,
            )
            self._live_api = api
            self.stats.camera_index = used_index
            self.stats.backend_name = backend_name
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.stats.width, self.stats.height = w, h
            log.info("Camera index=%s backend=%s size=%sx%s", used_index, backend_name, w, h)

    @property
    def width(self) -> int:
        return self.stats.width

    @property
    def height(self) -> int:
        return self.stats.height

    def _reopen_live(self) -> bool:
        """Recover from MSMF/DirectShow dropping the stream while the device still appears open."""
        idx = self.stats.camera_index
        if idx is None:
            idx = self._preferred_index
        log.warning("Reopening camera (index=%s, dshow_first=%s)", idx, self._win_dshow_first)
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        try:
            self._cap, used_idx, name, api = open_live_camera(
                idx,
                probe=False,
                dshow_first=self._win_dshow_first,
            )
            self._live_api = api
            self.stats.camera_index = used_idx
            self.stats.backend_name = name
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.stats.width, self.stats.height = w, h
            self._reopen_failures = 0
            log.info("Camera reopened: index=%s backend=%s size=%sx%s", used_idx, name, w, h)
            return True
        except Exception:
            self._reopen_failures += 1
            log.exception("Camera reopen failed (attempt %s)", self._reopen_failures)
            return False

    def read(self) -> Tuple[bool, Any]:
        assert self._cap is not None
        if self.mode == "video":
            ok, frame = self._cap.read()
            if self._loop_video and not ok:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
        else:
            ok, frame = False, None
            for _ in range(self._read_retries):
                ok, frame = self._cap.read()
                if ok and frame is not None:
                    break
                time.sleep(0.02)
            if not ok or frame is None:
                if self._reopen_live() and self._cap is not None:
                    ok, frame = self._cap.read()
                else:
                    ok, frame = False, None

        now = time.perf_counter()
        dt = now - self._last_t
        self._last_t = now
        if dt > 1e-6:
            if self._ema_dt is None:
                self._ema_dt = dt
            else:
                self._ema_dt = 0.9 * self._ema_dt + 0.1 * dt
        return ok, frame

    def estimated_fps(self) -> float:
        if self._ema_dt and self._ema_dt > 1e-6:
            return 1.0 / self._ema_dt
        return self.stats.fps_hint

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
