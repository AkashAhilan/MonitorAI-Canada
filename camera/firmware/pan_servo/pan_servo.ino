/*
  Pan servo — serial line commands from MonitorAI camera app (Python).

  Drives the pan servo directly from one Arduino PWM pin using Servo.h (no motor driver).

  Protocol (ASCII, newline-terminated, must match camera/serial_servo.py):
    PAN_LEFT   — decrease angle by STEP_DEGREES (clamp to PAN_MIN)
    PAN_RIGHT  — increase angle by STEP_DEGREES (clamp to PAN_MAX)
    STOP       — hold current angle (no movement)

  Wiring (typical SG90 / MG90S):
    Servo signal (orange/yellow) -> pin 9 (SERVO_PIN)
    Servo VCC (red)             -> 5V (external 5V if servo browns out USB)
    Servo GND (brown/black)     -> GND

  After upload, close Arduino Serial Monitor before running the Python app (port is exclusive on Windows).
*/

#include <Servo.h>

// --- Match Python: camera/config.py SERIAL_BAUD default ---
static const long SERIAL_BAUD = 115200;

// --- Servo: direct pin (PWM-capable pin on your board; Uno/Nano: 9 is fine) ---
static const int SERVO_PIN = 9;

static const int PAN_MIN = 0;
static const int PAN_MAX = 180;
static const int START_ANGLE = 90;
// Degrees per command (Python rate-limits PAN_*; increase if too slow, decrease if jerky)
static const int STEP_DEGREES = 3;

// If the mount is reversed: set true so PAN_LEFT / PAN_RIGHT match your rig
static const bool SWAP_LEFT_RIGHT = false;

// Uncomment to echo unknown lines on Serial (USB)
// #define DEBUG 1

Servo pan;
int currentAngle = START_ANGLE;
String lineBuffer;

void applyPanLeft() {
  int delta = SWAP_LEFT_RIGHT ? STEP_DEGREES : -STEP_DEGREES;
  moveBy(delta);
}

void applyPanRight() {
  int delta = SWAP_LEFT_RIGHT ? -STEP_DEGREES : STEP_DEGREES;
  moveBy(delta);
}

void moveBy(int delta) {
  int next = currentAngle + delta;
  if (next < PAN_MIN) next = PAN_MIN;
  if (next > PAN_MAX) next = PAN_MAX;
  if (next != currentAngle) {
    currentAngle = next;
    pan.write(currentAngle);
  }
}

void setup() {
  pan.attach(SERVO_PIN);
  pan.write(currentAngle);

  Serial.begin(SERIAL_BAUD);
#if defined(USBCON) || defined(ARDUINO_USB_CDC_ON_BOOT)
  while (!Serial) { ; }
#endif

  lineBuffer.reserve(32);
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      handleLine(lineBuffer);
      lineBuffer = "";
    } else if (lineBuffer.length() < 48) {
      lineBuffer += c;
    } else {
      lineBuffer = "";
    }
  }
}

void handleLine(String &raw) {
  raw.trim();
  if (raw.length() == 0) {
    return;
  }

  if (raw == "PAN_LEFT") {
    applyPanLeft();
  } else if (raw == "PAN_RIGHT") {
    applyPanRight();
  } else if (raw == "STOP") {
    // Hold position — Python sends STOP when centered
    ;
  } else {
#ifdef DEBUG
    Serial.print(F("? "));
    Serial.println(raw);
#endif
  }
}
