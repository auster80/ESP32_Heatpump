"""Modbus TCP backend: a list of register/coil writes per mode.

Requires ``pymodbus`` (``pip install '.[modbus]'``). Negative values are sent
as 16-bit two's complement, which is how signed heat pump registers such as a
heating-curve offset are usually encoded. Check your manufacturer's Modbus
manual for the exact addresses; nothing here is device specific.

**Write endurance.** A holding register that holds a *parameter* (a setpoint,
a heating-curve rise) is stored in the controller's non-volatile memory, which
survives a finite number of write cycles. A controller that rewrites the same
value every ``reapply_minutes`` would spend that budget for nothing: at the
15-minute default that is 96 writes a day, ~35 000 a year, per register. This
backend therefore writes a register only when the value actually changes, and
can be given a hard daily budget per address.

Targets that merely emulate a contact (a coil, or an SG Ready input register)
do not persist and may be rewritten freely; mark those ``volatile=True`` so a
reboot of the device is repaired on the next tick.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..schedule import Mode
from .base import Backend, BackendError

log = logging.getLogger(__name__)

WRITE_KINDS = ("holding", "coil")


DAY_SECONDS = 86400.0


@dataclass(frozen=True)
class ModbusWrite:
    address: int
    value: int
    kind: str = "holding"
    volatile: bool = False
    """The target does not persist (a coil, or a register emulating a contact).

    Volatile targets are rewritten on every apply, so that a device that
    rebooted is put back into the right state. Everything else is assumed to
    live in non-volatile memory and is written only when the value changes.
    """

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
        max_writes_per_day: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_writes_per_day is not None and max_writes_per_day < 1:
            raise ValueError("max_writes_per_day must be at least 1")
        self._host = host
        self._port = port
        self._unit = unit
        self._timeout = timeout
        self._writes = writes
        self._client_factory = client_factory or self._default_factory
        self._client: Any | None = None
        self._max_writes_per_day = max_writes_per_day
        self._clock = clock or time.monotonic
        self._last_written: dict[tuple[str, int], int] = {}
        self._recent: dict[tuple[str, int], deque[float]] = {}

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

    def _within_budget(self, key: tuple[str, int]) -> bool:
        """Whether another write to ``key`` fits the rolling 24-hour budget."""
        if self._max_writes_per_day is None:
            return True
        now = self._clock()
        stamps = self._recent.setdefault(key, deque())
        while stamps and now - stamps[0] >= DAY_SECONDS:
            stamps.popleft()
        return len(stamps) < self._max_writes_per_day

    def _pending(self, writes: list[ModbusWrite]) -> list[ModbusWrite]:
        """Drop writes that would change nothing or exceed the daily budget."""
        pending: list[ModbusWrite] = []
        for write in writes:
            key = (write.kind, write.address)
            if not write.volatile and self._last_written.get(key) == write.value:
                log.debug("modbus: %s %d already %d, not rewriting", *key, write.value)
                continue
            if not self._within_budget(key):
                log.warning(
                    "modbus: refusing to write %s %d, the daily budget of %d writes is spent; "
                    "the heat pump keeps its current setting",
                    write.kind,
                    write.address,
                    self._max_writes_per_day,
                )
                continue
            pending.append(write)
        return pending

    def apply(self, mode: Mode) -> None:
        writes = self._writes.get(mode, [])
        if not writes:
            log.debug("modbus backend: no writes configured for mode %s", mode.value)
            return
        writes = self._pending(writes)
        if not writes:
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
            key = (write.kind, write.address)
            self._last_written[key] = write.value
            if self._max_writes_per_day is not None:
                self._recent.setdefault(key, deque()).append(self._clock())
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
