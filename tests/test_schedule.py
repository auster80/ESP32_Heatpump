from __future__ import annotations

import unittest
from datetime import timedelta

from tibber_heatpump_bridge.schedule import (
    Mode,
    ScheduleConfig,
    TimeWindow,
    build_plan,
    mode_at,
    runs,
    summarize,
)

from .helpers import TZ, day_start, make_slots

# 24 hourly prices: cheap at night, expensive morning and evening peaks.
DAY = [
    0.50,
    0.45,
    0.40,
    0.38,
    0.42,
    0.55,  # 00-05
    0.90,
    1.40,
    1.60,
    1.20,
    1.00,
    0.95,  # 06-11
    0.85,
    0.80,
    0.82,
    0.90,
    1.10,
    1.50,  # 12-17
    1.70,
    1.45,
    1.15,
    0.95,
    0.75,
    0.60,  # 18-23
]


def unconstrained(**overrides) -> ScheduleConfig:
    base = dict(
        max_block_minutes=24 * 60,
        min_gap_after_block_minutes=0,
        max_block_minutes_per_day=24 * 60,
        force_below_price=None,
    )
    base.update(overrides)
    return ScheduleConfig(**base)


def modes(plan) -> list[Mode]:
    return [p.mode for p in plan]


class PercentileTests(unittest.TestCase):
    def test_shares_map_to_ranked_slots(self):
        cfg = unconstrained(force_share=0.0, boost_share=0.25, reduce_share=0.25, block_share=0.10)
        plan = build_plan(make_slots(DAY), cfg, tz=TZ)
        counts = {m: modes(plan).count(m) for m in Mode}
        # 24 slots: round(2.4)=2 block, round(6)=6 reduce, 6 boost, rest normal.
        self.assertEqual(counts[Mode.BLOCK], 2)
        self.assertEqual(counts[Mode.REDUCE], 6)
        self.assertEqual(counts[Mode.BOOST], 6)
        self.assertEqual(counts[Mode.FORCE], 0)
        self.assertEqual(counts[Mode.NORMAL], 10)
        # The two most expensive hours are 18:00 (1.70) and 08:00 (1.60).
        self.assertEqual(plan[18].mode, Mode.BLOCK)
        self.assertEqual(plan[8].mode, Mode.BLOCK)
        # Cheapest hour 03:00 boosts.
        self.assertEqual(plan[3].mode, Mode.BOOST)

    def test_force_share_takes_the_very_cheapest(self):
        cfg = unconstrained(force_share=0.1, boost_share=0.2, reduce_share=0.0, block_share=0.0)
        plan = build_plan(make_slots(DAY), cfg, tz=TZ)
        self.assertEqual(plan[3].mode, Mode.FORCE)
        self.assertEqual(plan[2].mode, Mode.FORCE)
        self.assertEqual(modes(plan).count(Mode.FORCE), 2)
        self.assertEqual(modes(plan).count(Mode.BOOST), 5)

    def test_ranking_is_per_local_day(self):
        cheap_day = make_slots([0.1] * 24)
        pricey_day = make_slots([1.0] * 24, start=day_start() + timedelta(days=1))
        cfg = unconstrained(boost_share=0.5, block_share=0.5, reduce_share=0.0)
        plan = build_plan(cheap_day + pricey_day, cfg, tz=TZ)
        first_day = modes(plan[:24])
        second_day = modes(plan[24:])
        # Both days contain both boost and block slots despite very different levels.
        self.assertIn(Mode.BOOST, first_day)
        self.assertIn(Mode.BLOCK, first_day)
        self.assertIn(Mode.BOOST, second_day)
        self.assertIn(Mode.BLOCK, second_day)

    def test_shares_over_one_rejected(self):
        with self.assertRaises(ValueError):
            build_plan(make_slots(DAY), unconstrained(boost_share=0.6, block_share=0.5), tz=TZ)

    def test_shares_are_clamped_when_rounding_overflows(self):
        cfg = unconstrained(force_share=0.5, boost_share=0.5, reduce_share=0.0, block_share=0.0)
        plan = build_plan(make_slots([1.0, 2.0, 3.0]), cfg, tz=TZ)
        self.assertEqual(len(plan), 3)


