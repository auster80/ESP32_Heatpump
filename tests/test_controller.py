from __future__ import annotations

import json
import unittest
from datetime import timedelta

from tibber_heatpump_bridge.backends.base import BackendError
from tibber_heatpump_bridge.backends.dryrun import DryRunBackend
from tibber_heatpump_bridge.config import OutdoorConfig, parse_config
from tibber_heatpump_bridge.controller import Controller
from tibber_heatpump_bridge.outdoor import extract_path, fetch_outdoor_temperature
from tibber_heatpump_bridge.schedule import Mode
from tibber_heatpump_bridge.tibber import TibberClient

from .helpers import day_start, tibber_document, tibber_entries

# Hourly prices with a clear expensive peak at 08:00 and cheap night.
PRICES = [0.2] * 6 + [0.9, 2.0, 2.5, 1.0] + [0.5] * 14


class ScriptedTransport:
    """Returns the queued documents in order; the last one repeats. Strings raise."""

    def __init__(self, *documents) -> None:
        self.documents = list(documents)
        self.calls = 0

    def __call__(self, url, headers, body, timeout):
        self.calls += 1
        current = self.documents[0] if len(self.documents) == 1 else self.documents.pop(0)
        if isinstance(current, Exception):
            raise current
        return json.dumps(current).encode()


class FailingBackend(DryRunBackend):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    def apply(self, mode: Mode) -> None:
        if self.fail:
            raise BackendError("relay unreachable")
        super().apply(mode)


def make_controller(transport, backend=None, **schedule):
    cfg = parse_config(
        {
            "tibber": {"token": "t", "resolution": "HOURLY"},
            "schedule": {
                "max_block_minutes": 240,
                "min_gap_after_block_minutes": 0,
                "max_block_minutes_per_day": 1440,
                **schedule,
            },
            "run": {"reapply_minutes": 15, "refresh_minutes": 30, "retry_minutes": 10, "stale_plan_hours": 6},
        },
        env={},
    )
    backend = backend or DryRunBackend()
    return Controller(cfg, TibberClient("t", transport=transport), backend), backend


def document(prices=PRICES, offset_days=0):
    start = day_start() + timedelta(days=offset_days)
    return tibber_document(tibber_entries(prices, start=start, minutes=60))


