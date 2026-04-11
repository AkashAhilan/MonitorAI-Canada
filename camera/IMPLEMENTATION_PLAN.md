# Implementation plan (staged checklist)

Use this as a **fast iteration** guide. Test with the **real USB camera** first at each stage; use **video file** mode for repeatable rPPG debugging.

## Dependencies

- Python 3.10–3.12 recommended.
- From repo root: `python -m pip install -r camera/requirements.txt`
- Verify: `python camera/verify_imports.py`

## Stage 0 — Plan

- Architecture: SEARCH → LOCK → MEASURE; abort to SEARCH on loss / motion / low quality.
- Risks: open-rppg + JAX CPU can be slow on first run; large wheel download.

## Stage 1 — Smoke test (camera path)

**Run:** `python -m camera.smoke_camera` (from repo root)

**Check:**

- Window shows live feed; overlay shows `LIVE MODE`, resolution, approximate FPS.
- Console prints mode, camera index, size.
- `q` quit, `c` saves PNG under `camera_captures/`, `v` toggles MP4 recording (`camera_record.mp4` by default).

**Video file:** set `INPUT_MODE=video` and `VIDEO_PATH` (see README).

## Stage 2 — Face + mock servo

**Run:** `python -m camera.app` with `MOCK_SERIAL=true` (default)

**Check:**

- Green box on largest / center-tie-break face.
- When off-center, terminal shows `[SERVO] PAN_LEFT` / `PAN_RIGHT`; near center shows `STOP` (throttled).

## Stage 3 — Lock + measure

**Check:**

- Stay centered: state goes SEARCH → LOCK → MEASURE (see on-screen `STATE:`).
- In MEASURE, no new pan commands (`cmd: hold (measure)`).

## Stage 4 — rPPG

**Check:**

- After buffer fills (~`MEASURE_BUFFER_FRAMES`), HR/SQI line updates (may take seconds on CPU).
- Poor SQI or failed inference repeatedly returns to SEARCH.

## Stage 5 — Real serial

- Set `MOCK_SERIAL=false`, `SERIAL_PORT` (e.g. `COM3`), connect Arduino.
- Use `s` in the app to toggle serial if you need to test without hardware.

## Stage 6 — Polish

- Thresholds in `camera/config.py` (deadband, lock frames, measure drift, SQI min).
- Record a short clip with smoke test `v`, then debug with `INPUT_MODE=video`.
