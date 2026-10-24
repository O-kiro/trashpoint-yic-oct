#!/usr/bin/env python3
"""Standalone servo test — moves GPIO 18 from 0 to 180, then back to 90.

Run this directly to test/recenter the servo if it's stuck off-center.

Usage:
    python3 servo_reset.py
"""

import time

import RPi.GPIO as GPIO

SERVO_PIN = 18
SERVO_FREQ_HZ = 50

MIN_DUTY = 2.5   # duty cycle % at 0°
MAX_DUTY = 12.5  # duty cycle % at 180°

MOVE_WAIT_S = 1.0  # time to let the servo physically reach each position


def angle_to_duty(angle: float) -> float:
    angle = max(0.0, min(180.0, angle))
    return MIN_DUTY + (angle / 180.0) * (MAX_DUTY - MIN_DUTY)


def move_to(pwm, angle: float, label: str = ""):
    duty = angle_to_duty(angle)
    print(f"Moving to {angle}°{' (' + label + ')' if label else ''}...")
    pwm.ChangeDutyCycle(duty)
    time.sleep(MOVE_WAIT_S)
    pwm.ChangeDutyCycle(0)  # stop pulses so it doesn't jitter/buzz while holding


def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SERVO_PIN, GPIO.OUT)
    pwm = GPIO.PWM(SERVO_PIN, SERVO_FREQ_HZ)
    pwm.start(0)

    try:
        move_to(pwm, 0)
        time.sleep(0.5)
        move_to(pwm, 180)
        time.sleep(0.5)
        move_to(pwm, 97, label="back to center")
        print("Done — servo should now be centered at 90°.")
    except KeyboardInterrupt:
        pass
    finally:
        pwm.stop()
        GPIO.cleanup()


if __name__ == "__main__":
    main()