from __future__ import annotations

import unittest
from datetime import timedelta

from tibber_heatpump_bridge.curve import (
    CurveSettings,
    CyclingModel,
    HouseModel,
    PowerModel,
    merge_slots,
    plan_curve,
    rollout,
    shift_runs,
)

from .helpers import day_start, make_slots
from .test_schedule import DAY

TWO_DAYS = DAY + DAY
FAST = CurveSettings(temp_step=0.2, shift_step=2.0, actions=(-6.0, -2.0, 0.0, 2.0, 4.0))


class ModelTests(unittest.TestCase):
    def test_equilibrium_and_filter(self):
        house = HouseModel(a=0.05, b=0.03, c=1.05, filter_minutes=60.0)
        self.assertAlmostEqual(house.equilibrium_c, 21.0)
        self.assertAlmostEqual(house.time_constant_h, 20.0)
        eff = house.filter_step(0.0, 4.0, 60.0)
        self.assertAlmostEqual(eff, 4.0 * (1 - 2.718281828**-1), places=6)
        self.assertEqual(HouseModel(filter_minutes=0.0).filter_step(0.0, 4.0, 15.0), 4.0)

    def test_step_moves_towards_equilibrium(self):
        house = HouseModel()
        self.assertGreater(house.step(20.0, 0.0, 0.0, 60.0), 20.0)
        self.assertLess(house.step(22.0, 0.0, 0.0, 60.0), 22.0)
        self.assertGreater(house.step(21.0, 4.0, 0.0, 60.0), 21.0)

    def test_power_model_clamps_at_zero(self):
        power = PowerModel(kw_per_k_outdoor=0.06, kw_per_k_shift=0.08, heat_limit_c=16.0)
        self.assertAlmostEqual(power.power_kw(0.0, 0.0), 0.96)
        self.assertEqual(power.power_kw(20.0, -6.0), 0.0)
        self.assertAlmostEqual(power.power_kw(0.0, 4.0), 1.28)

    def test_validation(self):
        with self.assertRaises(ValueError):
            HouseModel(a=0.0).validate()
        with self.assertRaises(ValueError):
            CurveSettings(band_low=22.0, band_high=20.0).validate()
        with self.assertRaises(ValueError):
            CurveSettings(end_target=25.0).validate()


