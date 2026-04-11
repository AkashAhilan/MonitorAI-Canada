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
from pathlib import Path
from typing import List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cv2

from camera.capture import FrameSource
from camera.config import load_config
from camera.rppg_infer import format_hr_display, infer_from_face_crops_bgr
from camera.serial_servo import RateLimitedPan, ServoSerial
from camera.tracking import FaceTracker, crop_face_bgr

log = logging.getLogger(__name__)

SEARCH, LOCK, MEASURE = "SEARCH", "LOCK", "MEASURE"


def draw_label(img, lines: List[Tuple[str, Tuple[int, int, int]]], x: int = 12, y0: int = 24) -> None:
    y = y0
    for text, color in lines:
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        y += 22


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
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

    win = "Waiting-room monitor (q quit, r reset, s serial, c cap, v rec)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    state = SEARCH
    consec_center = 0
    lock_started = 0.0
    ref_cx: Optional[float] = None
    last_cmd = "—"
    last_hr_line = "HR: —"
    low_sqi_streak = 0
    last_infer_at = 0.0
    measure_crops: deque = deque(maxlen=cfg.MEASURE_BUFFER_FRAMES)

    recording = False
    writer = None
    frame_i = 0
    t_prev = time.perf_counter()
    fps_ema: float | None = None

    os.makedirs(cfg.SMOKE_CAPTURE_DIR, exist_ok=True)

    def reset_search(reason: str) -> None:
        nonlocal state, consec_center, lock_started, ref_cx, measure_crops, low_sqi_streak, last_cmd
        log.info("LOST→SEARCH (%s)", reason)
        state = SEARCH
        consec_center = 0
        lock_started = 0.0
        ref_cx = None
        measure_crops.clear()
        low_sqi_streak = 0
        last_cmd = "—"
        pan.request_stop()

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

            h, w = frame.shape[:2]
            fc_x = w / 2.0
            box = tracker.pick_target(frame)

            if box is None:
                cv2.line(frame, (int(fc_x), 0), (int(fc_x), h), (80, 80, 80), 1)
                draw_label(
                    frame,
                    [
                        (f"STATE: {state}", (0, 255, 255)),
                        ("NO FACE", (0, 0, 255)),
                        (f"frame_cx: {fc_x:.0f}", (200, 200, 200)),
                        (f"fps~:{fps_ema:.1f}" if fps_ema else "fps~:—", (200, 200, 200)),
                        (last_hr_line, (0, 255, 0)),
                        (f"serial: {'ON' if cfg.SERIAL_ENABLED else 'OFF'} mock={cfg.MOCK_SERIAL}", (180, 180, 180)),
                    ],
                )
                if state == MEASURE:
                    reset_search("face lost in MEASURE")
                elif state == LOCK:
                    reset_search("face lost in LOCK")
                else:
                    pan.request_stop()
                last_cmd = "—"
            else:
                x1, y1, x2, y2 = box.x1, box.y1, box.x2, box.y2
                face_cx = box.cx
                err = face_cx - fc_x
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.line(frame, (int(fc_x), 0), (int(fc_x), h), (80, 80, 80), 1)
                cv2.circle(frame, (int(face_cx), int((y1 + y2) / 2)), 5, (0, 255, 255), -1)

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
                            len(measure_crops) >= cfg.MEASURE_BUFFER_FRAMES
                            and (time.monotonic() - last_infer_at) * 1000.0 >= cfg.RPPG_INFER_EVERY_MS
                        ):
                            last_infer_at = time.monotonic()
                            fps_use = float(fps_ema or cfg.MEASURE_FPS_ASSUMED)
                            result = infer_from_face_crops_bgr(list(measure_crops), fps_use)
                            last_hr_line, _, _, _br = format_hr_display(result)
                            if not result or result.get("SQI") is None:
                                low_sqi_streak += 1
                            elif result["SQI"] < cfg.SQI_MIN:
                                low_sqi_streak += 1
                            else:
                                low_sqi_streak = 0
                            if low_sqi_streak >= cfg.LOW_SQI_FRAMES_BEFORE_ABORT:
                                reset_search("low SQI or failed inference in MEASURE")
                            else:
                                log.info("rPPG %s", last_hr_line)

                lines = [
                    (f"STATE: {state}", (0, 255, 255)),
                    (f"face_cx: {face_cx:.0f}  frame_cx: {fc_x:.0f}  err: {err:+.0f}", (220, 220, 220)),
                    (f"cmd: {last_cmd}", (255, 200, 100)),
                    (last_hr_line, (0, 255, 128)),
                    (f"measuring: {'YES' if state == MEASURE else 'no'}  buf:{len(measure_crops)}", (180, 180, 255)),
                    (f"fps~:{fps_ema:.1f}" if fps_ema else "fps~:—", (150, 150, 150)),
                    (
                        f"serial: {'ON' if cfg.SERIAL_ENABLED else 'OFF'} mock={cfg.MOCK_SERIAL}",
                        (150, 150, 150),
                    ),
                ]
                draw_label(frame, lines)

            if recording and writer is not None:
                writer.write(frame)
            cv2.imshow(win, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("r"):
                state = SEARCH
                consec_center = 0
                lock_started = 0.0
                ref_cx = None
                measure_crops.clear()
                low_sqi_streak = 0
                last_hr_line = "HR: —"
                pan.request_stop()
                log.info("reset→SEARCH (manual)")
            if key == ord("s"):
                cfg.SERIAL_ENABLED = not cfg.SERIAL_ENABLED
                servo.enabled = cfg.SERIAL_ENABLED
                print(f"[serial] enabled={cfg.SERIAL_ENABLED}", flush=True)
            if key == ord("c"):
                path = os.path.join(cfg.SMOKE_CAPTURE_DIR, f"app_frame_{frame_i}.png")
                cv2.imwrite(path, frame)
                print(f"[capture] {path}", flush=True)
            if key == ord("v"):
                if not recording:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    ow, oh = frame.shape[1], frame.shape[0]
                    out_fps = max(8.0, min(60.0, fps_ema or src.stats.fps_hint or 30.0))
                    writer = cv2.VideoWriter(cfg.SMOKE_RECORD_PATH, fourcc, out_fps, (ow, oh))
                    recording = bool(writer.isOpened())
                    print(f"[record] {'started' if recording else 'FAILED'} {cfg.SMOKE_RECORD_PATH}", flush=True)
                else:
                    recording = False
                    if writer is not None:
                        writer.release()
                        writer = None
                    print("[record] stopped", flush=True)

    finally:
        if writer is not None:
            writer.release()
        tracker.close()
        servo.close()
        src.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