class ControllerTests(unittest.TestCase):
    def test_first_tick_fetches_and_applies(self):
        ctl, backend = make_controller(ScriptedTransport(document()))
        now = day_start() + timedelta(hours=8, minutes=10)
        mode, applied = ctl.tick(now)
        self.assertEqual(mode, Mode.BLOCK)
        self.assertTrue(applied)
        self.assertEqual(backend.applied, [Mode.BLOCK])

    def test_unchanged_mode_is_reapplied_only_after_interval(self):
        ctl, backend = make_controller(ScriptedTransport(document()))
        now = day_start() + timedelta(hours=8)
        ctl.tick(now)
        _, applied = ctl.tick(now + timedelta(minutes=5))
        self.assertFalse(applied)
        _, applied = ctl.tick(now + timedelta(minutes=15))
        self.assertTrue(applied)
        self.assertEqual(backend.applied, [Mode.BLOCK, Mode.BLOCK])

    def test_mode_change_at_slot_boundary_applies_immediately(self):
        ctl, backend = make_controller(ScriptedTransport(document()))
        ctl.tick(day_start() + timedelta(hours=8, minutes=59))
        mode, applied = ctl.tick(day_start() + timedelta(hours=9))
        self.assertTrue(applied)
        self.assertNotEqual(mode, Mode.BLOCK)

    def test_no_plan_is_fail_safe_normal(self):
        ctl, backend = make_controller(ScriptedTransport(OSError("network down")))
        mode, applied = ctl.tick(day_start() + timedelta(hours=8))
        self.assertEqual(mode, Mode.NORMAL)
        self.assertTrue(applied)
        self.assertEqual(backend.applied, [Mode.NORMAL])

    def test_stale_plan_falls_back_to_normal(self):
        transport = ScriptedTransport(document(), OSError("down"))
        ctl, backend = make_controller(transport)
        start = day_start() + timedelta(hours=8)
        self.assertEqual(ctl.tick(start)[0], Mode.BLOCK)
        # Every later refresh fails; after stale_plan_hours the plan is dropped.
        mode, _ = ctl.tick(start + timedelta(hours=7))
        self.assertEqual(mode, Mode.NORMAL)
        self.assertEqual(backend.applied[-1], Mode.NORMAL)

    def test_failed_refresh_keeps_previous_plan(self):
        transport = ScriptedTransport(document(), OSError("down"))
        ctl, _ = make_controller(transport)
        start = day_start() + timedelta(hours=8)
        ctl.tick(start)
        mode, _ = ctl.tick(start + timedelta(minutes=45))  # refresh due, fails
        self.assertEqual(mode, Mode.BLOCK)
        self.assertEqual(transport.calls, 2)

    def test_retry_interval_after_failed_fetch(self):
        transport = ScriptedTransport(OSError("down"), OSError("down"), document())
        ctl, _ = make_controller(transport)
        start = day_start() + timedelta(hours=8)
        ctl.tick(start)
        ctl.tick(start + timedelta(minutes=2))  # not retried yet
        self.assertEqual(transport.calls, 1)
        ctl.tick(start + timedelta(minutes=10))  # retried, still failing
        self.assertEqual(transport.calls, 2)
        mode, _ = ctl.tick(start + timedelta(minutes=20))
        self.assertEqual(transport.calls, 3)
        self.assertEqual(mode, Mode.BLOCK)

    def test_polls_for_tomorrow_when_horizon_is_short(self):
        transport = ScriptedTransport(document())
        ctl, _ = make_controller(transport)
        ctl.tick(day_start() + timedelta(hours=22))
        self.assertEqual(transport.calls, 1)
        ctl.tick(day_start() + timedelta(hours=22, minutes=5))
        self.assertEqual(transport.calls, 1)
        ctl.tick(day_start() + timedelta(hours=22, minutes=10))
        self.assertEqual(transport.calls, 2)

    def test_backend_failure_is_retried_next_tick(self):
        backend = FailingBackend()
        ctl, _ = make_controller(ScriptedTransport(document()), backend=backend)
        now = day_start() + timedelta(hours=8)
        with self.assertRaises(BackendError):
            ctl.tick(now)
        backend.fail = False
        _, applied = ctl.tick(now + timedelta(minutes=1))
        self.assertTrue(applied)
        self.assertEqual(backend.applied, [Mode.BLOCK])

    def test_outdoor_temperature_feeds_plan(self):
        ctl, _ = make_controller(ScriptedTransport(document()), never_block_below_outdoor_c=-5)
        ctl.temperature_fetcher = lambda: -10.0
        mode, _ = ctl.tick(day_start() + timedelta(hours=8))
        self.assertEqual(mode, Mode.REDUCE)
        self.assertEqual(ctl.outdoor_temp_c, -10.0)

    def test_next_wakeup_uses_slot_boundary(self):
        ctl, _ = make_controller(ScriptedTransport(document()))
        now = day_start() + timedelta(hours=8, minutes=59, seconds=30)
        ctl.tick(now)
        self.assertEqual(ctl.next_wakeup(now), day_start() + timedelta(hours=9, seconds=1))
        early = day_start() + timedelta(hours=8)
        self.assertEqual(ctl.next_wakeup(early), early + timedelta(seconds=60))

    def test_release_sets_normal(self):
        ctl, backend = make_controller(ScriptedTransport(document()))
        ctl.tick(day_start() + timedelta(hours=8))
        ctl.release()
        self.assertEqual(backend.applied[-1], Mode.NORMAL)


class OutdoorTests(unittest.TestCase):
    def test_extract_path(self):
        doc = {"tmp": {"tC": 3.5}, "list": [{"v": 1}, {"v": 2}]}
        self.assertEqual(extract_path(doc, "tmp.tC"), 3.5)
        self.assertEqual(extract_path(doc, "list.1.v"), 2)
        self.assertEqual(extract_path(7, ""), 7)

    def test_fetch_parses_and_tolerates_errors(self):
        cfg = OutdoorConfig(url="http://x", json_path="state")

        def ok(url, method, body, headers, timeout):
            return 200, b'{"state": "-3.2"}'

        def bad_json(url, method, body, headers, timeout):
            return 200, b"nope"

        def failing(url, method, body, headers, timeout):
            raise BackendError("unreachable")

        self.assertEqual(fetch_outdoor_temperature(cfg, sender=ok), -3.2)
        self.assertIsNone(fetch_outdoor_temperature(cfg, sender=bad_json))
        self.assertIsNone(fetch_outdoor_temperature(cfg, sender=failing))


if __name__ == "__main__":
    unittest.main()
