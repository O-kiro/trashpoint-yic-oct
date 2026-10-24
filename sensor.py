"""IR deposit sensor + LED/buzzer feedback + sort servo for the TrashPoint smart bin.

Wiring (BCM numbering):
  - IR_PIN: single IR sensor at the deposit chamber (active LOW) — just
    detects "something was dropped in", no plastic/aluminum distinction
    anymore (that now happens via camera + model classification).
  - FEEDBACK_PIN: shared LED + buzzer line. Same pin drives both — wire
    the LED and the buzzer's control line together to GPIO 23 (through
    their own current-limiting resistor/driver as needed). Success and
    error are told apart by blink/beep pattern, not color, since it's
    one pin now.
  - SERVO_PIN: sort servo, driven via RPi.GPIO's software PWM.
  - LIGHT_PIN: illumination light for the deposit chamber, turned on
    right before photographing an item (so the classifier gets a
    properly lit photo) and off again right after.
"""

import time

import RPi.GPIO as GPIO

IR_PIN = 17
FEEDBACK_PIN = 23
SERVO_PIN = 18
LIGHT_PIN = 4

DETECT_TIMEOUT_S = 15.0
POLL_INTERVAL_S = 0.02

SERVO_FREQ_HZ = 50
NEUTRAL_ANGLE = 90.0
SORT_HOLD_S = 0.8  # how long to hold the sort angle before returning to neutral


class BinSensors:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(IR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(FEEDBACK_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(LIGHT_PIN, GPIO.OUT, initial=GPIO.LOW)

        GPIO.setup(SERVO_PIN, GPIO.OUT)
        self._servo_pwm = GPIO.PWM(SERVO_PIN, SERVO_FREQ_HZ)
        self._servo_pwm.start(0)
        self.set_servo_angle(NEUTRAL_ANGLE)  # start centered, not wherever it last was

    def wait_for_item(self, timeout_s: float = DETECT_TIMEOUT_S) -> bool:
        """Waits for an item to break the IR beam.

        Returns True if something was detected, False on timeout.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if GPIO.input(IR_PIN) == GPIO.LOW:
                return True
            time.sleep(POLL_INTERVAL_S)
        return False

    def item_present(self) -> bool:
        """Non-blocking single check — use this when you also need to poll
        something else (like a display button) in the same loop, instead
        of wait_for_item() which blocks."""
        return GPIO.input(IR_PIN) == GPIO.LOW

    def light_on(self):
        GPIO.output(LIGHT_PIN, GPIO.HIGH)

    def light_off(self):
        GPIO.output(LIGHT_PIN, GPIO.LOW)

    def flash_success(self):
        # 2 short pulses = success
        self._pulse(times=2, on_s=0.15, off_s=0.1)

    def flash_error(self):
        # 1 long pulse = error
        self._pulse(times=1, on_s=0.6, off_s=0.1)

    def flash_reject(self):
        # 3 quick pulses ("tit-tit-tit") = item not recognized, try again
        self._pulse(times=3, on_s=0.1, off_s=0.1)

    def set_servo_angle(self, angle: float):
        """Moves the sort servo to `angle` degrees (0-180) and holds there.
        Use sort_to() instead if you want it to return to neutral after."""
        angle = max(0.0, min(180.0, angle))
        duty = 2.5 + (angle / 180.0) * 10.0
        self._servo_pwm.ChangeDutyCycle(duty)
        time.sleep(0.3)
        self._servo_pwm.ChangeDutyCycle(0)  # stop jitter/holding buzz

    def sort_to(self, angle: float, hold_s: float = SORT_HOLD_S):
        """Moves to `angle` to drop the item into the right bin, waits
        hold_s for it to fall through, then returns to NEUTRAL_ANGLE."""
        self.set_servo_angle(angle)
        time.sleep(hold_s)
        self.set_servo_angle(NEUTRAL_ANGLE)

    def _pulse(self, times: int, on_s: float, off_s: float):
        for _ in range(times):
            GPIO.output(FEEDBACK_PIN, GPIO.HIGH)
            time.sleep(on_s)
            GPIO.output(FEEDBACK_PIN, GPIO.LOW)
            time.sleep(off_s)

    def cleanup(self):
        self.light_off()
        self._servo_pwm.stop()
        GPIO.cleanup()