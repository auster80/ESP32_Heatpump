"""Generic HTTP backend: one or more requests per mode.

Covers Shelly/Tasmota relays, Home Assistant webhooks, or any device with a
REST endpoint. Example (Shelly Gen2)::

    [backend.http.actions]
    block  = [{ url = "http://shelly/rpc/Switch.Set?id=0&on=true" }]
    normal = [{ url = "http://shelly/rpc/Switch.Set?id=0&on=false" }]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..schedule import Mode
from ._http import Sender, send_request
from .base import Backend

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpAction:
    url: str
    method: str = "GET"
    body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


class HttpBackend(Backend):
    name = "http"

    def __init__(
        self,
        actions: dict[Mode, list[HttpAction]],
        *,
        timeout: float = 10.0,
        sender: Sender | None = None,
    ) -> None:
        self._actions = actions
        self._timeout = timeout
        self._send = sender or send_request

    def apply(self, mode: Mode) -> None:
        actions = self._actions.get(mode, [])
        if not actions:
            log.debug("http backend: no actions configured for mode %s", mode.value)
            return
        for action in actions:
            body = action.body.encode() if action.body is not None else None
            status, _ = self._send(action.url, action.method, body, action.headers, self._timeout)
            log.debug("%s %s -> %s", action.method, action.url, status)

    def describe(self) -> str:
        configured = ", ".join(f"{m.value}:{len(a)}" for m, a in self._actions.items() if a)
        return f"http ({configured or 'no actions'})"
