"""SG Ready backend: drives the two SG Ready contacts of a heat pump.

SG Ready states (BWP definition, contact A : contact B)::

    1  A=1 B=0  blocked (utility lock, max 2 h at a time)
    2  A=0 B=0  normal operation
    3  A=0 B=1  recommended on (raised set points)
    4  A=1 B=1  forced on (maximum set points)

Each contact is a :class:`Channel`: an HTTP-controlled relay (Shelly, Tasmota,
...) or a GPIO pin on a Raspberry Pi wired to a relay board.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ..schedule import Mode
from ._http import Sender, send_request
from .base import Backend, BackendError

log = logging.getLogger(__name__)

SG_READY_STATES: dict[int, tuple[bool, bool]] = {
    1: (True, False),
    2: (False, False),
    3: (False, True),
    4: (True, True),
}
DEFAULT_MODE_STATES: dict[Mode, int] = {
    Mode.BLOCK: 1,
    Mode.REDUCE: 2,
    Mode.NORMAL: 2,
    Mode.BOOST: 3,
    Mode.FORCE: 4,
}


class Channel(Protocol):
    def set(self, on: bool) -> None: ...

    def describe(self) -> str: ...


class HttpChannel:
    def __init__(
        self,
        on_url: str,
        off_url: str,
        *,
        method: str = "GET",
        timeout: float = 10.0,
        sender: Sender | None = None,
    ) -> None:
        self._on_url = on_url
        self._off_url = off_url
        self._method = method
        self._timeout = timeout
        self._send = sender or send_request

    def set(self, on: bool) -> None:
        url = self._on_url if on else self._off_url
        self._send(url, self._method, None, {}, self._timeout)

    def describe(self) -> str:
        return f"http {self._on_url}"


class GpioChannel:
    """Raspberry Pi GPIO output via gpiozero (installed with the ``gpio`` extra)."""

    def __init__(self, pin: int, *, active_high: bool = True) -> None:
        try:
            from gpiozero import OutputDevice
        except ImportError as exc:  # pragma: no cover - depends on host
            raise BackendError("gpiozero is not installed (pip install '.[gpio]')") from exc
        self._pin = pin
        self._device = OutputDevice(pin, active_high=active_high, initial_value=False)

    def set(self, on: bool) -> None:
        if on:
            self._device.on()
        else:
            self._device.off()

    def describe(self) -> str:
        return f"gpio {self._pin}"


class SGReadyBackend(Backend):
    name = "sgready"

    def __init__(
        self,
        contact_a: Channel,
        contact_b: Channel,
        *,
        mode_states: dict[Mode, int] | None = None,
    ) -> None:
        states = dict(DEFAULT_MODE_STATES)
        states.update(mode_states or {})
        for mode, state in states.items():
            if state not in SG_READY_STATES:
                raise BackendError(f"SG Ready state for {mode.value} must be 1-4, got {state}")
        self._a = contact_a
        self._b = contact_b
        self._mode_states = states

    def state_for(self, mode: Mode) -> int:
        return self._mode_states[mode]

    def apply(self, mode: Mode) -> None:
        state = self.state_for(mode)
        a_on, b_on = SG_READY_STATES[state]
        self._a.set(a_on)
        self._b.set(b_on)
        log.debug("sgready: mode %s -> state %d (A=%d B=%d)", mode.value, state, a_on, b_on)

    def close(self) -> None:
        # Leave the heat pump in normal operation when the bridge stops.
        try:
            self.apply(Mode.NORMAL)
        except BackendError as exc:
            log.warning("sgready: could not reset contacts on close: %s", exc)

    def describe(self) -> str:
        return f"sgready (A: {self._a.describe()}, B: {self._b.describe()})"
