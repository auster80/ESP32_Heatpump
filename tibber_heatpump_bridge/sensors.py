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
SENSOR_TYPES = ("ntc", "pt1000", "kty")


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


@dataclass(frozen=True)
class KtySensor:
    """Silicon PTC of the KTY81-2xx family, the second characteristic printed
    in the Tecalor TTF manual (2000 ohms at 25 C, 1630 at 0 C).

    R(T) = r25 * (1 + alpha*(T-25) + beta*(T-25)^2), which reproduces the
    manual's table to within about 3 ohms at the cold end.
    """

    r25: float = 2000.0
    alpha: float = 7.874e-3
    beta: float = 1.874e-5

    def resistance(self, temp_c: float) -> float:
        d = temp_c - 25.0
        return self.r25 * (1.0 + self.alpha * d + self.beta * d * d)

    def temperature(self, ohms: float) -> float:
        if ohms <= 0:
            raise ValueError("resistance must be positive")
        # Positive root of beta*d^2 + alpha*d + (1 - ohms/r25) = 0.
        c = 1.0 - ohms / self.r25
        disc = self.alpha * self.alpha - 4.0 * self.beta * c
        if disc < 0:
            raise ValueError(f"resistance {ohms} is outside the KTY characteristic")
        return 25.0 + (-self.alpha + math.sqrt(disc)) / (2.0 * self.beta)


Sensor = NtcSensor | Pt1000Sensor | KtySensor


def make_sensor(kind: str, **params: float) -> Sensor:
    kind = kind.lower()
    if kind == "ntc":
        return NtcSensor(**params)
    if kind == "pt1000":
        return Pt1000Sensor(**params)
    if kind == "kty":
        return KtySensor(**params)
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
class ResistorLadder:
    """Fixed base resistor plus binary-weighted resistors, each shorted by a
    latching relay (option B in docs/virtual-outdoor-sensor.md).

    PT1000 and KTY span too little resistance for a digital potentiometer to
    resolve, and a relay ladder has no supply-voltage limit, is galvanically
    isolated by construction, and draws no coil current between changes.

    The tap is the binary code: bit *i* set means ``steps[i]`` is in circuit.
    Exposes the same ``taps`` / ``resistance_at`` / ``tap_for`` surface as
    :class:`DigitalPotentiometer`, so ``emulate``, ``resolution_k`` and
    ``coverage_c`` work against either actuator.
    """

    base_ohms: float
    steps: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("a ladder needs at least one step resistor")
        if any(step <= 0 for step in self.steps):
            raise ValueError("ladder step resistors must be positive")

    @property
    def taps(self) -> int:
        return 1 << len(self.steps)

    @property
    def span_ohms(self) -> float:
        return sum(self.steps)

    def resistance_at(self, tap: int) -> float:
        tap = min(self.taps - 1, max(0, int(tap)))
        extra = sum(step for i, step in enumerate(self.steps) if tap >> i & 1)
        return self.base_ohms + extra

    def tap_for(self, ohms: float) -> int:
        """Closest code to ``ohms``; exact for a binary-weighted 1,2,4,... ladder."""
        wanted = ohms - self.base_ohms
        if wanted <= 0:
            return 0
        best, best_error = 0, abs(wanted)
        for tap in range(self.taps):
            error = abs(self.resistance_at(tap) - self.base_ohms - wanted)
            if error < best_error:
                best, best_error = tap, error
        return best

    def relays_for(self, tap: int) -> tuple[bool, ...]:
        """Per-relay state for ``tap``: True means that resistor is in circuit."""
        tap = min(self.taps - 1, max(0, int(tap)))
        return tuple(bool(tap >> i & 1) for i in range(len(self.steps)))


Actuator = DigitalPotentiometer | ResistorLadder


def _parallel(a: float, b: float) -> float:
    return a * b / (a + b)


