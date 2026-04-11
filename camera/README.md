# Waiting-room camera prototype

Local **Windows-friendly** demo: **OpenCV** capture + **MediaPipe** face detection (no identity) + **open-rppg** heart-rate estimate + **pyserial** pan servo (mock or real).

## Setup

1. **Python** 3.10–3.12 recommended.

2. Create a venv (recommended):

   ```text
   cd path\to\MonitorAI-Canada
   python -m venv .venv
   .venv\Scripts\activate
   python -m pip install -r camera/requirements.txt
   ```

3. **Verify imports:**

   ```text
   python camera/verify_imports.py
   ```

   First import of **open-rppg** / **JAX** may be slow; models download on first rPPG inference.

## Configuration (where to edit)

All defaults live in [`config.py`](config.py). You can override many values with **environment variables** (same name as the attribute), for example:

| Variable | Purpose |
|----------|---------|
| `INPUT_MODE` | `live` (webcam) or `video` (file) |
| `VIDEO_PATH` | Path to MP4/AVI when `INPUT_MODE=video` |
| `VIDEO_LOOP` | `true`/`false` — loop file when it ends (default `true`) |
| `CAMERA_INDEX` | Preferred camera index (default **`1`** — matches many Windows setups where `0` is unused; your `testing.py` uses `1`) |
| `CAMERA_PROBE` | If `true` (default), try other indices/backends until frames are not black |
| `CAMERA_WIN32_DSHOW_FIRST` | If `true` (default), try **DirectShow before** default/MSMF on Windows (avoids MSMF dying after a few seconds with `can't grab frame` / `-1072873822`) |
| `CAMERA_READ_RETRIES` | Per-frame read retries before reopening the device (default `20`) |
| `SERIAL_PORT` | e.g. `COM3` |
| `SERIAL_BAUD` | e.g. `115200` |
| `MOCK_SERIAL` | `true` = print commands only (default) |
| `SERIAL_ENABLED` | `false` = never open serial (keyboard `s` toggles at runtime in the app) |
| `DEADBAND_PX` | No pan if horizontal error ≤ this (pixels) |
| `CENTER_THRESHOLD_PX` | “Centered” for lock counter (pixels) |
| `LOCK_CONSECUTIVE_FRAMES` | Frames centered before LOCK |
| `SETTLE_MS` | Pause in LOCK before MEASURE |
| `SERVO_COOLDOWN_MS` | Min time between pan commands |
| `MEASURE_BUFFER_FRAMES` | Face crops buffered for rPPG (default 300; lower = faster but less stable) |
| `MEASURE_FPS_ASSUMED` | FPS passed to open-rppg if live FPS unknown |
| `RPPG_INFER_EVERY_MS` | Min gap between rPPG runs |
| `FACE_CROP_SIZE` | Square crop size sent to rPPG |
| `SQI_MIN` | Abort MEASURE if SQI stays below this |
| `LOW_SQI_FRAMES_BEFORE_ABORT` | Consecutive bad inferences before abort |
| `MEASURE_MAX_FACE_SHIFT_PX` | Max face horizontal drift in MEASURE |
| `SMOKE_CAPTURE_DIR` | Where `c` saves PNGs |
| `SMOKE_RECORD_PATH` | Default MP4 path for `v` recording |

**PowerShell example (video file):**

```powershell
$env:INPUT_MODE="video"
$env:VIDEO_PATH="C:\path\to\clip.mp4"
python -m camera.app
```

## Run commands

From the **repository root** (`MonitorAI-Canada`):

```text
python -m camera.smoke_camera
python -m camera.app
```

Alternative:

```text
cd camera
python smoke_camera.py
python app.py
```

## Keyboard

| Key | Smoke test | Main app |
|-----|------------|----------|
| `q` | Quit | Quit |
| `c` | Save PNG | Save PNG |
| `v` | Toggle MP4 record | Toggle MP4 record |
| `r` | — | Reset state machine to SEARCH |
| `s` | — | Toggle serial enabled |

## State machine (short)

1. **SEARCH** — Find faces; draw box; pan mock/real servo to center the face (deadband + rate limit).
2. **LOCK** — Face stays within `CENTER_THRESHOLD_PX` for `LOCK_CONSECUTIVE_FRAMES`; send **STOP**; wait `SETTLE_MS`.
3. **MEASURE** — No servo motion; rolling buffer of face crops; periodic **open-rppg** → HR / SQI on screen.
4. **Abort to SEARCH** — Face lost; too much motion vs reference; repeated low SQI / failed inference.

There is no separate **LOST** screen state: the app logs `LOST→SEARCH` and resumes SEARCH.

## Serial protocol (Arduino-friendly)

Default messages (one line each, ASCII):

- `PAN_LEFT`
- `PAN_RIGHT`
- `STOP`

Edit [`serial_servo.py`](serial_servo.py) if you prefer `PAN:<angle>` etc.

**Arduino:** ready-to-flash sketch (direct **`Servo`** on pin **9**) and wiring notes are in [`firmware/README.md`](firmware/README.md).

## rPPG integration

[`rppg_infer.py`](rppg_infer.py) calls `rppg.Model.process_faces_tensor` with **uint8 RGB** tensors `(T, H, W, 3)` — crops are converted from OpenCV **BGR** first. Swap this module if you change engines later.

## Troubleshooting

- **`AttributeError: module 'mediapipe' has no attribute 'solutions'`:** Recent PyPI `mediapipe` builds only ship the **Tasks** API. This project uses **Tasks `FaceDetector`** automatically and downloads `blaze_face_*.tflite` into [`camera/.cache/`](.cache/) on first run (needs network once).
- **Black window / “camera with a line through it” but overlays show:** usually wrong **index** or **backend**. Use `CAMERA_PROBE=true` and check the console for `resolved_camera_index` / `backend`.
- **Feed works briefly then stops with MSMF warnings** (`can't grab frame`, `-1072873822`): common **Media Foundation** bug. Defaults use **`CAMERA_WIN32_DSHOW_FIRST=true`** so **DirectShow** is tried first; the app also **retries reads** and **reopens** the camera if the stream drops. If you must use MSMF, set `CAMERA_WIN32_DSHOW_FIRST=false`.
- **Wrong device:** change `CAMERA_INDEX`; close other apps using the webcam.
- **open-rppg slow / freezes:** reduce `MEASURE_BUFFER_FRAMES` or increase `RPPG_INFER_EVERY_MS`.
- **No COM port:** use `MOCK_SERIAL=true` or press `s` to disable serial.

## Next upgrades (not implemented here)

- Forehead / cheek ROI for rPPG
- Micro-expression or discomfort cues
- Emotion estimation (would be a separate, explicit feature)
- Respiration: open-rppg may expose breathing rate in `hrv` when SQI is good — see `format_hr_display` in [`rppg_infer.py`](rppg_infer.py)
- Stronger target selection (e.g. Kalman on box)

## Fallback engine

This build uses **open-rppg** only. If it fails to install or run on your machine, switch the implementation in [`rppg_infer.py`](rppg_infer.py) to another library and document it here — no fallback package is wired in by default.