class LevelStrategyTests(unittest.TestCase):
    def test_tibber_levels_map_to_modes(self):
        slots = make_slots([1.0] * 5)
        levels = ["VERY_CHEAP", "CHEAP", "NORMAL", "EXPENSIVE", "VERY_EXPENSIVE"]
        slots = [
            type(s)(s.start, s.end, s.total, level, s.currency)
            for s, level in zip(slots, levels, strict=True)
        ]
        cfg = unconstrained(strategy="tibber_level")
        plan = build_plan(slots, cfg, tz=TZ)
        self.assertEqual(modes(plan), [Mode.FORCE, Mode.BOOST, Mode.NORMAL, Mode.REDUCE, Mode.BLOCK])
        self.assertEqual(plan[0].reason, "Tibber level VERY_CHEAP")

    def test_custom_level_mapping(self):
        slots = make_slots([1.0])
        slots = [type(slots[0])(slots[0].start, slots[0].end, 1.0, "VERY_EXPENSIVE")]
        cfg = unconstrained(strategy="tibber_level", level_modes={"VERY_EXPENSIVE": Mode.REDUCE})
        self.assertEqual(build_plan(slots, cfg, tz=TZ)[0].mode, Mode.REDUCE)


class PriceOverrideTests(unittest.TestCase):
    def test_negative_price_forces(self):
        prices = list(DAY)
        prices[12] = -0.01
        cfg = unconstrained(force_below_price=0.0)
        plan = build_plan(make_slots(prices), cfg, tz=TZ)
        self.assertEqual(plan[12].mode, Mode.FORCE)
        self.assertIn("at or below", plan[12].reason)

    def test_block_only_above_absolute_price(self):
        cfg = unconstrained(block_share=0.5, reduce_share=0.0, block_only_above_price=10.0)
        plan = build_plan(make_slots(DAY), cfg, tz=TZ)
        self.assertNotIn(Mode.BLOCK, modes(plan))
        self.assertIn(Mode.REDUCE, modes(plan))


class ComfortConstraintTests(unittest.TestCase):
    def test_comfort_window_neutralises_block_and_reduce(self):
        cfg = unconstrained(comfort_windows=[TimeWindow.parse("17:00-21:00")])
        plan = build_plan(make_slots(DAY), cfg, tz=TZ)
        for hour in range(17, 21):
            self.assertEqual(plan[hour].mode, Mode.NORMAL, hour)
            self.assertIn("comfort window", plan[hour].reason)
        self.assertEqual(plan[8].mode, Mode.BLOCK)  # outside the window

    def test_overnight_window_wraps_midnight(self):
        window = TimeWindow.parse("22:00-06:00")
        self.assertTrue(window.contains(TimeWindow.parse("23:00-00:00").start))
        self.assertTrue(window.contains(TimeWindow.parse("05:59-00:00").start))
        self.assertFalse(window.contains(TimeWindow.parse("06:00-00:00").start))
        self.assertFalse(window.contains(TimeWindow.parse("12:00-00:00").start))

    def test_invalid_window_text(self):
        with self.assertRaises(ValueError):
            TimeWindow.parse("6-8")

    def test_outdoor_guard_downgrades_block(self):
        cfg = unconstrained(never_block_below_outdoor_c=-5.0)
        cold = build_plan(make_slots(DAY), cfg, tz=TZ, outdoor_temp_c=-7.0)
        mild = build_plan(make_slots(DAY), cfg, tz=TZ, outdoor_temp_c=3.0)
        self.assertNotIn(Mode.BLOCK, modes(cold))
        self.assertEqual(cold[18].mode, Mode.REDUCE)
        self.assertIn(Mode.BLOCK, modes(mild))

    def test_outdoor_guard_ignored_without_temperature(self):
        cfg = unconstrained(never_block_below_outdoor_c=-5.0)
        plan = build_plan(make_slots(DAY), cfg, tz=TZ, outdoor_temp_c=None)
        self.assertIn(Mode.BLOCK, modes(plan))


