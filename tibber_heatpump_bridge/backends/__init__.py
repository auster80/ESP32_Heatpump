"""Backend registry: build a :class:`Backend` from the ``[backend]`` config table."""

from __future__ import annotations

from typing import Any

from ..schedule import Mode
from .base import Backend, BackendError
from .dryrun import DryRunBackend
from .http import HttpAction, HttpBackend
from .modbus import ModbusBackend, ModbusWrite
from .mqtt import MqttBackend
from .sgready import Channel, GpioChannel, HttpChannel, SGReadyBackend

BACKEND_TYPES = ("dryrun", "sgready", "http", "modbus", "mqtt")

__all__ = [
    "BACKEND_TYPES",
    "Backend",
    "BackendError",
    "DryRunBackend",
    "HttpBackend",
    "ModbusBackend",
    "MqttBackend",
    "SGReadyBackend",
    "build_backend",
]


def _mode_table(raw: Any, what: str) -> dict[Mode, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise BackendError(f"{what} must be a table keyed by mode")
    try:
        return {Mode.parse(key): value for key, value in raw.items()}
    except ValueError as exc:
        raise BackendError(f"{what}: {exc}") from exc


def _channel(raw: Any, name: str, timeout: float) -> Channel:
    if not isinstance(raw, dict):
        raise BackendError(f"[backend.sgready.{name}] must be a table")
    kind = str(raw.get("type", "http"))
    if kind == "http":
        try:
            return HttpChannel(
                str(raw["on"]),
                str(raw["off"]),
                method=str(raw.get("method", "GET")),
                timeout=timeout,
            )
        except KeyError as exc:
            raise BackendError(f"[backend.sgready.{name}] needs 'on' and 'off' URLs") from exc
    if kind == "gpio":
        if "pin" not in raw:
            raise BackendError(f"[backend.sgready.{name}] needs a 'pin'")
        return GpioChannel(int(raw["pin"]), active_high=bool(raw.get("active_high", True)))
    raise BackendError(f"[backend.sgready.{name}] type must be 'http' or 'gpio', got {kind!r}")


def _build_sgready(options: dict[str, Any]) -> Backend:
    timeout = float(options.get("timeout_seconds", 10.0))
    mode_states = {
        mode: int(state)
        for mode, state in _mode_table(options.get("modes"), "[backend.sgready].modes").items()
    }
    return SGReadyBackend(
        _channel(options.get("a"), "a", timeout),
        _channel(options.get("b"), "b", timeout),
        mode_states=mode_states,
    )


def _build_http(options: dict[str, Any]) -> Backend:
    actions: dict[Mode, list[HttpAction]] = {}
    for mode, entries in _mode_table(options.get("actions"), "[backend.http.actions]").items():
        if not isinstance(entries, list):
            raise BackendError(f"[backend.http.actions].{mode.value} must be a list of requests")
        built: list[HttpAction] = []
        for entry in entries:
            if not isinstance(entry, dict) or "url" not in entry:
                raise BackendError(f"[backend.http.actions].{mode.value}: each entry needs a 'url'")
            headers = entry.get("headers") or {}
            built.append(
                HttpAction(
                    url=str(entry["url"]),
                    method=str(entry.get("method", "GET")),
                    body=None if entry.get("body") is None else str(entry["body"]),
                    headers={str(k): str(v) for k, v in headers.items()},
                )
            )
        actions[mode] = built
    if not actions:
        raise BackendError("[backend.http.actions] has no modes configured")
    return HttpBackend(actions, timeout=float(options.get("timeout_seconds", 10.0)))


def _build_modbus(options: dict[str, Any]) -> Backend:
    if "host" not in options:
        raise BackendError("[backend.modbus] needs a 'host'")
    writes: dict[Mode, list[ModbusWrite]] = {}
    for mode, entries in _mode_table(options.get("writes"), "[backend.modbus.writes]").items():
        if not isinstance(entries, list):
            raise BackendError(f"[backend.modbus.writes].{mode.value} must be a list of writes")
        try:
            writes[mode] = [
                ModbusWrite(
                    address=int(entry["address"]),
                    value=int(entry["value"]),
                    kind=str(entry.get("kind", "holding")),
                )
                for entry in entries
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise BackendError(f"[backend.modbus.writes].{mode.value}: {exc}") from exc
    if not writes:
        raise BackendError("[backend.modbus.writes] has no modes configured")
    return ModbusBackend(
        str(options["host"]),
        writes,
        port=int(options.get("port", 502)),
        unit=int(options.get("unit", 1)),
        timeout=float(options.get("timeout_seconds", 5.0)),
    )


def _build_mqtt(options: dict[str, Any]) -> Backend:
    if "host" not in options:
        raise BackendError("[backend.mqtt] needs a 'host'")
    payloads = {
        mode: str(value)
        for mode, value in _mode_table(options.get("payloads"), "[backend.mqtt.payloads]").items()
    }
    return MqttBackend(
        str(options["host"]),
        port=int(options.get("port", 1883)),
        topic=str(options.get("topic", "heatpump/mode")),
        payloads=payloads,
        username=options.get("username"),
        password=options.get("password"),
        retain=bool(options.get("retain", True)),
        qos=int(options.get("qos", 1)),
        timeout=float(options.get("timeout_seconds", 10.0)),
    )


def build_backend(kind: str, options: dict[str, Any] | None = None) -> Backend:
    options = options or {}
    if kind == "dryrun":
        return DryRunBackend()
    if kind == "sgready":
        return _build_sgready(options)
    if kind == "http":
        return _build_http(options)
    if kind == "modbus":
        return _build_modbus(options)
    if kind == "mqtt":
        return _build_mqtt(options)
    raise BackendError(f"[backend].type must be one of {BACKEND_TYPES}, got {kind!r}")
