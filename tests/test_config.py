from __future__ import annotations

import unittest
from pathlib import Path

from tibber_heatpump_bridge.config import ConfigError, load_config, parse_config
from tibber_heatpump_bridge.schedule import Mode

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


class ExampleConfigTests(unittest.TestCase):
    def test_example_config_loads_with_env_token(self):
        cfg = load_config(EXAMPLE, env={"TIBBER_TOKEN": "env-token"})
        self.assertEqual(cfg.tibber.token, "env-token")
        self.assertIsNone(cfg.tibber.home_id)
        self.assertEqual(cfg.tibber.resolution, "QUARTER_HOURLY")
        self.assertEqual(cfg.backend.type, "dryrun")
        self.assertEqual(cfg.schedule.strategy, "percentile")
        self.assertEqual([str(w) for w in cfg.schedule.comfort_windows], ["06:00-08:00", "17:00-21:00"])
        self.assertEqual(cfg.schedule.level_modes["VERY_EXPENSIVE"], Mode.BLOCK)
        self.assertEqual(cfg.run.interval_seconds, 60)
        self.assertTrue(cfg.run.release_on_exit)
        self.assertIsNone(cfg.outdoor)

    def test_example_config_without_token_fails(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(EXAMPLE, env={})
        self.assertIn("token", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config("/nonexistent/config.toml", env={})


class ParseConfigTests(unittest.TestCase):
    def test_backend_options_follow_type(self):
        cfg = parse_config(
            {
                "tibber": {"token": "t"},
                "backend": {"type": "mqtt", "mqtt": {"host": "b"}, "sgready": {"a": {}}},
            },
            env={},
        )
        self.assertEqual(cfg.backend.type, "mqtt")
        self.assertEqual(cfg.backend.options, {"host": "b"})

    def test_unknown_backend_type(self):
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t"}, "backend": {"type": "fax"}}, env={})

    def test_invalid_schedule_values(self):
        with self.assertRaises(ConfigError):
            parse_config(
                {"tibber": {"token": "t"}, "schedule": {"boost_share": 0.8, "block_share": 0.5}}, env={}
            )
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t"}, "schedule": {"comfort_windows": ["morning"]}}, env={})
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t"}, "schedule": {"level_modes": {"CHEAP": "turbo"}}}, env={})
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t"}, "schedule": {"timezone": "Mars/Olympus"}}, env={})

    def test_invalid_resolution(self):
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t", "resolution": "DAILY"}}, env={})

    def test_run_limits(self):
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t"}, "run": {"interval_seconds": 1}}, env={})
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t"}, "run": {"release_on_exit": "yes"}}, env={})

    def test_outdoor_section(self):
        cfg = parse_config(
            {
                "tibber": {"token": "t"},
                "outdoor_temperature": {"url": "http://ha/api", "json_path": "state", "headers": {"A": "b"}},
            },
            env={},
        )
        assert cfg.outdoor is not None
        self.assertEqual(cfg.outdoor.headers, {"A": "b"})
        with self.assertRaises(ConfigError):
            parse_config({"tibber": {"token": "t"}, "outdoor_temperature": {"json_path": "x"}}, env={})

    def test_config_token_wins_over_env(self):
        cfg = parse_config({"tibber": {"token": "file"}}, env={"TIBBER_TOKEN": "env"})
        self.assertEqual(cfg.tibber.token, "file")


if __name__ == "__main__":
    unittest.main()
