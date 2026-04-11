"""
Live camera / file smoke test: proves OpenCV capture before the full pipeline.

Run from repo root:
  python -m camera.smoke_camera

Or:
  cd camera && python smoke_camera.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# Allow `python camera/smoke_camera.py` from repo root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cv2

from camera.capture import FrameSource
from camera.config import load_config

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    mode = cfg.INPUT_MODE
    if mode == "video":
        src = FrameSource("video", video_path=cfg.VIDEO_PATH, loop_video=cfg.VIDEO_LOOP)
    else:
        src = FrameSource(
            "live",
            camera_index=cfg.CAMERA_INDEX,
            loop_video=False,
            camera_probe=cfg.CAMERA_PROBE,
            camera_win32_dshow_first=cfg.CAMERA_WIN32_DSHOW_FIRST,
            camera_read_retries=cfg.CAMERA_READ_RETRIES,
        )

    # ASCII only: non-ASCII punctuation breaks the window title on some Windows/OpenCV builds
    win = "Smoke - camera (q quit, c capture, v record)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    recording = False
    writer = None
    frame_idx = 0
    t0 = time.perf_counter()
    fps_ema = None

    os.makedirs(cfg.SMOKE_CAPTURE_DIR, exist_ok=True)

    if mode == "live":
        print(
            f"LIVE resolved_camera_index={src.stats.camera_index} backend={src.stats.backend_name or '—'} "
            f"preferred={cfg.CAMERA_INDEX} probe={cfg.CAMERA_PROBE} size={src.width}x{src.height}",
            flush=True,
        )
    else:
        print(
            f"VIDEO file={cfg.VIDEO_PATH!r} size={src.width}x{src.height}",
            flush=True,
        )

    try:
        while True:
            ok, frame = src.read()
            if not ok or frame is None:
                log.warning("Frame grab failed")
                break
            frame_idx += 1
            now = time.perf_counter()
            dt = now - t0
            t0 = now
            if dt > 1e-6:
                inst_fps = 1.0 / dt
                fps_ema = inst_fps if fps_ema is None else 0.9 * fps_ema + 0.1 * inst_fps

            h, w = frame.shape[:2]
            lines = [
                "LIVE MODE",
                f"input: {mode}",
                f"size: {w}x{h}",
                f"fps~: {fps_ema:.1f}" if fps_ema else "fps~: —",
                f"frame: {frame_idx}",
                "REC ON" if recording else "REC off",
            ]
            if mode == "live" and src.stats.camera_index is not None:
                lines.insert(
                    2,
                    f"cam idx {src.stats.camera_index} ({src.stats.backend_name or '?'})",
                )
            y = 28
            for line in lines:
                cv2.putText(
                    frame,
                    line,
                    (12, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 255, 0) if not recording else (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                y += 26

            if recording and writer is not None:
                writer.write(frame)

            cv2.imshow(win, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("c"):
                path = os.path.join(cfg.SMOKE_CAPTURE_DIR, f"frame_{frame_idx}.png")
                cv2.imwrite(path, frame)
                print(f"[capture] saved {path}", flush=True)
            if key == ord("v"):
                if not recording:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    out_fps = max(8.0, min(60.0, fps_ema or src.stats.fps_hint or 30.0))
                    writer = cv2.VideoWriter(cfg.SMOKE_RECORD_PATH, fourcc, out_fps, (w, h))
                    if not writer.isOpened():
                        print("[record] failed to open VideoWriter", flush=True)
                        writer = None
                    else:
                        recording = True
                        print(
                            f"[record] started -> {cfg.SMOKE_RECORD_PATH} @ {out_fps:.1f} fps",
                            flush=True,
                        )
                else:
                    recording = False
                    if writer is not None:
                        writer.release()
                        writer = None
                    print("[record] stopped", flush=True)
    finally:
        if writer is not None:
            writer.release()
        src.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
