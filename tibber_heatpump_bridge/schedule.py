"""Turn price slots into a per-slot heat pump mode plan.

Two classification strategies:

* ``percentile`` ranks every slot within its local calendar day. The cheapest
  share becomes ``force``/``boost``, the most expensive share ``block``/``reduce``.
* ``tibber_level`` maps Tibber's own price level (relative to a trailing
  three-day average) straight to a mode.

Afterwards comfort constraints only ever move a slot towards more comfort:
comfort windows, an outdoor-temperature guard, a maximum block run length with
a recovery gap, and a daily block budget.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from .tibber import PRICE_LEVELS, PriceSlot

log = logging.getLogger(__name__)


class Mode(StrEnum):
    """Heat pump demand mode, ordered from least to most heat production."""

    BLOCK = "block"  # pause compressor (SG Ready state 1 / EVU lock)
    REDUCE = "reduce"  # lower heating curve / hot water target
    NORMAL = "normal"  # untouched
    BOOST = "boost"  # raise heating curve / hot water target
    FORCE = "force"  # maximum demand (SG Ready state 4)

    @classmethod
    def parse(cls, value: object) -> Mode:
        if isinstance(value, Mode):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            names = [m.value for m in cls]
            raise ValueError(f"unknown mode {value!r}; expected one of {names}") from None


MODE_ORDER: tuple[Mode, ...] = (Mode.BLOCK, Mode.REDUCE, Mode.NORMAL, Mode.BOOST, Mode.FORCE)
STRATEGIES = ("percentile", "tibber_level")
DEFAULT_LEVEL_MODES: dict[str, Mode] = {
    "VERY_CHEAP": Mode.FORCE,
    "CHEAP": Mode.BOOST,
    "NORMAL": Mode.NORMAL,
    "EXPENSIVE": Mode.REDUCE,
    "VERY_EXPENSIVE": Mode.BLOCK,
}


@dataclass(frozen=True)
class TimeWindow:
    """Daily local-time window ``start <= t < end``; wraps past midnight if start > end."""

    start: time
    end: time

    @classmethod
    def parse(cls, text: str) -> TimeWindow:
        try:
            start_text, end_text = text.split("-", 1)
            return cls(time.fromisoformat(start_text.strip()), time.fromisoformat(end_text.strip()))
        except ValueError:
            raise ValueError(f"invalid time window {text!r}; expected HH:MM-HH:MM") from None

    def contains(self, moment: time) -> bool:
        if self.start == self.end:
            return True
        if self.start < self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end

    def __str__(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


@dataclass
class ScheduleConfig:
    strategy: str = "percentile"
    force_share: float = 0.0
    boost_share: float = 0.25
    reduce_share: float = 0.25
    block_share: float = 0.10
    force_below_price: float | None = 0.0
    block_only_above_price: float | None = None
    level_modes: dict[str, Mode] = field(default_factory=lambda: dict(DEFAULT_LEVEL_MODES))
    max_block_minutes: int = 120
    min_gap_after_block_minutes: int = 60
    max_block_minutes_per_day: int = 360
    comfort_windows: list[TimeWindow] = field(default_factory=list)
    never_block_below_outdoor_c: float | None = None
    timezone: str | None = None

    def validate(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {STRATEGIES}, got {self.strategy!r}")
        shares = {
            "force_share": self.force_share,
            "boost_share": self.boost_share,
            "reduce_share": self.reduce_share,
            "block_share": self.block_share,
        }
        for name, value in shares.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {value}")
        if sum(shares.values()) > 1.0 + 1e-9:
            raise ValueError("force/boost/reduce/block shares add up to more than 1")
        for name in ("max_block_minutes", "min_gap_after_block_minutes", "max_block_minutes_per_day"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        for level, mode in self.level_modes.items():
            if level not in PRICE_LEVELS:
                raise ValueError(f"unknown Tibber price level {level!r} in level_modes")
            if not isinstance(mode, Mode):
                raise ValueError(f"level_modes[{level!r}] must be a Mode")
        if self.timezone:
            ZoneInfo(self.timezone)  # raises for unknown zones


@dataclass(frozen=True)
class PlannedSlot:
    slot: PriceSlot
    mode: Mode
    reason: str

    def with_mode(self, mode: Mode, reason: str) -> PlannedSlot:
        return PlannedSlot(self.slot, mode, reason)


def build_plan(
    slots: list[PriceSlot],
    cfg: ScheduleConfig,
    *,
    tz: ZoneInfo,
    outdoor_temp_c: float | None = None,
) -> list[PlannedSlot]:
    cfg.validate()
    ordered = sorted(slots, key=lambda s: s.start)
    if cfg.strategy == "tibber_level":
        plan = _classify_by_level(ordered, cfg)
    else:
        plan = _classify_by_percentile(ordered, cfg, tz)
    plan = _apply_price_overrides(plan, cfg)
    plan = _apply_comfort_windows(plan, cfg, tz)
    plan = _apply_outdoor_guard(plan, cfg, outdoor_temp_c)
    plan = _limit_block_runs(plan, cfg)
    plan = _limit_daily_block_budget(plan, cfg, tz)
    return plan


def mode_at(plan: list[PlannedSlot], when: datetime) -> PlannedSlot | None:
    return next((p for p in plan if p.slot.contains(when)), None)


@dataclass(frozen=True)
class Run:
    """Consecutive slots sharing one mode, for compact display."""

    start: datetime
    end: datetime
    mode: Mode
    minutes: float
    avg_price: float


def runs(plan: list[PlannedSlot]) -> list[Run]:
    result: list[Run] = []
    current: list[PlannedSlot] = []

    def flush() -> None:
        if not current:
            return
        minutes = sum(p.slot.minutes for p in current)
        weighted = sum(p.slot.total * p.slot.minutes for p in current)
        result.append(
            Run(
                start=current[0].slot.start,
                end=current[-1].slot.end,
                mode=current[0].mode,
                minutes=minutes,
                avg_price=weighted / minutes if minutes else 0.0,
            )
        )
        current.clear()

    for planned in plan:
        if current and (planned.mode is not current[-1].mode or planned.slot.start != current[-1].slot.end):
            flush()
        current.append(planned)
    flush()
    return result


def summarize(plan: list[PlannedSlot]) -> dict[Mode, dict[str, float]]:
    summary = {mode: {"count": 0, "minutes": 0.0, "avg_price": 0.0} for mode in MODE_ORDER}
    weighted = {mode: 0.0 for mode in MODE_ORDER}
    for planned in plan:
        entry = summary[planned.mode]
        entry["count"] += 1
        entry["minutes"] += planned.slot.minutes
        weighted[planned.mode] += planned.slot.total * planned.slot.minutes
    for mode, entry in summary.items():
        if entry["minutes"]:
            entry["avg_price"] = weighted[mode] / entry["minutes"]
    return summary


# --- classification -------------------------------------------------------


def _local_day(slot: PriceSlot, tz: ZoneInfo) -> date:
    return slot.start.astimezone(tz).date()


def _classify_by_percentile(slots: list[PriceSlot], cfg: ScheduleConfig, tz: ZoneInfo) -> list[PlannedSlot]:
    by_day: dict[date, list[PriceSlot]] = defaultdict(list)
    for slot in slots:
        by_day[_local_day(slot, tz)].append(slot)

    assigned: dict[PriceSlot, tuple[Mode, str]] = {}
    for day, group in by_day.items():
        ranked = sorted(group, key=lambda s: (s.total, s.start))
        n = len(ranked)
        k_force = min(n, round(n * cfg.force_share))
        cheap_n = min(n, k_force + round(n * cfg.boost_share))
        k_boost = cheap_n - k_force
        k_block = min(n - cheap_n, round(n * cfg.block_share))
        expensive_n = min(n - cheap_n, k_block + round(n * cfg.reduce_share))
        k_reduce = expensive_n - k_block
        for index, slot in enumerate(ranked):
            if index < k_force:
                mode = Mode.FORCE
            elif index < k_force + k_boost:
                mode = Mode.BOOST
            elif index >= n - k_block:
                mode = Mode.BLOCK
            elif index >= n - k_block - k_reduce:
                mode = Mode.REDUCE
            else:
                mode = Mode.NORMAL
            assigned[slot] = (mode, f"price rank {index + 1}/{n} on {day.isoformat()}")
    return [PlannedSlot(slot, *assigned[slot]) for slot in slots]


def _classify_by_level(slots: list[PriceSlot], cfg: ScheduleConfig) -> list[PlannedSlot]:
    return [
        PlannedSlot(
            slot,
            cfg.level_modes.get(slot.level, Mode.NORMAL),
            f"Tibber level {slot.level}",
        )
        for slot in slots
    ]


# --- constraints (each only ever moves a slot towards more comfort) -------


def _apply_price_overrides(plan: list[PlannedSlot], cfg: ScheduleConfig) -> list[PlannedSlot]:
    out: list[PlannedSlot] = []
    for planned in plan:
        price = planned.slot.total
        if cfg.force_below_price is not None and price <= cfg.force_below_price:
            planned = planned.with_mode(Mode.FORCE, f"price {price:.4f} at or below {cfg.force_below_price}")
        elif (
            cfg.block_only_above_price is not None
            and planned.mode is Mode.BLOCK
            and price <= cfg.block_only_above_price
        ):
            planned = planned.with_mode(Mode.REDUCE, f"price {price:.4f} not above block threshold")
        out.append(planned)
    return out


def _apply_comfort_windows(plan: list[PlannedSlot], cfg: ScheduleConfig, tz: ZoneInfo) -> list[PlannedSlot]:
    if not cfg.comfort_windows:
        return plan
    out: list[PlannedSlot] = []
    for planned in plan:
        local = planned.slot.start.astimezone(tz).time()
        window = next((w for w in cfg.comfort_windows if w.contains(local)), None)
        if window is not None and planned.mode in (Mode.BLOCK, Mode.REDUCE):
            planned = planned.with_mode(Mode.NORMAL, f"comfort window {window}")
        out.append(planned)
    return out


def _apply_outdoor_guard(
    plan: list[PlannedSlot], cfg: ScheduleConfig, outdoor_temp_c: float | None
) -> list[PlannedSlot]:
    threshold = cfg.never_block_below_outdoor_c
    if threshold is None or outdoor_temp_c is None or outdoor_temp_c >= threshold:
        return plan
    reason = f"outdoor {outdoor_temp_c:.1f} C below {threshold:.1f} C, block disabled"
    return [p.with_mode(Mode.REDUCE, reason) if p.mode is Mode.BLOCK else p for p in plan]


def _limit_block_runs(plan: list[PlannedSlot], cfg: ScheduleConfig) -> list[PlannedSlot]:
    """Cap consecutive block time and enforce a recovery gap after each block run."""
    out: list[PlannedSlot] = []
    run_minutes = 0.0
    gap_remaining = 0.0
    for planned in plan:
        minutes = planned.slot.minutes
        if (
            planned.mode is Mode.BLOCK
            and gap_remaining <= 0
            and run_minutes + minutes <= cfg.max_block_minutes
        ):
            run_minutes += minutes
            out.append(planned)
            continue
        if planned.mode is Mode.BLOCK:
            if gap_remaining > 0:
                reason = f"recovery gap after block ({cfg.min_gap_after_block_minutes} min)"
            else:
                reason = f"max block run {cfg.max_block_minutes} min reached"
            planned = planned.with_mode(Mode.REDUCE, reason)
        if run_minutes > 0:
            gap_remaining = float(cfg.min_gap_after_block_minutes)
        run_minutes = 0.0
        gap_remaining = max(0.0, gap_remaining - minutes)
        out.append(planned)
    return out


def _limit_daily_block_budget(
    plan: list[PlannedSlot], cfg: ScheduleConfig, tz: ZoneInfo
) -> list[PlannedSlot]:
    out = list(plan)
    by_day: dict[date, list[int]] = defaultdict(list)
    for index, planned in enumerate(out):
        by_day[_local_day(planned.slot, tz)].append(index)
    for day, indices in by_day.items():
        block_indices = [i for i in indices if out[i].mode is Mode.BLOCK]
        total = sum(out[i].slot.minutes for i in block_indices)
        if total <= cfg.max_block_minutes_per_day:
            continue
        # Give up the cheapest blocked slots first; keep blocking the priciest ones.
        for i in sorted(block_indices, key=lambda i: (out[i].slot.total, out[i].slot.start)):
            if total <= cfg.max_block_minutes_per_day:
                break
            out[i] = out[i].with_mode(
                Mode.REDUCE, f"daily block budget {cfg.max_block_minutes_per_day} min used"
            )
            total -= out[i].slot.minutes
        log.debug("%s: block budget trimmed to %.0f min", day, total)
    return out
