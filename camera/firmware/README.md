# Arduino pan servo (serial)

Firmware that pairs with the Python app in [`../`](../): it listens for the same text commands [`serial_servo.py`](../serial_servo.py) sends over USB serial.

The sketch drives the servo **directly** from one Arduino pin using **`Servo.h`** (default **pin 9**).

## Protocol

| Line (newline-terminated) | Action |
|---------------------------|--------|
| `PAN_LEFT` | Nudge pan angle down (see `STEP_DEGREES`, `PAN_MIN` / `PAN_MAX`) |
| `PAN_RIGHT` | Nudge pan angle up |
| `STOP` | Hold current angle (no motion) |

Baud rate must match Python: **115200** (see [`../config.py`](../config.py) `SERIAL_BAUD`).

## Flashing

1. Install [Arduino IDE](https://www.arduino.cc/en/software).
2. Open [`pan_servo/pan_servo.ino`](pan_servo/pan_servo.ino).
3. **Tools → Board** — your Arduino (Uno, Nano, etc.).
4. **Tools → Port** — COM port when the board is on USB.
5. **Upload**.
6. **Close Serial Monitor** before running the Python app (exclusive COM port on Windows).

No extra libraries beyond the built-in **Servo** library.

## Wiring (typical hobby servo, e.g. SG90)

| Servo lead | Connect |
|------------|---------|
| Signal (yellow/orange) | Arduino **D9** (see `SERVO_PIN` in the sketch) |
| VCC (red) | **5V** (use external 5V if the servo stalls or resets the board) |
| GND (brown/black) | **GND** |

Change **`SERVO_PIN`** at the top of `pan_servo.ino` if you use another pin.

## Run the Python app on real hardware

**PowerShell**

```powershell
$env:MOCK_SERIAL="false"
$env:SERIAL_PORT="COM3"   # same port as in Arduino IDE
$env:SERIAL_BAUD="115200"
python -m camera.app
```

Press `s` in the app to toggle serial if you test without the Arduino.

## If left and right are reversed

Set `SWAP_LEFT_RIGHT` to `true` in `pan_servo.ino`.

## Troubleshooting

- **Port busy:** Close Serial Monitor and other serial tools before `python -m camera.app`.
- **No movement:** Confirm baud **115200**, correct COM port, and servo power.
- **Jittery servo:** Reduce `STEP_DEGREES` in the sketch or increase `SERVO_COOLDOWN_MS` in Python [`config.py`](../config.py).
