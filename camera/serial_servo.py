"""
Serial servo driver: PAN_LEFT, PAN_RIGHT, STOP (newline-terminated).

Toggle MOCK_SERIAL in config to print commands instead of writing to hardware.
To use angle commands instead, replace send_* bodies with e.g. ser.write(b"PAN:90\n").
"""

from __future__ import annotations

import logging
import time
from typing import Optional

try:
    import serial
except ImportError:
    serial = None  # type: ignore

log = logging.getLogger(__name__)


class ServoSerial:
    def __init__(
        self,
        port: str,
        baud: int,
        mock: bool = True,
        enabled: bool = True,
    ) -> None:
        self._port = port
        self._baud = baud
        self.mock = mock
        self.enabled = enabled
        self._ser: Optional["serial.Serial"] = None
        if not mock and enabled and serial is not None:
            try:
                # dsrdtr=False avoids extra DTR toggles on Windows that can reset some boards
                try:
                    self._ser = serial.Serial(
                        port,
                        baud,
                        timeout=0.05,
                        write_timeout=2.0,
                        dsrdtr=False,
                        rtscts=False,
                    )
                except TypeError:
                    self._ser = serial.Serial(port, baud, timeout=0.05)
                log.info("Serial OPEN (real hardware): %s @ %s — bytes are sent to Arduino", port, baud)
            except OSError as e:
                log.warning("Serial open failed (%s); falling back to mock prints", e)
                self.mock = True

        if self.mock:
            log.warning(
                "MOCK_SERIAL: commands only print to this console — nothing is sent to the Arduino. "
                "Set MOCK_SERIAL=false and SERIAL_PORT to your COM port (and close Arduino Serial Monitor)."
            )

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except OSError:
                pass
            self._ser = None

    def _write_line(self, line: str) -> None:
        if not self.enabled:
            return
        payload = (line.strip() + "\n").encode("ascii", errors="ignore")
        if self.mock or self._ser is None:
            print(f"[SERVO] {line}", flush=True)
            return
        try:
            self._ser.write(payload)
            self._ser.flush()
        except Exception as e:
            log.warning("Serial write failed: %s", e)

    def send_pan_left(self) -> None:
        self._write_line("PAN_LEFT")

    def send_pan_right(self) -> None:
        self._write_line("PAN_RIGHT")

    def send_stop(self) -> None:
        self._write_line("STOP")


class RateLimitedPan:
    """Avoid flooding serial: minimum gap between non-STOP commands."""

    def __init__(self, servo: ServoSerial, cooldown_s: float) -> None:
        self.servo = servo
        self.cooldown_s = cooldown_s
        self._last_cmd_time = 0.0
        self._last_sent: Optional[str] = None

    def request_pan_left(self) -> None:
        self._maybe_send("LEFT", self.servo.send_pan_left)

    def request_pan_right(self) -> None:
        self._maybe_send("RIGHT", self.servo.send_pan_right)

    def request_stop(self) -> None:
        now = time.monotonic()
        if self._last_sent == "STOP" and now - self._last_cmd_time < self.cooldown_s:
            return
        self.servo.send_stop()
        self._last_sent = "STOP"
        self._last_cmd_time = now

    def _maybe_send(self, name: str, fn) -> None:
        now = time.monotonic()
        if now - self._last_cmd_time < self.cooldown_s and self._last_sent not in (None, "STOP"):
            return
        fn()
        self._last_sent = name
        self._last_cmd_time = now
