from __future__ import annotations

import random
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from tibber_heatpump_bridge.curve import HouseModel, PowerModel
from tibber_heatpump_bridge.learning import (
    LearningError,
    Observation,
    RecursiveLeastSquares,
    fit_house_model,
    fit_power_model,
    house_regression_rows,
    least_squares,
    read_observations_csv,
    solve_linear,
    write_observations_csv,
)

from .helpers import day_start

TRUTH = HouseModel(a=0.05, b=0.03, c=1.05, d=0.004, filter_minutes=0.0)
POWER = PowerModel(kw_per_k_outdoor=0.06, kw_per_k_shift=0.08, heat_limit_c=16.0, standby_kw=0.05)


def simulate(hours: int, *, noise: float = 0.01, seed: int = 1, step_minutes: int = 30) -> list[Observation]:
    rng = random.Random(seed)
    observations: list[Observation] = []
    temp = 21.0
    shift = 0.0
    when = day_start()
    for k in range(hours * 60 // step_minutes):
        if k % 8 == 0:
            shift = rng.choice([-6.0, -3.0, 0.0, 2.0, 4.0])
        outdoor = 2.0 + 6.0 * ((k % 48) / 48.0 - 0.5)
        power = POWER.power_kw(outdoor, shift) + rng.gauss(0.0, 0.02)
        observations.append(Observation(when, temp + rng.gauss(0.0, noise), outdoor, shift, power))
        temp = TRUTH.step(temp, shift, outdoor, step_minutes)
        when += timedelta(minutes=step_minutes)
    return observations


class LinearAlgebraTests(unittest.TestCase):
    def test_solve_linear(self):
        x = solve_linear([[2.0, 1.0], [1.0, 3.0]], [3.0, 5.0])
        self.assertAlmostEqual(x[0], 0.8)
        self.assertAlmostEqual(x[1], 1.4)
        with self.assertRaises(LearningError):
            solve_linear([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])

    def test_least_squares_recovers_line(self):
        rows = [([1.0, float(i)], 2.0 + 0.5 * i) for i in range(10)]
        theta = least_squares(rows)
        self.assertAlmostEqual(theta[0], 2.0, places=6)
        self.assertAlmostEqual(theta[1], 0.5, places=6)


class HouseFitTests(unittest.TestCase):
    def test_batch_fit_recovers_parameters(self):
        fit = fit_house_model(simulate(24 * 14), include_outdoor=True)
        self.assertAlmostEqual(fit.model.a, TRUTH.a, delta=0.006)
        self.assertAlmostEqual(fit.model.b, TRUTH.b, delta=0.004)
        self.assertAlmostEqual(fit.model.equilibrium_c, 21.0 + TRUTH.d * 2.0 / TRUTH.a, delta=0.5)
        self.assertEqual(fit.report.warnings, [])
        self.assertLess(fit.report.rmse, 0.05)

    def test_rls_converges_to_same_parameters(self):
        rows = house_regression_rows(simulate(24 * 14))
        rls = RecursiveLeastSquares(4, forgetting=0.999)
        for x, y in rows:
            rls.update(x, y)
        self.assertAlmostEqual(rls.theta[1], TRUTH.a, delta=0.008)
        self.assertAlmostEqual(rls.theta[2], TRUTH.b, delta=0.006)
        self.assertEqual(rls.samples, len(rows))

    def test_constant_shift_is_flagged(self):
        observations = [
            Observation(day_start() + timedelta(minutes=30 * k), 21.0 - 0.01 * k, 2.0, 0.0) for k in range(40)
        ]
        with self.assertRaises(LearningError):
            fit_house_model(observations[:5])
        fit = fit_house_model(observations)
        self.assertTrue(any("never changed" in w for w in fit.report.warnings))

    def test_gaps_are_skipped(self):
        observations = simulate(48)
        observations[20] = Observation(observations[20].when + timedelta(hours=10), 21.0, 2.0, 0.0, None)
        rows = house_regression_rows(sorted(observations, key=lambda o: o.when))
        self.assertLess(len(rows), len(observations) - 1)


class PowerFitTests(unittest.TestCase):
    def test_power_fit(self):
        fit = fit_power_model(simulate(24 * 7), heat_limit_c=16.0)
        self.assertAlmostEqual(fit.model.kw_per_k_outdoor, POWER.kw_per_k_outdoor, delta=0.005)
        self.assertAlmostEqual(fit.model.kw_per_k_shift, POWER.kw_per_k_shift, delta=0.005)
        self.assertAlmostEqual(fit.model.standby_kw, POWER.standby_kw, delta=0.05)

    def test_power_fit_needs_power_column(self):
        observations = [Observation(o.when, o.indoor_c, o.outdoor_c, o.shift, None) for o in simulate(24)]
        with self.assertRaises(LearningError):
            fit_power_model(observations)


class CsvTests(unittest.TestCase):
    def test_roundtrip(self):
        observations = simulate(6)
        observations[2] = Observation(observations[2].when, 21.0, 1.0, 0.0, None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.csv"
            write_observations_csv(path, observations)
            back = read_observations_csv(path)
        self.assertEqual(len(back), len(observations))
        self.assertIsNone(back[2].power_kw)
        self.assertAlmostEqual(back[0].indoor_c, observations[0].indoor_c, places=3)
        self.assertEqual(back[0].when, observations[0].when)

    def test_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("time,indoor_c\n2026-01-01T00:00:00+01:00,21\n")
            with self.assertRaises(LearningError):
                read_observations_csv(path)


if __name__ == "__main__":
    unittest.main()
