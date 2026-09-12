"""Modbus TCP backend: a list of register/coil writes per mode.

Requires ``pymodbus`` (``pip install '.[modbus]'``). Negative values are sent
as 16-bit two's complement, which is how signed heat pump registers such as a
heating-curve offset are usually encoded. Check your manufacturer's Modbus
manual for the exact addresses; nothing here is device specific.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..schedule import Mode
from .base import Backend, BackendError

log = logging.getLogger(__name__)

WRITE_KINDS = ("holding", "coil")


@dataclass(frozen=True)
class ModbusWrite:
    address: int
    value: int
    kind: str = "holding"

    def __post_init__(self) -> None:
        if self.kind not in WRITE_KINDS:
            raise ValueError(f"modbus write kind must be one of {WRITE_KINDS}, got {self.kind!r}")
        if self.address < 0:
            raise ValueError("modbus address must not be negative")
        if self.kind == "holding" and not -32768 <= self.value <= 65535:
            raise ValueError(f"modbus value {self.value} does not fit a 16-bit register")

    @property
    def register_value(self) -> int:
        return self.value & 0xFFFF if self.value < 0 else self.value


def _call_with_unit(function: Callable[..., Any], unit: int, *args: Any) -> Any:
    """pymodbus renamed the unit-id keyword across releases; try them in turn."""
    last_error: TypeError | None = None
    for keyword in ("device_id", "slave", "unit"):
        try:
            return function(*args, **{keyword: unit})
        except TypeError as exc:
            last_error = exc
    raise BackendError(f"unsupported pymodbus write signature: {last_error}")


class ModbusBackend(Backend):
    name = "modbus"

    def __init__(
        self,
        host: str,
        writes: dict[Mode, list[ModbusWrite]],
        *,
        port: int = 502,
        unit: int = 1,
        timeout: float = 5.0,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._unit = unit
        self._timeout = timeout
        self._writes = writes
        self._client_factory = client_factory or self._default_factory
        self._client: Any | None = None

    def _default_factory(self) -> Any:
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:
            raise BackendError("pymodbus is not installed (pip install '.[modbus]')") from exc
        return ModbusTcpClient(self._host, port=self._port, timeout=self._timeout)

    def _connected_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        client = self._client
        connected = getattr(client, "connected", None)
        if connected is False or connected is None:
            if not client.connect():
                self._client = None
                raise BackendError(f"cannot connect to Modbus {self._host}:{self._port}")
        return client

    def apply(self, mode: Mode) -> None:
        writes = self._writes.get(mode, [])
        if not writes:
            log.debug("modbus backend: no writes configured for mode %s", mode.value)
            return
        client = self._connected_client()
        for write in writes:
            if write.kind == "coil":
                result = _call_with_unit(client.write_coil, self._unit, write.address, bool(write.value))
            else:
                result = _call_with_unit(
                    client.write_register, self._unit, write.address, write.register_value
                )
            if hasattr(result, "isError") and result.isError():
                self.close()
                raise BackendError(f"modbus write to {write.address} failed: {result}")
            log.debug("modbus: %s %d <- %d", write.kind, write.address, write.value)

    def check(self) -> None:
        self._connected_client()

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def describe(self) -> str:
        return f"modbus {self._host}:{self._port} unit {self._unit}"
