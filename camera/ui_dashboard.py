"""
OpenCV dashboard layout for Monitor AI — dark enterprise-style UI composited on numpy/cv2.

Text uses cv2.putText (Hershey): stroke-based, not OS subpixel text. Use only ASCII in
on-screen strings (Hershey cannot draw Unicode like em dashes — they show as "???").

If the OpenCV window is larger than the framebuffer (e.g. maximized), the whole image
is upscaled and UI/chrome looks blurrier than the video; keep window at native size for
crisp pixels, or use PIL/FreeType for high-quality overlays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

import cv2
import numpy as np

if TYPE_CHECKING:
    from camera.tracking import FaceBox

# --- Layout (pixels) — adjust for your display ---------------------------------
DASHBOARD_W, DASHBOARD_H = 1360, 768
PAD = 16
HEADER_H = 52
STATE_ROW_H = 40
FOOTER_H = 46
SIDEBAR_W = 400

# --- Theme (BGR) — Reference A: dark charcoal, restrained accents ------------
BG = (18, 18, 18)  # ~#121212
PANEL = (28, 28, 30)
PANEL_BORDER = (55, 55, 58)
HEADER_BG = (22, 22, 24)
TEXT_PRIMARY = (245, 245, 245)
TEXT_SECONDARY = (175, 175, 178)
TEXT_MUTED = (120, 120, 125)
ACCENT_GREEN = (100, 200, 130)
ACCENT_AMBER = (80, 190, 255)
ACCENT_RED = (80, 80, 240)
LINE_GUIDE = (70, 70, 75)
FACE_BOX = (100, 220, 140)


@dataclass
class DashboardContext:
    state: str  # SEARCH | LOCK | MEASURE
    has_face: bool
    face_cx: Optional[float]
    frame_cx: float
    err_px: float
    last_cmd: str
    fps_ema: Optional[float]
    last_bpm: Optional[float]
    last_sqi: Optional[float]
    last_rr: Optional[float]
    measure_buf_len: int
    measure_buf_max: int
    serial_enabled: bool
    mock_serial: bool
    input_mode: str
    recording: bool


def _sqi_quality_label(sqi: Optional[float]) -> str:
    if sqi is None:
        return "-"  # ASCII: Hershey cannot render U+2014 em dash
    if sqi >= 0.6:
        return "Excellent"
    if sqi >= 0.4:
        return "Good"
    if sqi >= 0.25:
        return "Fair"
    return "Poor"


def _monitoring_status(ctx: DashboardContext) -> str:
    if ctx.state != "MEASURE":
        return "Inactive"
    if ctx.measure_buf_len < ctx.measure_buf_max:
        return "Acquiring"
    if ctx.last_sqi is None:
        return "Processing"
    if ctx.last_sqi >= 0.5:
        return "Stable"
    if ctx.last_sqi >= 0.25:
        return "Marginal"
    return "Unstable"


def _active_state_key(ctx: DashboardContext) -> str:
    """Which of the four pills is active: searching | locked | measuring | lost"""
    if not ctx.has_face:
        return "lost"
    if ctx.state == "SEARCH":
        return "searching"
    if ctx.state == "LOCK":
        return "locked"
    return "measuring"


def _text_size(text: str, scale: float, thick: int) -> Tuple[int, int]:
    (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    return tw, th + baseline


def _draw_text(
    img: np.ndarray,
    text: str,
    x: int,
    y: int,
    scale: float,
    color: Tuple[int, int, int],
    thick: int = 1,
) -> None:
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _filled_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int]) -> None:
    cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)


def _border_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int], t: int = 1) -> None:
    cv2.rectangle(img, (x1, y1), (x2, y2), color, t)


def _draw_header(img: np.ndarray, w: int) -> None:
    _filled_rect(img, 0, 0, w, HEADER_H, HEADER_BG)
    title = "HOSPITAL WAITING ROOM MONITOR AI"
    tw, th = _text_size(title, 0.62, 1)
    y = HEADER_H // 2 + th // 2 - 4
    x = PAD
    _draw_text(img, title, x, y, 0.62, TEXT_PRIMARY, 1)
    sub = "Live monitoring"
    _draw_text(img, sub, w - PAD - _text_size(sub, 0.38, 1)[0], y - 2, 0.38, TEXT_MUTED, 1)


def _draw_state_row(img: np.ndarray, y0: int, w: int, active: str) -> None:
    """Four pills: Searching, Locked, Measuring, Lost"""
    labels = [
        ("searching", "Searching"),
        ("locked", "Locked"),
        ("measuring", "Measuring"),
        ("lost", "Lost"),
    ]
    pill_y = y0 + 6
    pill_h = STATE_ROW_H - 12
    x = PAD
    gap = 10
    for key, label in labels:
        tw, th = _text_size(label, 0.42, 1)
        pill_w = tw + 28
        is_on = key == active
        bg = (45, 48, 52) if is_on else (32, 34, 38)
        border = ACCENT_GREEN if (is_on and key == "measuring") else (ACCENT_AMBER if (is_on and key in ("searching", "lost")) else (100, 100, 110))
        if is_on and key == "locked":
            border = TEXT_SECONDARY
        if is_on and key == "lost":
            border = ACCENT_AMBER
        _filled_rect(img, x, pill_y, x + pill_w, pill_y + pill_h, bg)
        _border_rect(img, x, pill_y, x + pill_w, pill_y + pill_h, border if is_on else PANEL_BORDER, 1)
        col = TEXT_PRIMARY if is_on else TEXT_MUTED
        _draw_text(img, label, x + 14, pill_y + pill_h - 10, 0.42, col, 1)
        x += pill_w + gap


def _draw_video_overlays(
    vid: np.ndarray,
    vw: int,
    vh: int,
    src_w: int,
    src_h: int,
    box: Optional["FaceBox"],
    fc_x: float,
) -> None:
    sx = vw / float(src_w)
    sy = vh / float(src_h)
    cx = int(fc_x * sx)
    cv2.line(vid, (cx, 0), (cx, vh), LINE_GUIDE, 1)
    if box is not None:
        x1 = int(box.x1 * sx)
        y1 = int(box.y1 * sy)
        x2 = int(box.x2 * sx)
        y2 = int(box.y2 * sy)
        cv2.rectangle(vid, (x1, y1), (x2, y2), FACE_BOX, 2)
        fcx = int(box.cx * sx)
        fcy = int((box.y1 + box.y2) / 2 * sy)
        cv2.circle(vid, (fcx, fcy), 4, ACCENT_AMBER, -1)


def _draw_video_legend(vid: np.ndarray, vw: int, vh: int, ctx: DashboardContext) -> None:
    """Bottom strip inside video panel"""
    bar_h = 52
    overlay = np.zeros((bar_h, vw, 3), dtype=np.uint8)
    overlay[:] = (25, 25, 28)
    alpha = 0.72
    y0 = vh - bar_h
    roi = vid[y0 : y0 + bar_h, 0:vw]
    blended = (alpha * overlay + (1 - alpha) * roi).astype(np.uint8)
    vid[y0 : y0 + bar_h, 0:vw] = blended

    fc = ctx.face_cx if ctx.face_cx is not None else float("nan")
    off = ctx.err_px
    centered = abs(off) <= 40  # loose display; matches deadband order of magnitude
    line1 = f"Face center X: {fc:.0f}   Frame center X: {ctx.frame_cx:.0f}" if ctx.has_face else "No face detected"
    line2 = (
        f"Offset: {off:+.0f} px   {('CENTERED' if centered else 'ADJUSTING')}"
        if ctx.has_face
        else "Align subject in frame"
    )
    ty = y0 + 22
    _draw_text(vid, line1, 12, ty, 0.45, TEXT_PRIMARY if ctx.has_face else TEXT_SECONDARY, 1)
    _draw_text(vid, line2, 12, ty + 20, 0.42, ACCENT_GREEN if (ctx.has_face and centered) else TEXT_SECONDARY, 1)


def _card(
    img: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    title: str,
) -> Tuple[int, int]:
    _filled_rect(img, x1, y1, x2, y2, PANEL)
    _border_rect(img, x1, y1, x2, y2, PANEL_BORDER, 1)
    _draw_text(img, title, x1 + 12, y1 + 22, 0.48, TEXT_SECONDARY, 1)
    return x1 + 12, y1 + 44


def _draw_sidebar(img: np.ndarray, x0: int, y0: int, w: int, h: int, ctx: DashboardContext) -> None:
    x1, y1 = x0, y0
    x2, y2 = x0 + w, y0 + h

    # Card 1 — Heart rate
    mid = y0 + (h // 2) - 8
    cx, cy = _card(img, x1, y1, x2, mid, "HEART RATE MONITORING")
    bpm = ctx.last_bpm
    bpm_str = f"{bpm:.0f}" if bpm is not None else "-"
    _draw_text(img, bpm_str, cx, cy + 36, 2.0, TEXT_PRIMARY, 2)
    tw_bpm, _ = _text_size(bpm_str, 2.0, 2)
    _draw_text(img, "BPM", cx + tw_bpm + 14, cy + 36, 0.55, TEXT_MUTED, 1)
    sq_lab = _sqi_quality_label(ctx.last_sqi)
    _draw_text(img, "Signal quality", cx, cy + 78, 0.42, TEXT_SECONDARY, 1)
    _draw_text(img, sq_lab, cx + 132, cy + 78, 0.42, ACCENT_GREEN if ctx.last_sqi and ctx.last_sqi >= 0.4 else TEXT_SECONDARY, 1)
    bar_w = x2 - cx - 12
    bar_y = cy + 94
    bar_h = 5
    _filled_rect(img, cx, bar_y, cx + bar_w, bar_y + bar_h, (38, 40, 44))
    if ctx.last_sqi is not None:
        fill = int(bar_w * max(0.0, min(1.0, float(ctx.last_sqi))))
        if fill > 0:
            _filled_rect(img, cx, bar_y, cx + fill, bar_y + bar_h, ACCENT_GREEN)

    # Card 2 — rPPG analysis
    cx2, cy2 = _card(img, x1, mid + 8, x2, y2, "RPPG ANALYSIS")
    rr = ctx.last_rr
    rr_str = f"{rr:.1f} RPM" if rr is not None else "-"
    _draw_text(img, "Breathing rate", cx2, cy2 + 8, 0.42, TEXT_SECONDARY, 1)
    _draw_text(img, rr_str, cx2 + 150, cy2 + 8, 0.48, TEXT_PRIMARY, 1)
    ms = _monitoring_status(ctx)
    _draw_text(img, "Monitoring status", cx2, cy2 + 38, 0.42, TEXT_SECONDARY, 1)
    col = ACCENT_GREEN if ms == "Stable" else (ACCENT_AMBER if ms in ("Marginal", "Acquiring") else TEXT_PRIMARY)
    if ms == "Inactive":
        col = TEXT_MUTED
    _draw_text(img, ms.upper(), cx2 + 180, cy2 + 38, 0.48, col, 1)


def _draw_footer(img: np.ndarray, y: int, w: int, ctx: DashboardContext) -> None:
    _filled_rect(img, 0, y, w, DASHBOARD_H, HEADER_BG)
    _border_rect(img, 0, y, w, DASHBOARD_H, PANEL_BORDER, 1)
    if not ctx.serial_enabled:
        servo = "DISABLED"
    elif "PAN_LEFT" in ctx.last_cmd or "PAN_RIGHT" in ctx.last_cmd:
        servo = "TRACKING"
    else:
        servo = "STOPPED"
    meas = "ACTIVE" if ctx.state == "MEASURE" else "INACTIVE"
    inp = "LIVE CAMERA" if ctx.input_mode == "live" else "VIDEO FILE"
    rec = "ON" if ctx.recording else "OFF"
    line_a = f"  SERVO: {servo}     MEASUREMENT: {meas}     INPUT: {inp}     RECORD: {rec}"
    if ctx.mock_serial:
        line_a += "     (SERIAL MOCK)"
    _draw_text(img, "SYSTEM STATUS", PAD, y + 22, 0.42, TEXT_MUTED, 1)
    _draw_text(img, line_a, PAD + 140, y + 22, 0.42, TEXT_PRIMARY, 1)
    help_bar = "[Q] Quit   [C] Capture   [V] Record   [R] Reset   [S] Toggle serial"
    tw = _text_size(help_bar, 0.38, 1)[0]
    _draw_text(img, help_bar, w - tw - PAD, y + 22, 0.38, TEXT_MUTED, 1)


def render_dashboard(
    frame_bgr: np.ndarray,
    ctx: DashboardContext,
    box: Optional["FaceBox"],
) -> np.ndarray:
    """
    Composite full dashboard image. `frame_bgr` is the raw camera frame (BGR).
    """
    h0, w0 = frame_bgr.shape[:2]
    out = np.zeros((DASHBOARD_H, DASHBOARD_W, 3), dtype=np.uint8)
    out[:] = BG

    _draw_header(out, DASHBOARD_W)
    y_state = HEADER_H
    _filled_rect(out, 0, y_state, DASHBOARD_W, y_state + STATE_ROW_H, BG)
    _draw_state_row(out, y_state, DASHBOARD_W, _active_state_key(ctx))

    y_main = HEADER_H + STATE_ROW_H + PAD
    main_h = DASHBOARD_H - y_main - FOOTER_H - PAD
    video_w = DASHBOARD_W - SIDEBAR_W - 3 * PAD
    video_x = PAD
    sidebar_x = video_x + video_w + PAD

    vid = cv2.resize(frame_bgr, (video_w, main_h), interpolation=cv2.INTER_AREA)
    _draw_video_overlays(vid, video_w, main_h, w0, h0, box, ctx.frame_cx)
    _draw_video_legend(vid, video_w, main_h, ctx)

    out[y_main : y_main + main_h, video_x : video_x + video_w] = vid

    label_y = y_main + 8
    _draw_text(out, "LIVE CAMERA", video_x + 8, label_y, 0.38, TEXT_MUTED, 1)

    _draw_sidebar(out, sidebar_x, y_main, SIDEBAR_W, main_h, ctx)

    fps = ctx.fps_ema
    fps_s = f"{fps:.1f} FPS" if fps else ""
    if fps_s:
        _draw_text(out, fps_s, DASHBOARD_W - PAD - _text_size(fps_s, 0.38, 1)[0], label_y, 0.38, TEXT_MUTED, 1)

    y_foot = DASHBOARD_H - FOOTER_H
    _draw_footer(out, y_foot, DASHBOARD_W, ctx)

    return out
