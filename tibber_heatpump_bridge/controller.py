"""Ties prices, plan and backend together with fail-safe behaviour.

Whenever there is no usable plan (Tibber unreachable for longer than
``stale_plan_hours``, no slot covering the current time, ...), the controller
falls back to ``normal`` so the heat pump is never left blocked by accident.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .backends.base import Backend
from .config import AppConfig
from .outdoor import TemperatureFetcher
from .schedule import Mode, PlannedSlot, build_plan, mode_at
from .tibber import PriceData, TibberClient, TibberError

log = logging.getLogger(__name__)


class Controller:
    def __init__(
        self,
        cfg: AppConfig,
        client: TibberClient,
        backend: Backend,
        *,
        temperature_fetcher: TemperatureFetcher | None = None,
    ) -> None:
        self.cfg = cfg
        self.client = client
        self.backend = backend
        self.temperature_fetcher = temperature_fetcher
        self.prices: PriceData | None = None
        self.plan: list[PlannedSlot] = []
        self.plan_built_at: datetime | None = None
        self.last_refresh_attempt: datetime | None = None
        self.outdoor_temp_c: float | None = None
        self.tz: ZoneInfo | None = ZoneInfo(cfg.schedule.timezone) if cfg.schedule.timezone else None
        self.last_mode: Mode | None = None
        self.last_apply_at: datetime | None = None

    # --- planning -------------------------------------------------------

    def refresh(self, now: datetime) -> None:
        """Fetch prices and rebuild the plan. Raises :class:`TibberError` on failure."""
        self.last_refresh_attempt = now
        prices = self.client.fetch_prices(
            home_id=self.cfg.tibber.home_id, resolution=self.cfg.tibber.resolution
        )
        tz = self.tz or ZoneInfo(prices.time_zone)
        outdoor = self.temperature_fetcher() if self.temperature_fetcher else None
        plan = build_plan(prices.slots, self.cfg.schedule, tz=tz, outdoor_temp_c=outdoor)
        self.prices = prices
        self.tz = tz
        self.outdoor_temp_c = outdoor
        self.plan = plan
        self.plan_built_at = now
        log.info(
            "plan rebuilt: %d slots until %s%s",
            len(plan),
            plan[-1].slot.end.astimezone(tz).strftime("%Y-%m-%d %H:%M") if plan else "-",
            f", outdoor {outdoor:.1f} C" if outdoor is not None else "",
        )

    def needs_refresh(self, now: datetime) -> bool:
        run = self.cfg.run
        if self.plan_built_at is None or not self.plan:
            attempt = self.last_refresh_attempt
            return attempt is None or now - attempt >= timedelta(minutes=run.retry_minutes)
        age = now - self.plan_built_at
        if age >= timedelta(minutes=run.refresh_minutes):
            return True
        # Tomorrow's prices are published in the afternoon; poll a bit more often
        # while the plan does not yet reach three hours ahead.
        horizon = self.plan[-1].slot.end - now
        since_attempt = now - (self.last_refresh_attempt or self.plan_built_at)
        return horizon < timedelta(hours=3) and since_attempt >= timedelta(minutes=run.retry_minutes)

    def decide(self, now: datetime) -> tuple[Mode, str]:
        if not self.plan or self.plan_built_at is None:
            return Mode.NORMAL, "no price plan available (fail-safe)"
        if now - self.plan_built_at > timedelta(hours=self.cfg.run.stale_plan_hours):
            return Mode.NORMAL, "price plan is stale (fail-safe)"
        planned = mode_at(self.plan, now)
        if planned is None:
            return Mode.NORMAL, "no price slot covers the current time (fail-safe)"
        return planned.mode, planned.reason

    # --- control loop ---------------------------------------------------

    def tick(self, now: datetime | None = None) -> tuple[Mode, bool]:
        """One control step: refresh if due, decide, apply if changed or due.

        Returns the current mode and whether the backend was written to.
        Backend errors propagate so the caller can log them; the mode is
        re-applied on the next tick because ``last_mode`` is not updated.
        """
        now = now or datetime.now(UTC)
        if self.needs_refresh(now):
            try:
                self.refresh(now)
            except (TibberError, ValueError, OSError) as exc:
                self.last_refresh_attempt = now
                log.warning("price refresh failed, keeping previous plan: %s", exc)
        mode, reason = self.decide(now)
        reapply = timedelta(minutes=self.cfg.run.reapply_minutes)
        due = self.last_mode is not mode or self.last_apply_at is None or now - self.last_apply_at >= reapply
        if not due:
            return mode, False
        self.backend.apply(mode)
        if self.last_mode is not mode:
            log.info("heat pump mode -> %s (%s)", mode.value, reason)
        else:
            log.debug("heat pump mode re-applied: %s", mode.value)
        self.last_mode = mode
        self.last_apply_at = now
        return mode, True

    def next_wakeup(self, now: datetime) -> datetime:
        """Wake at the next slot boundary or after the polling interval, whichever is sooner."""
        interval = timedelta(seconds=self.cfg.run.interval_seconds)
        planned = mode_at(self.plan, now)
        candidate = now + interval
        if planned is not None and now < planned.slot.end < candidate:
            candidate = planned.slot.end + timedelta(seconds=1)
        return candidate

    def release(self) -> None:
        """Return the heat pump to normal operation (used on shutdown)."""
        if not self.cfg.run.release_on_exit:
            return
        try:
            self.backend.apply(Mode.NORMAL)
            log.info("heat pump mode -> normal (bridge stopping)")
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise
            log.error("could not release heat pump to normal on exit: %s", exc)