class PlannerTests(unittest.TestCase):
    def test_plan_holds_band_and_beats_baseline(self):
        slots = make_slots(TWO_DAYS)
        plan = plan_curve(slots, HouseModel(), PowerModel(), FAST, indoor_c=21.0, outdoor_c=0.0)
        self.assertEqual(len(plan.steps), 48)
        self.assertLessEqual(plan.max_violation_k, 0.15)
        self.assertLess(plan.cost, plan.baseline_cost * 0.97)
        # Cheap slots get more shift than expensive ones.
        ranked = sorted(plan.steps, key=lambda s: s.slot.total)
        cheap = sum(s.shift for s in ranked[:12]) / 12
        pricey = sum(s.shift for s in ranked[-12:]) / 12
        self.assertGreater(cheap, pricey + 2.0)
        # The evening peak (18:00) is coasted.
        self.assertLess(plan.steps[18].shift, 0.0)

    def test_negative_prices_trigger_maximum_shift(self):
        prices = [0.5] * 24
        prices[10] = prices[11] = -1.0  # strongly negative: worth switching and warming up
        slots = make_slots(prices)
        plan = plan_curve(slots, HouseModel(), PowerModel(), FAST, indoor_c=20.5, outdoor_c=0.0)
        self.assertEqual(plan.steps[10].shift, 4.0)
        self.assertEqual(plan.steps[11].shift, 4.0)

    def test_equal_prices_keep_temperature_stable(self):
        slots = make_slots([1.0] * 24)
        plan = plan_curve(slots, HouseModel(), PowerModel(), FAST, indoor_c=21.0, outdoor_c=0.0)
        low, high = plan.indoor_range
        # The comfort penalty lets the room sag about half a degree (cheaper), no more.
        self.assertGreater(low, 20.3)
        self.assertLess(high, 21.5)
        self.assertAlmostEqual(plan.cost, plan.baseline_cost, delta=plan.baseline_cost * 0.1)

    def test_without_comfort_penalty_the_band_floor_is_cheapest(self):
        slots = make_slots([1.0] * 24)
        settings = CurveSettings(**{**FAST.__dict__, "comfort_penalty": 0.0})
        plan = plan_curve(slots, HouseModel(), PowerModel(), settings, indoor_c=21.0, outdoor_c=0.0)
        self.assertLess(plan.indoor_range[0], 20.3)
        self.assertLess(plan.cost, plan.baseline_cost)

    def test_filter_lag_is_respected(self):
        slots = make_slots(TWO_DAYS)
        house = HouseModel(filter_minutes=120.0)
        plan = plan_curve(slots, house, PowerModel(), FAST, indoor_c=21.0, outdoor_c=0.0)
        self.assertLessEqual(plan.max_violation_k, 0.15)
        lagging = [s for s in plan.steps if abs(s.shift_effective - s.shift) > 0.5]
        self.assertTrue(lagging, "effective shift should lag the applied shift")

    def test_outdoor_series_and_cold_snap_costs_more(self):
        slots = make_slots(DAY)
        cold = plan_curve(slots, HouseModel(), PowerModel(), FAST, indoor_c=21.0, outdoor_c=-10.0)
        mild = plan_curve(slots, HouseModel(), PowerModel(), FAST, indoor_c=21.0, outdoor_c=10.0)
        self.assertGreater(cold.energy_kwh, mild.energy_kwh)
        series = [-10.0] * 12 + [5.0] * 12
        plan = plan_curve(slots, HouseModel(), PowerModel(), FAST, indoor_c=21.0, outdoor_c=series)
        self.assertEqual([s.outdoor_c for s in plan.steps][:12], [-10.0] * 12)
        self.assertEqual(plan.steps[-1].outdoor_c, 5.0)

    def test_receding_horizon_with_model_mismatch(self):
        """Plan with the default model, but the real house is 25% different."""
        truth = HouseModel(a=0.0625, b=0.0225, c=1.3125, filter_minutes=90.0)  # equilibrium 21.0
        planner_model = HouseModel(filter_minutes=60.0)
        slots = make_slots(TWO_DAYS)
        temp, eff = 21.0, 0.0
        applied: list[float] = []
        for k in range(len(slots)):
            if k % 6 == 0:  # re-plan every six hours on the remaining horizon
                plan = plan_curve(
                    slots[k:],
                    planner_model,
                    PowerModel(),
                    FAST,
                    indoor_c=temp,
                    outdoor_c=0.0,
                    shift_effective=eff,
                )
                upcoming = [s.shift for s in plan.steps[:6]]
            shift = upcoming[k % 6]
            applied.append(shift)
            eff = truth.filter_step(eff, shift, slots[k].minutes)
            temp = truth.step(temp, eff, 0.0, slots[k].minutes)
            self.assertGreater(temp, FAST.band_low - 0.4, f"too cold at slot {k}")
            self.assertLess(temp, FAST.band_high + 0.4, f"too warm at slot {k}")
        real = rollout(slots, truth, PowerModel(), applied, indoor_c=21.0, outdoor=[0.0] * 48)
        baseline = rollout(slots, truth, PowerModel(), [0.0] * 48, indoor_c=21.0, outdoor=[0.0] * 48)
        self.assertLess(sum(s.cost for s in real), sum(s.cost for s in baseline))

    def test_switch_penalty_reduces_dithering(self):
        slots = make_slots(TWO_DAYS)
        nervous = CurveSettings(**{**FAST.__dict__, "switch_penalty": 0.0})
        calm = CurveSettings(**{**FAST.__dict__, "switch_penalty": 0.05})
        house = HouseModel(filter_minutes=90.0)

        def changes(settings):
            plan = plan_curve(slots, house, PowerModel(), settings, indoor_c=21.0, outdoor_c=0.0)
            return sum(1 for a, b in zip(plan.steps, plan.steps[1:], strict=False) if a.shift != b.shift)

        self.assertLess(changes(calm), changes(nervous) * 0.7)
        self.assertLessEqual(changes(calm), 18)

    def test_empty_slots_rejected(self):
        with self.assertRaises(ValueError):
            plan_curve([], HouseModel(), PowerModel(), FAST, indoor_c=21.0, outdoor_c=0.0)


