"""Command line interface: ``plan``, ``once``, ``run`` and ``check``."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

from . import __version__
from .backends import DryRunBackend, build_backend
from .backends.base import Backend, BackendError
from .config import AppConfig, ConfigError, load_config
from .controller import Controller
from .outdoor import make_fetcher
from .schedule import MODE_ORDER, runs, summarize
from .tibber import TibberClient, TibberError

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


COMMANDS: dict[str, Callable[[AppConfig, argparse.Namespace], int]] = {
    "plan": cmd_plan,
    "once": cmd_once,
    "run": cmd_run,
    "check": cmd_check,
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
