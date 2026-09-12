"""TOML configuration loading and validation."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backends import BACKEND_TYPES
from .schedule import DEFAULT_LEVEL_MODES, Mode, ScheduleConfig, TimeWindow
from .tibber import RESOLUTIONS

TOKEN_ENV = "TIBBER_TOKEN"


class ConfigError(ValueError):
    """Raised for a missing, malformed or inconsistent configuration."""


@dataclass
class TibberConfig:
    token: str
    home_id: str | None = None
    resolution: str = "QUARTER_HOURLY"


@dataclass
class OutdoorConfig:
    url: str
    json_path: str = "state"
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 10.0


@dataclass
class RunConfig:
    interval_seconds: int = 60
    reapply_minutes: int = 15
    refresh_minutes: int = 30
    retry_minutes: int = 10
    stale_plan_hours: int = 6
    release_on_exit: bool = True


@dataclass
class BackendConfig:
    type: str = "dryrun"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    tibber: TibberConfig
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    run: RunConfig = field(default_factory=RunConfig)
    backend: BackendConfig = field(default_factory=BackendConfig)
    outdoor: OutdoorConfig | None = None


def load_config(path: str | os.PathLike[str], *, env: Mapping[str, str] | None = None) -> AppConfig:
    file = Path(path)
    try:
        with file.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file {file} not found") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file}: {exc}") from exc
    return parse_config(document, env=env)


def parse_config(document: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> AppConfig:
    env = os.environ if env is None else env
    tibber = _parse_tibber(_table(document, "tibber"), env)
    schedule = _parse_schedule(_table(document, "schedule"))
    run = _parse_run(_table(document, "run"))
    backend = _parse_backend(_table(document, "backend"))
    outdoor_raw = document.get("outdoor_temperature")
    outdoor = _parse_outdoor(outdoor_raw) if outdoor_raw else None
    return AppConfig(tibber=tibber, schedule=schedule, run=run, backend=backend, outdoor=outdoor)


# --- helpers ----------------------------------------------------------------


def _table(document: Mapping[str, Any], name: str) -> dict[str, Any]:
    raw = document.get(name, {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] must be a table")
    return dict(raw)


def _number(table: Mapping[str, Any], key: str, default: float | None, *, section: str) -> float | None:
    if key not in table or table[key] is None:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"[{section}].{key} must be a number")
    return float(value)


def _integer(table: Mapping[str, Any], key: str, default: int, *, section: str) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"[{section}].{key} must be an integer")
    return value


def _boolean(table: Mapping[str, Any], key: str, default: bool, *, section: str) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"[{section}].{key} must be true or false")
    return value


def _parse_tibber(table: Mapping[str, Any], env: Mapping[str, str]) -> TibberConfig:
    token = str(table.get("token") or env.get(TOKEN_ENV) or "").strip()
    if not token:
        raise ConfigError(f"[tibber].token is missing (or set the {TOKEN_ENV} environment variable)")
    resolution = str(table.get("resolution", "QUARTER_HOURLY")).upper()
    if resolution not in RESOLUTIONS:
        raise ConfigError(f"[tibber].resolution must be one of {RESOLUTIONS}")
    home_id = str(table.get("home_id") or "").strip() or None
    return TibberConfig(token=token, home_id=home_id, resolution=resolution)


def _parse_schedule(table: Mapping[str, Any]) -> ScheduleConfig:
    section = "schedule"
    defaults = ScheduleConfig()
    windows: list[TimeWindow] = []
    for text in table.get("comfort_windows", []) or []:
        try:
            windows.append(TimeWindow.parse(str(text)))
        except ValueError as exc:
            raise ConfigError(f"[schedule].comfort_windows: {exc}") from exc
    level_modes = dict(DEFAULT_LEVEL_MODES)
    raw_levels = table.get("level_modes") or {}
    if not isinstance(raw_levels, dict):
        raise ConfigError("[schedule.level_modes] must be a table")
    for level, mode in raw_levels.items():
        try:
            level_modes[str(level).upper()] = Mode.parse(mode)
        except ValueError as exc:
            raise ConfigError(f"[schedule.level_modes].{level}: {exc}") from exc
    cfg = ScheduleConfig(
        strategy=str(table.get("strategy", defaults.strategy)),
        force_share=_number(table, "force_share", defaults.force_share, section=section) or 0.0,
        boost_share=_number(table, "boost_share", defaults.boost_share, section=section) or 0.0,
        reduce_share=_number(table, "reduce_share", defaults.reduce_share, section=section) or 0.0,
        block_share=_number(table, "block_share", defaults.block_share, section=section) or 0.0,
        force_below_price=_number(table, "force_below_price", defaults.force_below_price, section=section),
        block_only_above_price=_number(table, "block_only_above_price", None, section=section),
        level_modes=level_modes,
        max_block_minutes=_integer(table, "max_block_minutes", defaults.max_block_minutes, section=section),
        min_gap_after_block_minutes=_integer(
            table, "min_gap_after_block_minutes", defaults.min_gap_after_block_minutes, section=section
        ),
        max_block_minutes_per_day=_integer(
            table, "max_block_minutes_per_day", defaults.max_block_minutes_per_day, section=section
        ),
        comfort_windows=windows,
        never_block_below_outdoor_c=_number(table, "never_block_below_outdoor_c", None, section=section),
        timezone=str(table["timezone"]).strip() if table.get("timezone") else None,
    )
    try:
        cfg.validate()
    except (ValueError, KeyError) as exc:
        raise ConfigError(f"[schedule]: {exc}") from exc
    return cfg


def _parse_run(table: Mapping[str, Any]) -> RunConfig:
    section = "run"
    defaults = RunConfig()
    cfg = RunConfig(
        interval_seconds=_integer(table, "interval_seconds", defaults.interval_seconds, section=section),
        reapply_minutes=_integer(table, "reapply_minutes", defaults.reapply_minutes, section=section),
        refresh_minutes=_integer(table, "refresh_minutes", defaults.refresh_minutes, section=section),
        retry_minutes=_integer(table, "retry_minutes", defaults.retry_minutes, section=section),
        stale_plan_hours=_integer(table, "stale_plan_hours", defaults.stale_plan_hours, section=section),
        release_on_exit=_boolean(table, "release_on_exit", defaults.release_on_exit, section=section),
    )
    if cfg.interval_seconds < 5:
        raise ConfigError("[run].interval_seconds must be at least 5")
    for name in ("reapply_minutes", "refresh_minutes", "retry_minutes", "stale_plan_hours"):
        if getattr(cfg, name) < 1:
            raise ConfigError(f"[run].{name} must be at least 1")
    return cfg


def _parse_backend(table: Mapping[str, Any]) -> BackendConfig:
    kind = str(table.get("type", "dryrun")).lower()
    if kind not in BACKEND_TYPES:
        raise ConfigError(f"[backend].type must be one of {BACKEND_TYPES}, got {kind!r}")
    options = table.get(kind, {})
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ConfigError(f"[backend.{kind}] must be a table")
    return BackendConfig(type=kind, options=dict(options))


def _parse_outdoor(raw: Any) -> OutdoorConfig:
    if not isinstance(raw, dict):
        raise ConfigError("[outdoor_temperature] must be a table")
    if not raw.get("url"):
        raise ConfigError("[outdoor_temperature].url is required")
    headers = raw.get("headers") or {}
    if not isinstance(headers, dict):
        raise ConfigError("[outdoor_temperature.headers] must be a table")
    return OutdoorConfig(
        url=str(raw["url"]),
        json_path=str(raw.get("json_path", "state")),
        headers={str(k): str(v) for k, v in headers.items()},
        timeout_seconds=float(_number(raw, "timeout_seconds", 10.0, section="outdoor_temperature") or 10.0),
    )