class HelperTests(unittest.TestCase):
    def test_merge_slots_weights_price_by_duration(self):
        quarter = make_slots([1.0, 2.0, 3.0, 4.0, 5.0], minutes=15)
        merged = merge_slots(quarter, 30)
        self.assertEqual([s.minutes for s in merged], [30, 30, 15])
        self.assertEqual([s.total for s in merged], [1.5, 3.5, 5.0])
        self.assertEqual(merged[0].end, merged[1].start)

    def test_merge_slots_breaks_on_gap(self):
        first = make_slots([1.0, 1.0], minutes=15)
        later = make_slots([2.0, 2.0], minutes=15, start=day_start() + timedelta(hours=3))
        merged = merge_slots(first + later, 60)
        self.assertEqual(len(merged), 2)

    def test_shift_runs_merge_equal_shifts(self):
        slots = make_slots([0.1] * 4 + [3.0] * 4)
        plan = plan_curve(slots, HouseModel(), PowerModel(), FAST, indoor_c=21.0, outdoor_c=0.0)
        runs = shift_runs(plan, indoor_start_c=21.0)
        self.assertEqual(sum(r.minutes for r in runs), 8 * 60)
        self.assertTrue(all(a.shift != b.shift for a, b in zip(runs, runs[1:], strict=False)))
        self.assertEqual(runs[0].indoor_start_c, 21.0)


if __name__ == "__main__":
    unittest.main()


class CyclingModelTests(unittest.TestCase):
    def _model(self) -> CyclingModel:
        return CyclingModel(capacity_kw=6.0, buffer_kwh=0.5, min_off_minutes=20.0)

    def test_no_cycling_at_the_extremes(self):
        m = self._model()
        self.assertEqual(m.starts_per_hour(0.0), 0.0)
        self.assertEqual(m.starts_per_hour(6.0), 0.0)
        self.assertEqual(m.starts_per_hour(9.9), 0.0)

    def test_cycling_peaks_at_partial_load(self):
        """The result the planner leans on: pushing the pump towards off or
        towards capacity reduces starts. Cost and wear are not in tension."""
        m = self._model()
        peak = max(m.starts_per_hour(d / 10) for d in range(1, 60))
        self.assertGreater(peak, m.starts_per_hour(0.3))
        self.assertGreater(peak, m.starts_per_hour(5.5))

    def test_blocking_beats_flat_operation_for_the_same_energy(self):
        """24 kWh/day delivered in blocks costs far fewer starts than flat."""
        m = self._model()
        flat = m.starts_per_hour(1.0) * 24
        blocked = m.starts_per_hour(4.0) * 6
        self.assertLess(blocked, flat / 3)

    def test_a_bigger_buffer_cycles_less(self):
        small = CyclingModel(capacity_kw=6.0, buffer_kwh=0.25)
        large = CyclingModel(capacity_kw=6.0, buffer_kwh=2.0)
        self.assertGreater(small.starts_per_hour(3.0), large.starts_per_hour(3.0))

    def test_min_off_timer_binds_where_the_natural_off_period_is_short(self):
        """RESTSTILLSTAND clips cycling at moderate demand, where the buffer
        drains quickly, and does nothing at low demand where the off period is
        already long."""
        without = CyclingModel(capacity_kw=6.0, buffer_kwh=0.5, min_off_minutes=0.0)
        with_timer = CyclingModel(capacity_kw=6.0, buffer_kwh=0.5, min_off_minutes=30.0)
        # 2 kW: natural off period is 15 min, so a 30 min timer halves the rate
        self.assertLess(with_timer.starts_per_hour(2.0), without.starts_per_hour(2.0))
        # 0.5 kW: natural off period is already 60 min, timer is irrelevant
        self.assertAlmostEqual(with_timer.starts_per_hour(0.5), without.starts_per_hour(0.5), places=9)

    def test_duty_and_validation(self):
        m = self._model()
        self.assertAlmostEqual(m.duty(3.0), 0.5)
        self.assertAlmostEqual(m.duty(9.0), 1.0)
        m.validate()
        with self.assertRaises(ValueError):
            CyclingModel(capacity_kw=0.0).validate()
        with self.assertRaises(ValueError):
            CyclingModel(buffer_kwh=-1.0).validate()
