"""
Main app: SEARCH → LOCK → MEASURE state machine, face tracking, rPPG, servo pan.

Run from repo root:
  python -m camera.app
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cv2

from camera.capture import FrameSource
from camera.config import load_config
from camera.rppg_infer import format_hr_display, infer_from_face_crops_bgr
from camera.serial_servo import RateLimitedPan, ServoSerial
from camera.tracking import FaceTracker, crop_face_bgr
from camera.ui_dashboard import DASHBOARD_H, DASHBOARD_W, DashboardContext, render_dashboard

log = logging.getLogger(__name__)

SEARCH, LOCK, MEASURE = "SEARCH", "LOCK", "MEASURE"


def _rppg_bg_task(crops_bgr: list, fps: float, gen: int) -> tuple[int, Optional[Dict[str, Any]]]:
    """Runs in worker thread; returns (generation, raw model dict) for stale-result discard."""
    return gen, infer_from_face_crops_bgr(crops_bgr, fps)


def main() -> None:
    # Quieter TFLite / MediaPipe on Windows (still loads; less console spam).
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for _name in ("tensorflow", "absl", "rppg"):
        logging.getLogger(_name).setLevel(logging.ERROR)

    cfg = load_config()

    if cfg.INPUT_MODE == "video":
        src = FrameSource(
            "video",
            camera_index=cfg.CAMERA_INDEX,
            video_path=cfg.VIDEO_PATH,
            loop_video=cfg.VIDEO_LOOP,
        )
    else:
        src = FrameSource(
            "live",
            camera_index=cfg.CAMERA_INDEX,
            loop_video=False,
            camera_probe=cfg.CAMERA_PROBE,
            camera_win32_dshow_first=cfg.CAMERA_WIN32_DSHOW_FIRST,
            camera_read_retries=cfg.CAMERA_READ_RETRIES,
        )

    tracker = FaceTracker(min_detection_confidence=cfg.MP_MIN_DETECTION_CONFIDENCE, model_selection=0)
    servo = ServoSerial(cfg.SERIAL_PORT, cfg.SERIAL_BAUD, mock=cfg.MOCK_SERIAL, enabled=cfg.SERIAL_ENABLED)
    pan = RateLimitedPan(servo, cfg.SERVO_COOLDOWN_MS / 1000.0)

    if cfg.MOCK_SERIAL or getattr(servo, "mock", True):
        print(
            "\n>>> SERVO: MOCK — [SERVO] lines only go to this window; Arduino USB serial gets NO data.\n"
            "    To move the real servo: set MOCK_SERIAL=false, SERIAL_PORT=COMx (Device Manager), "
            "close Arduino Serial Monitor, then run again.\n",
            flush=True,
        )
    elif cfg.SERIAL_ENABLED:
        print(
            f"\n>>> SERVO: serial -> {cfg.SERIAL_PORT} @ {cfg.SERIAL_BAUD} (commands sent to Arduino)\n",
            flush=True,
        )

    win = "Monitor AI — Hospital Waiting Room"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    # Match framebuffer size so OpenCV does not upscale the composite (upscale = soft UI text).
    cv2.resizeWindow(win, DASHBOARD_W, DASHBOARD_H)

    state = SEARCH
    consec_center = 0
    lock_started = 0.0
    ref_cx: Optional[float] = None
    last_cmd = "—"
    last_hr_line = "HR: —"
    last_bpm: Optional[float] = None
    last_sqi: Optional[float] = None
    last_rr: Optional[float] = None
    low_sqi_streak = 0
    last_infer_at = 0.0
    infer_gen = 0
    infer_future: Optional[Future] = None
    measure_crops: deque = deque(maxlen=cfg.MEASURE_BUFFER_FRAMES)

    recording = False
    writer = None
    frame_i = 0
    t_prev = time.perf_counter()
    fps_ema: float | None = None

    os.makedirs(cfg.SMOKE_CAPTURE_DIR, exist_ok=True)

    def reset_search(reason: str) -> None:
        nonlocal state, consec_center, lock_started, ref_cx, measure_crops, low_sqi_streak, last_cmd
        nonlocal last_hr_line, last_bpm, last_sqi, last_rr, infer_gen
        log.info("LOST→SEARCH (%s)", reason)
        infer_gen += 1
        state = SEARCH
        consec_center = 0
        lock_started = 0.0
        ref_cx = None
        measure_crops.clear()
        low_sqi_streak = 0
        last_cmd = "—"
        last_hr_line = "HR: —"
        last_bpm = last_sqi = last_rr = None
        pan.request_stop()

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rppg")
    try:
        while True:
            ok, frame = src.read()
            if not ok or frame is None:
                log.warning("No frame")
                break
            frame_i += 1
            now = time.perf_counter()
            dt = now - t_prev
            t_prev = now
            if dt > 1e-6:
                inst = 1.0 / dt
                fps_ema = inst if fps_ema is None else 0.92 * fps_ema + 0.08 * inst

            # Apply completed rPPG (non-blocking); avoids stalling camera/UI on heavy TFLite work.
            if infer_future is not None and infer_future.done():
                g = -1
                result: Optional[Dict[str, Any]] = None
                try:
                    g, result = infer_future.result()
                except Exception:
                    log.exception("rPPG inference")
                infer_future = None
                if g == infer_gen and state == MEASURE:
                    last_hr_line, last_bpm, last_sqi, last_rr = format_hr_display(result)
                    if not result or result.get("SQI") is None:
                        low_sqi_streak += 1
                    elif result["SQI"] < cfg.SQI_MIN:
                        low_sqi_streak += 1
                    else:
                        low_sqi_streak = 0
                    if low_sqi_streak >= cfg.LOW_SQI_FRAMES_BEFORE_ABORT:
                        reset_search("low SQI or failed inference in MEASURE")
                    else:
                        log.debug("rPPG %s", last_hr_line)

            _, w = frame.shape[:2]
            fc_x = w / 2.0
            box = tracker.pick_target(frame)

            if box is None:
                last_bpm = last_sqi = last_rr = None
                last_hr_line = "HR: —"
                if state == MEASURE:
                    reset_search("face lost in MEASURE")
                elif state == LOCK:
                    reset_search("face lost in LOCK")
                else:
                    pan.request_stop()
                last_cmd = "—"
            else:
                face_cx = box.cx
                err = face_cx - fc_x

                if state == SEARCH:
                    if cfg.SERIAL_ENABLED:
                        if abs(err) > cfg.DEADBAND_PX:
                            if err < 0:
                                pan.request_pan_left()
                                last_cmd = "PAN_LEFT"
                            else:
                                pan.request_pan_right()
                                last_cmd = "PAN_RIGHT"
                        else:
                            pan.request_stop()
                            last_cmd = "STOP"
                    else:
                        last_cmd = "serial OFF"

                    if abs(err) <= cfg.CENTER_THRESHOLD_PX:
                        consec_center += 1
                    else:
                        consec_center = 0

                    if consec_center >= cfg.LOCK_CONSECUTIVE_FRAMES:
                        pan.request_stop()
                        last_cmd = "STOP"
                        state = LOCK
                        lock_started = time.monotonic()
                        consec_center = 0
                        log.info("SEARCH→LOCK (centered %s frames)", cfg.LOCK_CONSECUTIVE_FRAMES)

                elif state == LOCK:
                    pan.request_stop()
                    last_cmd = "STOP"
                    if abs(err) > cfg.CENTER_THRESHOLD_PX * 2:
                        reset_search("drift in LOCK")
                    elif time.monotonic() - lock_started >= cfg.SETTLE_MS / 1000.0:
                        infer_gen += 1
                        state = MEASURE
                        ref_cx = face_cx
                        measure_crops.clear()
                        last_infer_at = time.monotonic()
                        log.info("LOCK→MEASURE ref_cx=%.1f", ref_cx)

                elif state == MEASURE:
                    last_cmd = "hold (measure)"
                    if ref_cx is not None and abs(face_cx - ref_cx) > cfg.MEASURE_MAX_FACE_SHIFT_PX:
                        reset_search("face moved too much in MEASURE")
                    else:
                        crop = crop_face_bgr(frame, box, cfg.FACE_CROP_SIZE)
                        measure_crops.append(crop.copy())
                        if (
                            infer_future is None
                            and len(measure_crops) >= cfg.MEASURE_BUFFER_FRAMES
                            and (time.monotonic() - last_infer_at) * 1000.0 >= cfg.RPPG_INFER_EVERY_MS
                        ):
                            last_infer_at = time.monotonic()
                            fps_use = float(fps_ema or cfg.MEASURE_FPS_ASSUMED)
                            infer_future = executor.submit(
                                _rppg_bg_task, list(measure_crops), fps_use, infer_gen
                            )

            ctx = DashboardContext(
                state=state,
                has_face=box is not None,
                face_cx=box.cx if box is not None else None,
                frame_cx=fc_x,
                err_px=(box.cx - fc_x) if box is not None else 0.0,
                last_cmd=last_cmd,
                fps_ema=fps_ema,
                last_bpm=last_bpm,
                last_sqi=last_sqi,
                last_rr=last_rr,
                measure_buf_len=len(measure_crops),
                measure_buf_max=cfg.MEASURE_BUFFER_FRAMES,
                serial_enabled=cfg.SERIAL_ENABLED,
                mock_serial=cfg.MOCK_SERIAL,
                input_mode=cfg.INPUT_MODE,
                recording=recording,
            )
            composite = render_dashboard(frame, ctx, box)

            if recording and writer is not None:
                writer.write(composite)
            cv2.imshow(win, composite)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("r"):
                infer_gen += 1
                state = SEARCH
                consec_center = 0
                lock_started = 0.0
                ref_cx = None
                measure_crops.clear()
                low_sqi_streak = 0
                last_hr_line = "HR: —"
                last_bpm = last_sqi = last_rr = None
                pan.request_stop()
                log.info("reset→SEARCH (manual)")
            if key == ord("s"):
                cfg.SERIAL_ENABLED = not cfg.SERIAL_ENABLED
                servo.enabled = cfg.SERIAL_ENABLED
                print(f"[serial] enabled={cfg.SERIAL_ENABLED}", flush=True)
            if key == ord("c"):
                path = os.path.join(cfg.SMOKE_CAPTURE_DIR, f"app_frame_{frame_i}.png")
                cv2.imwrite(path, composite)
                print(f"[capture] {path}", flush=True)
            if key == ord("v"):
                if not recording:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    out_fps = max(8.0, min(60.0, fps_ema or src.stats.fps_hint or 30.0))
                    writer = cv2.VideoWriter(
                        cfg.SMOKE_RECORD_PATH, fourcc, out_fps, (DASHBOARD_W, DASHBOARD_H)
                    )
                    recording = bool(writer.isOpened())
                    print(f"[record] {'started' if recording else 'FAILED'} {cfg.SMOKE_RECORD_PATH}", flush=True)
                else:
                    recording = False
                    if writer is not None:
                        writer.release()
                        writer = None
                    print("[record] stopped", flush=True)

    finally:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)
        if writer is not None:
            writer.release()
        tracker.close()
        servo.close()
        src.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
