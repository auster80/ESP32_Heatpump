"""Command line interface: ``plan``, ``once``, ``run`` and ``check``."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from . import __version__
from .backends import DryRunBackend, build_backend
from .backends.base import Backend, BackendError
from .config import AppConfig, ConfigError, load_config
from .controller import Controller
from .curve import CurvePlan, merge_slots, plan_curve, shift_runs
from .learning import LearningError, fit_house_model, fit_power_model, read_observations_csv
from .outdoor import make_fetcher
from .schedule import MODE_ORDER, runs, summarize
from .sensors import emulate, fake_temperature, resolution_k
from .tibber import PriceSlot, TibberClient, TibberError

log = logging.getLogger("tibber_heatpump_bridge")

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_TIBBER = 3
EXIT_BACKEND = 4


def _fmt_minutes(minutes: float) -> str:
    total = int(round(minutes))
    hours, rest = divmod(total, 60)
    return f"{hours}h{rest:02d}" if hours else f"{rest}m"


def _make_backend(cfg: AppConfig, dry_run: bool) -> Backend:
    if dry_run:
        return DryRunBackend()
    return build_backend(cfg.backend.type, cfg.backend.options)


def _controller(cfg: AppConfig, backend: Backend) -> Controller:
    client = TibberClient(cfg.tibber.token)
    return Controller(cfg, client, backend, temperature_fetcher=make_fetcher(cfg.outdoor))


def _print_plan(ctl: Controller, now: datetime, *, every_slot: bool, out=sys.stdout) -> None:
    assert ctl.prices is not None and ctl.tz is not None
    tz = ctl.tz
    currency = ctl.prices.currency or ""
    print(
        f"home {ctl.prices.home_id}  tz {tz.key}  strategy {ctl.cfg.schedule.strategy}"
        f"  resolution {ctl.cfg.tibber.resolution}"
        + (f"  outdoor {ctl.outdoor_temp_c:.1f} C" if ctl.outdoor_temp_c is not None else ""),
        file=out,
    )
    if every_slot:
        current_day = None
        for planned in ctl.plan:
            start = planned.slot.start.astimezone(tz)
            if start.date() != current_day:
                current_day = start.date()
                print(f"\n{current_day.isoformat()}", file=out)
            marker = "*" if planned.slot.contains(now) else " "
            end = planned.slot.end.astimezone(tz)
            print(
                f"{marker} {start:%H:%M}-{end:%H:%M}  {planned.slot.total:8.4f}"
                f"  {planned.slot.level:<14} {planned.mode.value:<7} {planned.reason}",
                file=out,
            )
    else:
        print(file=out)
        for run in runs(ctl.plan):
            marker = "*" if run.start <= now < run.end else " "
            print(
                f"{marker} {run.start.astimezone(tz):%a %H:%M} - {run.end.astimezone(tz):%a %H:%M}"
                f"  {run.mode.value:<7} {_fmt_minutes(run.minutes):>6}  avg {run.avg_price:.4f} {currency}",
                file=out,
            )
    summary = summarize(ctl.plan)
    parts = []
    for mode in MODE_ORDER:
        entry = summary[mode]
        if entry["minutes"]:
            parts.append(f"{mode.value} {_fmt_minutes(entry['minutes'])} (avg {entry['avg_price']:.4f})")
    print("\nsummary: " + " | ".join(parts), file=out)
    mode, reason = ctl.decide(now)
    print(f"now {now.astimezone(tz):%Y-%m-%d %H:%M}: {mode.value} ({reason})", file=out)


def cmd_plan(cfg: AppConfig, args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    ctl = _controller(cfg, DryRunBackend())
    if args.outdoor_temp is not None:
        ctl.temperature_fetcher = lambda: args.outdoor_temp
    ctl.refresh(now)
    _print_plan(ctl, now, every_slot=args.slots)
    return EXIT_OK


def cmd_once(cfg: AppConfig, args: argparse.Namespace) -> int:
    backend = _make_backend(cfg, args.dry_run)
    ctl = _controller(cfg, backend)
    try:
        now = datetime.now(UTC)
        ctl.refresh(now)
        mode, _ = ctl.tick(now)
        print(f"applied {mode.value} via {backend.describe()}")
        return EXIT_OK
    finally:
        backend.close()


def cmd_check(cfg: AppConfig, args: argparse.Namespace) -> int:
    backend = _make_backend(cfg, False)
    print(f"backend: {backend.describe()}")
    try:
        backend.check()
        print("backend: reachable")
    except BackendError as exc:
        print(f"backend: FAILED ({exc})")
        return EXIT_BACKEND
    finally:
        backend.close()
    client = TibberClient(cfg.tibber.token)
    prices = client.fetch_prices(home_id=cfg.tibber.home_id, resolution=cfg.tibber.resolution)
    last = prices.last_end
    print(
        f"tibber: ok, home {prices.home_id} ({prices.time_zone}), {len(prices.slots)} slots"
        f" until {last.isoformat() if last else '-'}"
    )
    if cfg.outdoor is not None:
        fetcher = make_fetcher(cfg.outdoor)
        temp = fetcher() if fetcher else None
        print(f"outdoor temperature: {temp if temp is not None else 'unavailable'}")
    return EXIT_OK


def cmd_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    backend = _make_backend(cfg, args.dry_run)
    ctl = _controller(cfg, backend)
    stopping = False

    def _stop(signum, _frame) -> None:
        nonlocal stopping
        stopping = True
        log.info("received signal %s, shutting down", signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)

    log.info("tibber-heatpump-bridge %s starting, backend %s", __version__, backend.describe())
    try:
        while not stopping:
            now = datetime.now(UTC)
            try:
                ctl.tick(now)
            except BackendError as exc:
                log.error("backend error (will retry): %s", exc)
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("unexpected error in control loop")
            wake = ctl.next_wakeup(datetime.now(UTC))
            while not stopping and datetime.now(UTC) < wake:
                time.sleep(1)
    finally:
        ctl.release()
        backend.close()
    return EXIT_OK


# --- curve shifting (virtual outdoor sensor) ----------------------------------


def render_curve_plan(
    cfg: AppConfig,
    plan: CurvePlan,
    *,
    tz: ZoneInfo,
    now: datetime,
    indoor_c: float,
    outdoor_c: float,
    currency: str = "",
    every_slot: bool = False,
) -> str:
    curve = cfg.curve
    settings = curve.settings
    lines = [
        f"indoor {indoor_c:.1f} C (band {settings.band_low:.1f}-{settings.band_high:.1f}, "
        f"target {settings.end_target_c:.1f})  outdoor {outdoor_c:.1f} C  "
        f"model a={curve.house.a:.3f} b={curve.house.b:.3f} c={curve.house.c:.3f} "
        f"filter {curve.house.filter_minutes:.0f} min",
        "",
    ]
    if every_slot:
        for step in plan.steps:
            marker = "*" if step.slot.contains(now) else " "
            lines.append(
                f"{marker} {step.slot.start.astimezone(tz):%a %H:%M}  shift {step.shift:+5.1f}"
                f"  eff {step.shift_effective:+5.1f}  indoor {step.indoor_c:5.2f}"
                f"  {step.slot.total:7.4f}  {step.power_kw:5.2f} kW"
            )
    else:
        for run in shift_runs(plan, indoor_start_c=indoor_c):
            marker = "*" if run.start <= now < run.end else " "
            lines.append(
                f"{marker} {run.start.astimezone(tz):%a %H:%M} - {run.end.astimezone(tz):%a %H:%M}"
                f"  shift {run.shift:+5.1f} K  indoor {run.indoor_start_c:.1f} -> {run.indoor_end_c:.1f}"
                f"  avg {run.avg_price:.4f} {currency}  {run.energy_kwh:5.1f} kWh  {run.cost:6.2f}"
            )
    saving = 0.0 if plan.baseline_cost == 0 else (1 - plan.cost / plan.baseline_cost) * 100
    low, high = plan.indoor_range
    lines += [
        "",
        f"planned: {plan.energy_kwh:.1f} kWh, {plan.cost:.2f} {currency}"
        f"   without shifting: {plan.baseline_energy_kwh:.1f} kWh, {plan.baseline_cost:.2f} {currency}"
        f"   saving {saving:.0f}%",
        f"predicted indoor {low:.1f} - {high:.1f} C, worst band violation {plan.max_violation_k:.2f} K",
    ]
    current = next((s for s in plan.steps if s.slot.contains(now)), plan.steps[0])
    present = fake_temperature(outdoor_c, current.shift)
    line = (
        f"now: shift {current.shift:+.1f} K -> present {present:.1f} C to the heat pump"
        f" (real {outdoor_c:.1f} C)"
    )
    if curve.sensor is not None:
        emu = emulate(curve.sensor.sensor, curve.sensor.pot, present)
        step_k = resolution_k(curve.sensor.sensor, curve.sensor.pot, present)
        line += (
            f"; {curve.sensor.kind}: {emu.target_ohms:.0f} ohm -> tap {emu.tap}"
            f" ({emu.achieved_ohms:.0f} ohm = {emu.achieved_c:.2f} C, step {step_k:.2f} K)"
        )
    lines.append(line)
    return "\n".join(lines)


def _planning_slots(slots: list[PriceSlot], cfg: AppConfig, now: datetime) -> list[PriceSlot]:
    merged = merge_slots(slots, cfg.curve.planning_slot_minutes)
    upcoming = [s for s in merged if s.end > now]
    horizon_end = now + timedelta(hours=cfg.curve.horizon_hours)
    return [s for s in upcoming if s.start < horizon_end]


def cmd_curve_plan(cfg: AppConfig, args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    client = TibberClient(cfg.tibber.token)
    prices = client.fetch_prices(home_id=cfg.tibber.home_id, resolution=cfg.tibber.resolution)
    tz = ZoneInfo(cfg.schedule.timezone or prices.time_zone)
    outdoor_c = args.outdoor
    if outdoor_c is None:
        fetcher = make_fetcher(cfg.outdoor)
        outdoor_c = fetcher() if fetcher else None
    if outdoor_c is None:
        print("curve-plan needs --outdoor or an [outdoor_temperature] source", file=sys.stderr)
        return EXIT_CONFIG
    slots = _planning_slots(prices.slots, cfg, now)
    if not slots:
        print("no upcoming price slots to plan", file=sys.stderr)
        return EXIT_TIBBER
    plan = plan_curve(
        slots,
        cfg.curve.house,
        cfg.curve.power,
        cfg.curve.settings,
        indoor_c=args.indoor,
        outdoor_c=outdoor_c,
        shift_effective=args.shift_now,
    )
    print(
        f"home {prices.home_id}  tz {tz.key}  {len(slots)} planning slots of"
        f" {cfg.curve.planning_slot_minutes} min, horizon {cfg.curve.horizon_hours} h"
    )
    print(
        render_curve_plan(
            cfg,
            plan,
            tz=tz,
            now=now,
            indoor_c=args.indoor,
            outdoor_c=outdoor_c,
            currency=prices.currency,
            every_slot=args.slots,
        )
    )
    return EXIT_OK


def cmd_curve_fit(cfg: AppConfig, args: argparse.Namespace) -> int:
    filter_minutes = cfg.curve.house.filter_minutes if args.filter_minutes is None else args.filter_minutes
    try:
        observations = read_observations_csv(args.log)
        house = fit_house_model(
            observations, filter_minutes=filter_minutes, include_outdoor=not args.no_outdoor
        )
    except LearningError as exc:
        print(f"fit error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    model = house.model
    print(f"# {house.report.samples} samples, rmse {house.report.rmse:.3f} K/h")
    print(f"# equilibrium {model.equilibrium_c:.2f} C, time constant {model.time_constant_h:.1f} h")
    for warning in house.report.warnings:
        print(f"# WARNING: {warning}")
    print("[curve.model]")
    print(f"a = {model.a:.5f}")
    print(f"b = {model.b:.5f}")
    print(f"c = {model.c:.5f}")
    print(f"d = {model.d:.5f}")
    print(f"filter_minutes = {filter_minutes:.0f}")
    if any(o.power_kw is not None for o in observations):
        try:
            power = fit_power_model(
                observations, heat_limit_c=cfg.curve.power.heat_limit_c, filter_minutes=filter_minutes
            )
        except LearningError as exc:
            print(f"# power model not fitted: {exc}")
            return EXIT_OK
        print(f"\n# power: {power.report.samples} samples, rmse {power.report.rmse:.3f} kW")
        for warning in power.report.warnings:
            print(f"# WARNING: {warning}")
        print("[curve.power]")
        print(f"kw_per_k_outdoor = {power.model.kw_per_k_outdoor:.5f}")
        print(f"kw_per_k_shift = {power.model.kw_per_k_shift:.5f}")
        print(f"heat_limit_c = {power.model.heat_limit_c:.1f}")
        print(f"standby_kw = {power.model.standby_kw:.4f}")
    return EXIT_OK


COMMANDS: dict[str, Callable[[AppConfig, argparse.Namespace], int]] = {
    "plan": cmd_plan,
    "once": cmd_once,
    "run": cmd_run,
    "check": cmd_check,
    "curve-plan": cmd_curve_plan,
    "curve-fit": cmd_curve_fit,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tibber-heatpump-bridge",
        description="Drive a heat pump from Tibber spot prices (SG Ready, Modbus, MQTT, HTTP).",
    )
    parser.add_argument("-c", "--config", default="config.toml", help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="fetch prices and print the mode plan (no writes)")
    plan.add_argument("--slots", action="store_true", help="print every slot instead of runs")
    plan.add_argument("--outdoor-temp", type=float, help="assume this outdoor temperature (C)")

    once = sub.add_parser("once", help="apply the mode for the current slot once (cron friendly)")
    once.add_argument("--dry-run", action="store_true", help="log instead of writing to the backend")

    run = sub.add_parser("run", help="run continuously (systemd service)")
    run.add_argument("--dry-run", action="store_true", help="log instead of writing to the backend")

    sub.add_parser("check", help="validate config, backend connectivity and the Tibber token")

    curve_plan = sub.add_parser(
        "curve-plan", help="plan heating-curve shifts (virtual outdoor temperature) for the price horizon"
    )
    curve_plan.add_argument("--indoor", type=float, required=True, help="current indoor temperature (C)")
    curve_plan.add_argument("--outdoor", type=float, help="current outdoor temperature (C); default: source")
    curve_plan.add_argument("--shift-now", type=float, default=0.0, help="shift currently in effect (K)")
    curve_plan.add_argument("--slots", action="store_true", help="print every planning slot")

    curve_fit = sub.add_parser("curve-fit", help="fit the house (and power) model from a CSV log")
    curve_fit.add_argument("log", help="CSV with time,indoor_c,outdoor_c,shift[,power_kw]")
    curve_fit.add_argument(
        "--filter-minutes", type=float, help="heat pump outdoor smoothing; default from config"
    )
    curve_fit.add_argument("--no-outdoor", action="store_true", help="drop the residual outdoor term d")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = load_config(args.config)
        return COMMANDS[args.command](cfg, args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except TibberError as exc:
        print(f"tibber error: {exc}", file=sys.stderr)
        return EXIT_TIBBER
    except BackendError as exc:
        print(f"backend error: {exc}", file=sys.stderr)
        return EXIT_BACKEND
    except BrokenPipeError:  # e.g. `plan | head`
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
