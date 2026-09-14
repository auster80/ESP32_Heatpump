"""Heating-curve shifting through a virtual outdoor temperature.

The idea is the one Ngenic Tune uses: the heat pump keeps running its own
weather-compensated curve, but the outdoor temperature it sees is shifted.
A positive ``shift`` (in K) makes the pump believe it is colder, so it heats
more; a negative shift makes it believe it is milder, so it heats less or
stops. The planner picks a shift per price slot so that the indoor
temperature stays inside a comfort band while as much of the heating as
possible happens in cheap slots. The house's thermal mass is the battery.

Model (rates per hour)::

    dT_in/dt = c - a * T_in + b * shift_eff + d * T_out

``a`` is how fast the house plus the pump's own curve pull the room back to
its equilibrium ``c / a``; ``b`` is the indoor warming rate per K of shift;
``d`` captures imperfect weather compensation and is normally near 0. Heat
pumps smooth the outdoor reading, so the effective shift follows the applied
one with a first-order lag ``filter_minutes``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .tibber import PriceSlot

INF = float("inf")


@dataclass(frozen=True)
class HouseModel:
    a: float = 0.05  # 1/h
    b: float = 0.03  # K/h per K of shift
    c: float = 1.05  # K/h (equilibrium c/a = 21 C)
    d: float = 0.0  # 1/h
    filter_minutes: float = 60.0

    @property
    def equilibrium_c(self) -> float:
        return self.c / self.a if self.a else math.nan

    @property
    def time_constant_h(self) -> float:
        return 1.0 / self.a if self.a else math.inf

    def validate(self) -> None:
        if self.a <= 0:
            raise ValueError("house model 'a' must be positive (the room must settle)")
        if self.b <= 0:
            raise ValueError("house model 'b' must be positive (a shift must add heat)")
        if self.filter_minutes < 0:
            raise ValueError("filter_minutes must not be negative")

    def filter_step(self, shift_eff: float, shift: float, dt_minutes: float) -> float:
        if self.filter_minutes <= 0:
            return shift
        alpha = 1.0 - math.exp(-dt_minutes / self.filter_minutes)
        return shift_eff + alpha * (shift - shift_eff)

    def step(self, indoor_c: float, shift_eff: float, outdoor_c: float, dt_minutes: float) -> float:
        h = dt_minutes / 60.0
        return indoor_c + h * (self.c - self.a * indoor_c + self.b * shift_eff + self.d * outdoor_c)


@dataclass(frozen=True)
class PowerModel:
    """Electrical power of the heat pump in kW as a function of outdoor temperature and shift."""

    kw_per_k_outdoor: float = 0.06
    kw_per_k_shift: float = 0.08
    heat_limit_c: float = 16.0
    standby_kw: float = 0.0

    def validate(self) -> None:
        if self.kw_per_k_outdoor < 0 or self.kw_per_k_shift <= 0 or self.standby_kw < 0:
            raise ValueError("power model coefficients must be positive")

    def power_kw(self, outdoor_c: float, shift_eff: float) -> float:
        base = self.kw_per_k_outdoor * max(0.0, self.heat_limit_c - outdoor_c)
        return max(0.0, self.standby_kw + base + self.kw_per_k_shift * shift_eff)


@dataclass(frozen=True)
class CurveSettings:
    band_low: float = 20.0
    band_high: float = 22.0
    end_target: float | None = None
    actions: tuple[float, ...] = (-6.0, -3.0, 0.0, 2.0, 4.0)
    temp_step: float = 0.1
    shift_step: float = 1.0
    margin: float = 1.0
    violation_penalty: float = 50.0  # cost per K^2 and hour outside the band
    comfort_penalty: float = 0.5  # cost per K^2 and hour away from the target temperature
    switch_penalty: float = 0.05  # cost per K of change between the effective and the chosen shift
    shift_penalty: float = 1e-4  # tie breaker favouring small shifts

    def validate(self) -> None:
        if self.band_low >= self.band_high:
            raise ValueError("band_low must be below band_high")
        if not self.actions:
            raise ValueError("at least one shift action is required")
        if self.temp_step <= 0 or self.shift_step <= 0 or self.margin < 0:
            raise ValueError("temp_step, shift_step must be positive and margin non-negative")
        penalties = (self.violation_penalty, self.comfort_penalty, self.switch_penalty, self.shift_penalty)
        if any(value < 0 for value in penalties):
            raise ValueError("penalties must not be negative")
        if self.end_target is not None and not self.band_low <= self.end_target <= self.band_high:
            raise ValueError("end_target must lie inside the comfort band")

    @property
    def end_target_c(self) -> float:
        if self.end_target is not None:
            return self.end_target
        return (self.band_low + self.band_high) / 2.0

    def violation(self, indoor_c: float) -> float:
        if indoor_c < self.band_low:
            return self.band_low - indoor_c
        if indoor_c > self.band_high:
            return indoor_c - self.band_high
        return 0.0


@dataclass(frozen=True)
class PlannedShift:
    slot: PriceSlot
    shift: float
    shift_effective: float
    indoor_c: float  # predicted at the end of the slot
    outdoor_c: float
    power_kw: float
    cost: float

    @property
    def energy_kwh(self) -> float:
        return self.power_kw * self.slot.minutes / 60.0


@dataclass
class CurvePlan:
    steps: list[PlannedShift]
    baseline: list[PlannedShift]
    settings: CurveSettings

    @property
    def cost(self) -> float:
        return sum(s.cost for s in self.steps)

    @property
    def baseline_cost(self) -> float:
        return sum(s.cost for s in self.baseline)

    @property
    def energy_kwh(self) -> float:
        return sum(s.energy_kwh for s in self.steps)

    @property
    def baseline_energy_kwh(self) -> float:
        return sum(s.energy_kwh for s in self.baseline)

    @property
    def max_violation_k(self) -> float:
        return max((self.settings.violation(s.indoor_c) for s in self.steps), default=0.0)

    @property
    def indoor_range(self) -> tuple[float, float]:
        temps = [s.indoor_c for s in self.steps]
        return (min(temps), max(temps)) if temps else (math.nan, math.nan)


def outdoor_series(slots: list[PriceSlot], outdoor: float | list[float]) -> list[float]:
    if isinstance(outdoor, (int, float)):
        return [float(outdoor)] * len(slots)
    values = [float(v) for v in outdoor]
    if not values:
        raise ValueError("outdoor temperature series is empty")
    if len(values) < len(slots):
        values += [values[-1]] * (len(slots) - len(values))
    return values[: len(slots)]


def rollout(
    slots: list[PriceSlot],
    house: HouseModel,
    power: PowerModel,
    shifts: list[float],
    *,
    indoor_c: float,
    outdoor: list[float],
    shift_effective: float = 0.0,
) -> list[PlannedShift]:
    """Simulate the model under a given shift sequence."""
    steps: list[PlannedShift] = []
    temp = indoor_c
    eff = shift_effective
    for slot, shift, t_out in zip(slots, shifts, outdoor, strict=True):
        eff = house.filter_step(eff, shift, slot.minutes)
        temp = house.step(temp, eff, t_out, slot.minutes)
        kw = power.power_kw(t_out, eff)
        cost = slot.total * kw * slot.minutes / 60.0
        steps.append(PlannedShift(slot, shift, eff, temp, t_out, kw, cost))
    return steps


def plan_curve(
    slots: list[PriceSlot],
    house: HouseModel,
    power: PowerModel,
    settings: CurveSettings,
    *,
    indoor_c: float,
    outdoor_c: float | list[float],
    shift_effective: float = 0.0,
) -> CurvePlan:
    """Dynamic programming over (indoor temperature, effective shift) per slot.

    Minimises electricity cost plus a heavy penalty for leaving the comfort
    band and a mild one for straying from the target temperature. Without the
    latter the cheapest plan is always to sit at the bottom of the band, since
    a cooler room loses less heat; the comfort penalty makes the planner
    deviate from the target only when the price spread pays for it. A small
    switching penalty keeps the shift from dithering between neighbouring
    values just to fine-tune the smoothed effective shift. Heat
    stored in the house at the end of the horizon is valued at the mean price,
    so the plan neither dumps nor hoards heat just because the horizon ends.
    """
    house.validate()
    power.validate()
    settings.validate()
    if not slots:
        raise ValueError("no price slots to plan")
    slots = sorted(slots, key=lambda s: s.start)
    outdoor = outdoor_series(slots, outdoor_c)
    n = len(slots)

    t_lo = settings.band_low - settings.margin
    t_hi = settings.band_high + settings.margin
    t_step = settings.temp_step
    nt = int(round((t_hi - t_lo) / t_step)) + 1
    temps = [t_lo + i * t_step for i in range(nt)]

    actions = sorted(set(settings.actions), key=abs)  # evaluate small shifts first
    u_lo = min(actions)
    u_hi = max(actions)
    u_step = settings.shift_step
    nu = int(round((u_hi - u_lo) / u_step)) + 1
    ueffs = [u_lo + j * u_step for j in range(nu)]

    def t_index(t: float) -> int:
        idx = int((t - t_lo) / t_step + 0.5)
        return 0 if idx < 0 else nt - 1 if idx >= nt else idx

    def u_index(u: float) -> int:
        idx = int((u - u_lo) / u_step + 0.5)
        return 0 if idx < 0 else nu - 1 if idx >= nu else idx

    total_minutes = sum(s.minutes for s in slots)
    mean_price = sum(s.total * s.minutes for s in slots) / total_minutes
    end_target = settings.end_target_c
    stored_heat_value = mean_price * power.kw_per_k_shift / house.b  # cost per K of indoor temperature

    value_next = [[stored_heat_value * (end_target - t)] * nu for t in temps]
    policies: list[list[list[int]]] = []
    band_low, band_high = settings.band_low, settings.band_high
    penalty = settings.violation_penalty
    comfort = settings.comfort_penalty
    switch = settings.switch_penalty
    tie = settings.shift_penalty

    for k in range(n - 1, -1, -1):
        slot = slots[k]
        h = slot.minutes / 60.0
        price = slot.total
        t_out = outdoor[k]
        alpha = h * (house.c + house.d * t_out)
        beta = 1.0 - h * house.a
        gamma = h * house.b
        transitions: list[list[tuple[int, float, float]]] = []
        for u in ueffs:
            row = []
            for a in actions:
                u_next = house.filter_step(u, a, slot.minutes)
                energy_cost = (
                    price * power.power_kw(t_out, u_next) * h + tie * abs(a) * h + switch * abs(a - u)
                )
                row.append((u_index(u_next), energy_cost, alpha + gamma * u_next))
            transitions.append(row)

        value_k = [[0.0] * nu for _ in range(nt)]
        policy_k = [[0] * nu for _ in range(nt)]
        for i, t in enumerate(temps):
            bt = beta * t
            values_i = value_k[i]
            policy_i = policy_k[i]
            for j in range(nu):
                best = INF
                best_a = 0
                for ai, (j_next, energy_cost, base) in enumerate(transitions[j]):
                    t_next = base + bt
                    deviation = t_next - end_target
                    total = (
                        energy_cost
                        + comfort * deviation * deviation * h
                        + value_next[t_index(t_next)][j_next]
                    )
                    if t_next < band_low:
                        gap = band_low - t_next
                        total += penalty * gap * gap * h
                    elif t_next > band_high:
                        gap = t_next - band_high
                        total += penalty * gap * gap * h
                    if total < best:
                        best = total
                        best_a = ai
                values_i[j] = best
                policy_i[j] = best_a
        value_next = value_k
        policies.append(policy_k)
    policies.reverse()

    shifts: list[float] = []
    temp = indoor_c
    eff = shift_effective
    for k, slot in enumerate(slots):
        action = actions[policies[k][t_index(temp)][u_index(eff)]]
        shifts.append(action)
        eff = house.filter_step(eff, action, slot.minutes)
        temp = house.step(temp, eff, outdoor[k], slot.minutes)

    steps = rollout(
        slots, house, power, shifts, indoor_c=indoor_c, outdoor=outdoor, shift_effective=shift_effective
    )
    baseline = rollout(
        slots, house, power, [0.0] * n, indoor_c=indoor_c, outdoor=outdoor, shift_effective=shift_effective
    )
    return CurvePlan(steps=steps, baseline=baseline, settings=settings)


def merge_slots(slots: list[PriceSlot], minutes: int) -> list[PriceSlot]:
    """Aggregate consecutive slots into ``minutes``-long slots (price weighted by duration)."""
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    merged: list[PriceSlot] = []
    group: list[PriceSlot] = []

    def flush() -> None:
        if not group:
            return
        total_minutes = sum(s.minutes for s in group)
        price = sum(s.total * s.minutes for s in group) / total_minutes
        merged.append(
            PriceSlot(
                start=group[0].start,
                end=group[-1].end,
                total=price,
                level=group[0].level,
                currency=group[0].currency,
            )
        )
        group.clear()

    for slot in sorted(slots, key=lambda s: s.start):
        if group and (slot.start != group[-1].end or sum(s.minutes for s in group) + slot.minutes > minutes):
            flush()
        group.append(slot)
        if sum(s.minutes for s in group) >= minutes:
            flush()
    flush()
    return merged


@dataclass(frozen=True)
class ShiftRun:
    start: object
    end: object
    shift: float
    minutes: float
    indoor_start_c: float
    indoor_end_c: float
    avg_price: float
    energy_kwh: float
    cost: float


def shift_runs(plan: CurvePlan, *, indoor_start_c: float) -> list[ShiftRun]:
    runs: list[ShiftRun] = []
    group: list[PlannedShift] = []
    start_temp = indoor_start_c

    def flush() -> None:
        nonlocal start_temp
        if not group:
            return
        minutes = sum(s.slot.minutes for s in group)
        runs.append(
            ShiftRun(
                start=group[0].slot.start,
                end=group[-1].slot.end,
                shift=group[0].shift,
                minutes=minutes,
                indoor_start_c=start_temp,
                indoor_end_c=group[-1].indoor_c,
                avg_price=sum(s.slot.total * s.slot.minutes for s in group) / minutes,
                energy_kwh=sum(s.energy_kwh for s in group),
                cost=sum(s.cost for s in group),
            )
        )
        start_temp = group[-1].indoor_c
        group.clear()

    for step in plan.steps:
        if group and (step.shift != group[-1].shift or step.slot.start != group[-1].slot.end):
            flush()
        group.append(step)
    flush()
    return runs


__all__ = [
    "CurvePlan",
    "CurveSettings",
    "HouseModel",
    "PlannedShift",
    "PowerModel",
    "ShiftRun",
    "merge_slots",
    "outdoor_series",
    "plan_curve",
    "rollout",
    "shift_runs",
]


@dataclass(frozen=True)
class CyclingModel:
    """Compressor starts per hour for an on/off heat pump behind a buffer tank.

    The WPM runs the buffer on its return sensor with a hysteresis band, so the
    compressor fills the buffer at full output and then waits while the house
    draws it down. With ``capacity_kw`` of output, ``buffer_kwh`` of usable
    storage between the switching points and a house demand of ``demand_kw``:

        on  = buffer_kwh / (capacity_kw - demand_kw)
        off = buffer_kwh / demand_kw
        starts/h = 1 / (on + off) = demand*(capacity-demand) / (buffer*capacity)

    The consequence that matters for planning: **cycling is worst at half
    load**, peaking at ``capacity / (4 * buffer)``, and falls to zero at both
    ends. A controller that pushes the pump towards either off or near-capacity
    therefore *reduces* starts, which is the same thing price-blocking wants.
    Cost and compressor wear are not in tension here as long as the plan is
    built from long blocks rather than per-slot wiggles.

    ``min_off_minutes`` is the WPM's own standstill timer (``RESTSTILLSTAND``),
    which caps the rate no matter what the demand is.
    """

    capacity_kw: float = 6.0
    buffer_kwh: float = 0.5
    min_off_minutes: float = 20.0

    def validate(self) -> None:
        if self.capacity_kw <= 0:
            raise ValueError("capacity_kw must be positive")
        if self.buffer_kwh <= 0:
            raise ValueError("buffer_kwh must be positive")
        if self.min_off_minutes < 0:
            raise ValueError("min_off_minutes must not be negative")

    def starts_per_hour(self, demand_kw: float) -> float:
        if demand_kw <= 0.0 or demand_kw >= self.capacity_kw:
            return 0.0
        on_h = self.buffer_kwh / (self.capacity_kw - demand_kw)
        off_h = max(self.buffer_kwh / demand_kw, self.min_off_minutes / 60.0)
        return 1.0 / (on_h + off_h)

    @property
    def worst_demand_kw(self) -> float:
        """Demand at which the pump cycles hardest."""
        return self.capacity_kw / 2.0

    @property
    def worst_starts_per_hour(self) -> float:
        return self.starts_per_hour(self.worst_demand_kw)

    def duty(self, demand_kw: float) -> float:
        """Fraction of the time the compressor runs."""
        if demand_kw <= 0.0:
            return 0.0
        return min(1.0, demand_kw / self.capacity_kw)