class BlockRunTests(unittest.TestCase):
    def test_max_block_run_and_recovery_gap(self):
        # Six expensive hours in a row 08:00-13:59 would all be blocked.
        prices = [0.1] * 8 + [5.0] * 6 + [0.1] * 10
        cfg = unconstrained(
            block_share=0.25, reduce_share=0.0, max_block_minutes=120, min_gap_after_block_minutes=60
        )
        plan = build_plan(make_slots(prices), cfg, tz=TZ)
        self.assertEqual(
            modes(plan)[8:14],
            [
                Mode.BLOCK,
                Mode.BLOCK,  # 2 h run
                Mode.REDUCE,  # recovery gap
                Mode.BLOCK,
                Mode.BLOCK,  # next 2 h run
                Mode.REDUCE,  # gap again
            ],
        )
        self.assertIn("max block run", plan[10].reason)
        # With hourly slots the 60 min gap is consumed by the downgraded slot itself,
        # so slot 13 is again limited by the run length.
        self.assertIn("max block run", plan[13].reason)

    def test_quarter_hour_slots_respect_minutes(self):
        prices = [0.1] * 32 + [5.0] * 16 + [0.1] * 48  # 4 h expensive block
        cfg = unconstrained(
            block_share=16 / 96, reduce_share=0.0, max_block_minutes=90, min_gap_after_block_minutes=30
        )
        plan = build_plan(make_slots(prices, minutes=15), cfg, tz=TZ)
        block_run = modes(plan)[32:48]
        self.assertEqual(block_run[:6], [Mode.BLOCK] * 6)  # 90 min
        self.assertEqual(block_run[6:8], [Mode.REDUCE] * 2)  # 30 min gap
        self.assertEqual(block_run[8:14], [Mode.BLOCK] * 6)
        self.assertEqual(block_run[14:16], [Mode.REDUCE] * 2)
        self.assertIn("max block run", plan[38].reason)
        self.assertIn("recovery gap", plan[39].reason)

    def test_zero_max_block_disables_blocking(self):
        cfg = unconstrained(block_share=0.5, reduce_share=0.0, max_block_minutes=0)
        plan = build_plan(make_slots(DAY), cfg, tz=TZ)
        self.assertNotIn(Mode.BLOCK, modes(plan))

    def test_daily_budget_keeps_most_expensive_blocks(self):
        prices = [0.1] * 6 + [3.0, 4.0, 5.0, 6.0] + [0.1] * 14
        cfg = unconstrained(
            block_share=4 / 24,
            reduce_share=0.0,
            max_block_minutes_per_day=120,
            max_block_minutes=240,
            min_gap_after_block_minutes=0,
        )
        plan = build_plan(make_slots(prices), cfg, tz=TZ)
        self.assertEqual(modes(plan)[6:10], [Mode.REDUCE, Mode.REDUCE, Mode.BLOCK, Mode.BLOCK])
        self.assertIn("daily block budget", plan[6].reason)


class LookupTests(unittest.TestCase):
    def test_mode_at_and_runs_and_summary(self):
        cfg = unconstrained()
        plan = build_plan(make_slots(DAY), cfg, tz=TZ)
        at = mode_at(plan, day_start() + timedelta(hours=18, minutes=30))
        self.assertIsNotNone(at)
        self.assertEqual(at.mode, Mode.BLOCK)
        self.assertIsNone(mode_at(plan, day_start() - timedelta(minutes=1)))

        merged = runs(plan)
        self.assertEqual(sum(r.minutes for r in merged), 24 * 60)
        self.assertTrue(all(a.end == b.start for a, b in zip(merged, merged[1:], strict=False)))
        self.assertTrue(all(a.mode is not b.mode for a, b in zip(merged, merged[1:], strict=False)))

        summary = summarize(plan)
        self.assertEqual(sum(v["minutes"] for v in summary.values()), 24 * 60)
        self.assertGreater(summary[Mode.BLOCK]["avg_price"], summary[Mode.BOOST]["avg_price"])

    def test_mode_parse(self):
        self.assertIs(Mode.parse(" Boost "), Mode.BOOST)
        self.assertIs(Mode.parse(Mode.BLOCK), Mode.BLOCK)
        with self.assertRaises(ValueError):
            Mode.parse("turbo")


if __name__ == "__main__":
    unittest.main()
