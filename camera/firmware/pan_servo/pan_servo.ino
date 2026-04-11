/*
  Pan servo — serial line commands from MonitorAI camera app (Python).

  Drives the pan servo directly from one Arduino PWM pin using Servo.h (no motor driver).

  Protocol (ASCII, newline-terminated, must match camera/serial_servo.py):
    PAN_LEFT   — nudge target angle by STEP_DEGREES (clamp to PAN_MIN)
    PAN_RIGHT  — nudge target angle by STEP_DEGREES (clamp to PAN_MAX)
    STOP       — hold current target (motion may still finish smoothing)

  Smoothing: PAN_* commands update a *target* angle; the servo eases toward it in small
  steps (see SMOOTH_* below) so motion is less choppy than instant pan.write() jumps.

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
// Degrees added to target per PAN command (Python rate-limits PAN_*)
static const int STEP_DEGREES = 3;

// If the mount is reversed: set true so PAN_LEFT / PAN_RIGHT match your rig
static const bool SWAP_LEFT_RIGHT = true;

// --- Smoothing (reduce choppy motion) ---
// Finer = smoother: 1° steps often (~8ms) reads as a slow pan instead of steps.
// If catch-up feels too slow, raise SMOOTH_MAX_STEP (e.g. 2) or lower SMOOTH_INTERVAL_MS slightly.
static const unsigned long SMOOTH_INTERVAL_MS = 8;
static const int SMOOTH_MAX_STEP = 1;

// Uncomment to echo unknown lines on Serial (USB)
// #define DEBUG 1

Servo pan;
int targetAngle = START_ANGLE;
int currentAngle = START_ANGLE;
unsigned long lastSmoothMs = 0;
String lineBuffer;

void smoothTowardTarget() {
  unsigned long now = millis();
  if (now - lastSmoothMs < SMOOTH_INTERVAL_MS) {
    return;
  }
  lastSmoothMs = now;
  if (currentAngle == targetAngle) {
    return;
  }
  int diff = targetAngle - currentAngle;
  int step;
  if (abs(diff) <= SMOOTH_MAX_STEP) {
    step = diff;
  } else {
    step = (diff > 0) ? SMOOTH_MAX_STEP : -SMOOTH_MAX_STEP;
  }
  currentAngle += step;
  pan.write(currentAngle);
}

void applyPanLeft() {
  int delta = SWAP_LEFT_RIGHT ? STEP_DEGREES : -STEP_DEGREES;
  moveBy(delta);
}

void applyPanRight() {
  int delta = SWAP_LEFT_RIGHT ? -STEP_DEGREES : STEP_DEGREES;
  moveBy(delta);
}

void moveBy(int delta) {
  long next = (long)targetAngle + delta;
  if (next < PAN_MIN) next = PAN_MIN;
  if (next > PAN_MAX) next = PAN_MAX;
  targetAngle = (int)next;
}

void setup() {
  pan.attach(SERVO_PIN);
  targetAngle = START_ANGLE;
  currentAngle = START_ANGLE;
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
  smoothTowardTarget();
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
    // Hold: stop changing target; servo finishes easing to last target
    ;
  } else {
#ifdef DEBUG
    Serial.print(F("? "));
    Serial.println(raw);
#endif
  }
}
