from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path

from tibber_heatpump_bridge.cli import main, render_curve_plan
from tibber_heatpump_bridge.config import ConfigError, parse_config
from tibber_heatpump_bridge.curve import plan_curve
from tibber_heatpump_bridge.learning import write_observations_csv
from tibber_heatpump_bridge.sensors import NtcSensor, Pt1000Sensor

from .helpers import TZ, day_start, make_slots
from .test_learning import simulate
from .test_schedule import DAY

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


class CurveConfigTests(unittest.TestCase):
    def test_defaults_when_section_missing(self):
        cfg = parse_config({"tibber": {"token": "t"}}, env={})
        self.assertEqual(cfg.curve.settings.band_low, 20.0)
        self.assertIsNone(cfg.curve.sensor)
        self.assertEqual(cfg.curve.planning_slot_minutes, 30)

    def test_example_config_curve_section(self):
        cfg = parse_config(__import__("tomllib").loads(EXAMPLE.read_text()), env={"TIBBER_TOKEN": "x"})
        self.assertEqual(cfg.curve.settings.actions, (-6.0, -3.0, 0.0, 2.0, 4.0))
        self.assertAlmostEqual(cfg.curve.house.equilibrium_c, 21.0)
        assert cfg.curve.sensor is not None
        self.assertIsInstance(cfg.curve.sensor.sensor, NtcSensor)
        self.assertEqual(cfg.curve.sensor.pot.taps, 1024)
        self.assertEqual(cfg.curve.sensor.pot.wiper_ohms, 35.0)

    def test_pt1000_sensor(self):
        cfg = parse_config(
            {
                "tibber": {"token": "t"},
                "curve": {"sensor": {"type": "pt1000", "digipot_ohms": 1000, "series_ohms": 850}},
            },
            env={},
        )
        assert cfg.curve.sensor is not None
        self.assertIsInstance(cfg.curve.sensor.sensor, Pt1000Sensor)
        self.assertEqual(cfg.curve.sensor.pot.series_ohms, 850.0)

    def test_invalid_values(self):
        for bad in (
            {"band_low": 23.0},
            {"actions": []},
            {"actions": ["x"]},
            {"model": {"a": -1.0}},
            {"sensor": {"type": "lm35"}},
            {"planning_slot_minutes": 1},
            {"comfort_penalty": -1.0},
            {"switch_penalty": -0.1},
        ):
            with self.assertRaises(ConfigError, msg=str(bad)):
                parse_config({"tibber": {"token": "t"}, "curve": bad}, env={})


class RenderTests(unittest.TestCase):
    def test_render_runs_and_slots(self):
        cfg = parse_config(__import__("tomllib").loads(EXAMPLE.read_text()), env={"TIBBER_TOKEN": "x"})
        slots = make_slots(DAY)
        plan = plan_curve(
            slots, cfg.curve.house, cfg.curve.power, cfg.curve.settings, indoor_c=21.0, outdoor_c=2.0
        )
        now = day_start() + timedelta(hours=18, minutes=10)
        text = render_curve_plan(cfg, plan, tz=TZ, now=now, indoor_c=21.0, outdoor_c=2.0, currency="NOK")
        self.assertIn("without shifting", text)
        self.assertIn("present", text)
        self.assertIn("ntc:", text)
        self.assertIn("tap", text)
        self.assertIn("*", text)
        detailed = render_curve_plan(
            cfg, plan, tz=TZ, now=now, indoor_c=21.0, outdoor_c=2.0, currency="NOK", every_slot=True
        )
        self.assertGreaterEqual(detailed.count("shift"), 24)


class CurveFitCommandTests(unittest.TestCase):
    def test_curve_fit_prints_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('[tibber]\ntoken = "t"\n')
            log = Path(tmp) / "log.csv"
            write_observations_csv(log, simulate(24 * 10))
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["-c", str(config), "curve-fit", str(log), "--filter-minutes", "0"])
            self.assertEqual(code, 0, err.getvalue())
            text = out.getvalue()
            self.assertIn("[curve.model]", text)
            self.assertIn("[curve.power]", text)
            self.assertIn("a = 0.0", text)
            self.assertNotIn("WARNING", text)

    def test_curve_fit_reports_bad_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('[tibber]\ntoken = "t"\n')
            log = Path(tmp) / "log.csv"
            log.write_text("time,indoor_c\n")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = main(["-c", str(config), "curve-fit", str(log)])
            self.assertEqual(code, 2)
            self.assertIn("missing columns", err.getvalue())


if __name__ == "__main__":
    unittest.main()