@dataclass(frozen=True)
class ShuntEmulator:
    """The real sensor stays in the measurement path; a digital rheostat in
    **parallel** pulls the presented resistance down, and a small fixed series
    resistor biases the whole range so both directions are reachable.

        X2 T(A) o──┬── R_bias ── AFS 2 ──┬──o X26
                   └──── digipot ────────┘

    Why not synthesise the resistance outright (a ladder or a pot in series):
    the controllable element would sit in series with the measurement, so its
    contact and tolerance errors land at full weight on a signal whose whole
    useful span is ~150 ohms. Here the rheostat is tens of kiloohms making a
    small correction to a ~1 kohm sensor, so a 1 % part error becomes a 1 %
    error *of the shift* -- hundredths of a kelvin -- and the pump keeps its
    own commissioned sensor and its calibration.

    It also means the emulator never needs to measure the outdoor temperature:
    real weather passes through the sensor by itself, and the true value can be
    recovered from what the pump reports plus the tap that was set
    (:meth:`recover_real_c`).

    ``bias_ohms`` in series shifts the whole range warmer, which buys the
    "pretend it is milder" direction; with the rheostat open the pump reads
    ``bias_ohms`` worth of degrees too warm, and closing it pulls back down
    past the true value.
    """

    sensor: Sensor
    pot: DigitalPotentiometer
    bias_ohms: float = 39.0
    min_present_c: float = -30.0
    max_present_c: float = 35.0
    """Never present a temperature outside this window (section 2, item 4).

    At the closed end the rheostat approaches its wiper resistance, which would
    short the sensor and read hundreds of degrees below zero -- a sensor fault
    to the pump. :meth:`safe_taps` is the range that respects the window and is
    what every other method clamps to.
    """

    def safe_taps(self, real_c: float) -> tuple[int, int]:
        """Lowest and highest tap that keep the presented value in the window."""
        lo, hi = 0, self.pot.taps - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.presented_c(real_c, mid) < self.min_present_c:
                lo = mid + 1
            else:
                hi = mid
        highest = self.pot.taps - 1
        if self.presented_c(real_c, highest) > self.max_present_c:
            lo2, hi2 = lo, highest
            while lo2 < hi2:
                mid = (lo2 + hi2 + 1) // 2
                if self.presented_c(real_c, mid) > self.max_present_c:
                    hi2 = mid - 1
                else:
                    lo2 = mid
            highest = lo2
        return lo, highest

    def presented_ohms(self, real_c: float, tap: int) -> float:
        return _parallel(self.sensor.resistance(real_c) + self.bias_ohms, self.pot.resistance_at(tap))

    def presented_c(self, real_c: float, tap: int) -> float:
        return self.sensor.temperature(self.presented_ohms(real_c, tap))

    def shift_k(self, real_c: float, tap: int) -> float:
        """Positive means the pump is being told it is colder than it is."""
        return real_c - self.presented_c(real_c, tap)

    def tap_for_shift(self, real_c: float, shift_k: float) -> int:
        """Tap that presents ``fake_temperature(real_c, shift_k)``."""
        target_ohms = self.sensor.resistance(fake_temperature(real_c, shift_k))
        source_ohms = self.sensor.resistance(real_c) + self.bias_ohms
        lowest, highest = self.safe_taps(real_c)
        if target_ohms >= source_ohms:
            return highest  # rheostat open: the warmest we can present
        tap = self.pot.tap_for(1.0 / (1.0 / target_ohms - 1.0 / source_ohms))
        return min(highest, max(lowest, tap))

    def recover_real_c(self, presented_c: float, tap: int) -> float:
        """True outdoor temperature from what the pump reports and the tap set.

        Lets the controller close the loop through the pump's own read-only
        outdoor register instead of a second temperature sensor.
        """
        presented_ohms = self.sensor.resistance(presented_c)
        pot_ohms = self.pot.resistance_at(tap)
        if presented_ohms >= pot_ohms:
            raise ValueError("presented resistance is not below the shunt; tap cannot be inverted")
        return self.sensor.temperature(1.0 / (1.0 / presented_ohms - 1.0 / pot_ohms) - self.bias_ohms)

    def shift_range_k(self, real_c: float) -> tuple[float, float]:
        """Most negative and most positive shift reachable safely at ``real_c``."""
        lowest, highest = self.safe_taps(real_c)
        a, b = self.shift_k(real_c, lowest), self.shift_k(real_c, highest)
        return (a, b) if a < b else (b, a)


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


def emulate(sensor: Sensor, pot: Actuator, target_c: float) -> Emulation:
    """Pick the tap that best reproduces ``target_c`` and report the achieved value."""
    target_ohms = sensor.resistance(target_c)
    tap = pot.tap_for(target_ohms)
    achieved_ohms = pot.resistance_at(tap)
    return Emulation(target_c, target_ohms, tap, achieved_ohms, sensor.temperature(achieved_ohms))


def resolution_k(sensor: Sensor, pot: Actuator, temp_c: float) -> float:
    """Temperature change caused by one tap step around ``temp_c``."""
    tap = pot.tap_for(sensor.resistance(temp_c))
    tap = min(pot.taps - 2, max(0, tap))
    low = sensor.temperature(pot.resistance_at(tap))
    high = sensor.temperature(pot.resistance_at(tap + 1))
    return abs(high - low)


def coverage_c(sensor: Sensor, pot: Actuator) -> tuple[float, float]:
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
