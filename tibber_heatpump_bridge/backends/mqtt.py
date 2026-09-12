"""MQTT backend: publishes the mode (or a per-mode payload) to one topic.

Requires ``paho-mqtt`` (``pip install '.[mqtt]'``). Handy when Home Assistant,
Node-RED or an ESPHome relay board does the last hop to the heat pump.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..schedule import Mode
from .base import Backend, BackendError

log = logging.getLogger(__name__)


class MqttBackend(Backend):
    name = "mqtt"

    def __init__(
        self,
        host: str,
        *,
        port: int = 1883,
        topic: str = "heatpump/mode",
        payloads: dict[Mode, str] | None = None,
        username: str | None = None,
        password: str | None = None,
        retain: bool = True,
        qos: int = 1,
        timeout: float = 10.0,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._topic = topic
        self._payloads = payloads or {}
        self._username = username
        self._password = password
        self._retain = retain
        self._qos = qos
        self._timeout = timeout
        self._client_factory = client_factory or self._default_factory
        self._client: Any | None = None

    def _default_factory(self) -> Any:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise BackendError("paho-mqtt is not installed (pip install '.[mqtt]')") from exc
        api_version = getattr(mqtt, "CallbackAPIVersion", None)
        client = mqtt.Client(api_version.VERSION2) if api_version else mqtt.Client()
        if self._username:
            client.username_pw_set(self._username, self._password)
        return client

    def _connected_client(self) -> Any:
        if self._client is None:
            client = self._client_factory()
            try:
                client.connect(self._host, self._port, keepalive=60)
            except OSError as exc:
                raise BackendError(f"cannot connect to MQTT {self._host}:{self._port}: {exc}") from exc
            if hasattr(client, "loop_start"):
                client.loop_start()
            self._client = client
        return self._client

    def payload_for(self, mode: Mode) -> str:
        return self._payloads.get(mode, mode.value)

    def apply(self, mode: Mode) -> None:
        client = self._connected_client()
        info = client.publish(self._topic, self.payload_for(mode), qos=self._qos, retain=self._retain)
        if hasattr(info, "wait_for_publish"):
            info.wait_for_publish(timeout=self._timeout)
        rc = getattr(info, "rc", 0)
        if rc not in (0, None):
            self.close()
            raise BackendError(f"mqtt publish to {self._topic} failed with rc={rc}")
        log.debug("mqtt: %s <- %s", self._topic, self.payload_for(mode))

    def check(self) -> None:
        self._connected_client()

    def close(self) -> None:
        if self._client is None:
            return
        client, self._client = self._client, None
        try:
            if hasattr(client, "loop_stop"):
                client.loop_stop()
            client.disconnect()
        except OSError:  # pragma: no cover - best effort
            pass

    def describe(self) -> str:
        return f"mqtt {self._host}:{self._port} topic {self._topic}"
