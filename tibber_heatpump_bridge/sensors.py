"""Outdoor sensor models and digital potentiometer emulation.

Heat pumps read their outdoor sensor as a resistance. To present a different
outdoor temperature the emulator must produce the resistance the sensor would
have at that temperature. Two sensor families cover nearly every hydronic heat
pump: NTC thermistors (10 kOhm at 25 C is the usual value) and PT1000 RTDs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KELVIN = 273.15
SENSOR_TYPES = ("ntc", "pt1000")


@dataclass(frozen=True)
class NtcSensor:
    """NTC thermistor described by the beta model."""

    r25: float = 10000.0
    beta: float = 3977.0

    def resistance(self, temp_c: float) -> float:
        return self.r25 * math.exp(self.beta * (1.0 / (temp_c + KELVIN) - 1.0 / (25.0 + KELVIN)))

    def temperature(self, ohms: float) -> float:
        if ohms <= 0:
            raise ValueError("resistance must be positive")
        inv_t = 1.0 / (25.0 + KELVIN) + math.log(ohms / self.r25) / self.beta
        return 1.0 / inv_t - KELVIN


@dataclass(frozen=True)
class Pt1000Sensor:
    """Platinum RTD following Callendar-Van Dusen (IEC 60751 coefficients)."""

    r0: float = 1000.0
    a: float = 3.9083e-3
    b: float = -5.775e-7
    c: float = -4.183e-12

    def resistance(self, temp_c: float) -> float:
        t = temp_c
        if t >= 0:
            return self.r0 * (1 + self.a * t + self.b * t * t)
        return self.r0 * (1 + self.a * t + self.b * t * t + self.c * (t - 100.0) * t**3)

    def temperature(self, ohms: float) -> float:
        if ohms <= 0:
            raise ValueError("resistance must be positive")
        t = (ohms / self.r0 - 1.0) / self.a
        for _ in range(20):
            f = self.resistance(t) - ohms
            derivative = (self.resistance(t + 0.01) - self.resistance(t - 0.01)) / 0.02
            step = f / derivative
            t -= step
            if abs(step) < 1e-6:
                break
        return t


Sensor = NtcSensor | Pt1000Sensor


def make_sensor(kind: str, **params: float) -> Sensor:
    kind = kind.lower()
    if kind == "ntc":
        return NtcSensor(**params)
    if kind == "pt1000":
        return Pt1000Sensor(**params)
    raise ValueError(f"sensor type must be one of {SENSOR_TYPES}, got {kind!r}")


@dataclass(frozen=True)
class DigitalPotentiometer:
    """Rheostat-connected digital potentiometer plus optional fixed series resistor.

    ``wiper_ohms`` is the wiper contact resistance (tens of ohms on most parts)
    which adds to every setting; ``series_ohms`` is an external resistor used
    to move the adjustable range (needed for PT1000, whose whole -30..+40 C
    span is only 880..1155 ohms).
    """

    full_scale_ohms: float = 100_000.0
    taps: int = 1024
    wiper_ohms: float = 0.0
    series_ohms: float = 0.0

    @property
    def step_ohms(self) -> float:
        return self.full_scale_ohms / (self.taps - 1)

    def resistance_at(self, tap: int) -> float:
        tap = min(self.taps - 1, max(0, tap))
        return self.series_ohms + self.wiper_ohms + tap * self.step_ohms

    def tap_for(self, ohms: float) -> int:
        adjustable = ohms - self.series_ohms - self.wiper_ohms
        return min(self.taps - 1, max(0, round(adjustable / self.step_ohms)))


@dataclass(frozen=True)
class Emulation:
    target_c: float
    target_ohms: float
    tap: int
    achieved_ohms: float
    achieved_c: float

    @property
    def error_k(self) -> float:
        return self.achieved_c - self.target_c


def emulate(sensor: Sensor, pot: DigitalPotentiometer, target_c: float) -> Emulation:
    """Pick the tap that best reproduces ``target_c`` and report the achieved value."""
    target_ohms = sensor.resistance(target_c)
    tap = pot.tap_for(target_ohms)
    achieved_ohms = pot.resistance_at(tap)
    return Emulation(target_c, target_ohms, tap, achieved_ohms, sensor.temperature(achieved_ohms))


def resolution_k(sensor: Sensor, pot: DigitalPotentiometer, temp_c: float) -> float:
    """Temperature change caused by one tap step around ``temp_c``."""
    tap = pot.tap_for(sensor.resistance(temp_c))
    tap = min(pot.taps - 2, max(0, tap))
    low = sensor.temperature(pot.resistance_at(tap))
    high = sensor.temperature(pot.resistance_at(tap + 1))
    return abs(high - low)


def coverage_c(sensor: Sensor, pot: DigitalPotentiometer) -> tuple[float, float]:
    """Coldest and warmest temperature the potentiometer can represent."""
    lowest_ohms = pot.resistance_at(0)
    highest_ohms = pot.resistance_at(pot.taps - 1)
    temps = sorted((sensor.temperature(max(lowest_ohms, 1e-3)), sensor.temperature(highest_ohms)))
    return temps[0], temps[1]


def fake_temperature(real_c: float, shift_k: float) -> float:
    """Outdoor temperature to present for a curve shift.

    A positive shift means "pretend it is colder", which makes the heat pump
    raise its supply temperature.
    """
    return real_c - shift_k
