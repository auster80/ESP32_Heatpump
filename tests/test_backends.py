from __future__ import annotations

import unittest

from tibber_heatpump_bridge.backends import BackendError, build_backend
from tibber_heatpump_bridge.backends.dryrun import DryRunBackend
from tibber_heatpump_bridge.backends.http import HttpAction, HttpBackend
from tibber_heatpump_bridge.backends.modbus import ModbusBackend, ModbusWrite
from tibber_heatpump_bridge.backends.mqtt import MqttBackend
from tibber_heatpump_bridge.backends.sgready import SG_READY_STATES, HttpChannel, SGReadyBackend
from tibber_heatpump_bridge.schedule import Mode


class RecordingSender:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple] = []
        self.fail = fail

    def __call__(self, url, method, body, headers, timeout):
        if self.fail:
            raise BackendError(f"{method} {url} failed")
        self.calls.append((url, method, body, headers))
        return 200, b"ok"


class FakeChannel:
    def __init__(self) -> None:
        self.states: list[bool] = []

    def set(self, on: bool) -> None:
        self.states.append(on)

    def describe(self) -> str:
        return "fake"


class FakeModbusClient:
    def __init__(self, keyword: str = "device_id", fail_connect: bool = False) -> None:
        self.keyword = keyword
        self.fail_connect = fail_connect
        self.connected = False
        self.writes: list[tuple] = []
        self.closed = False

    def connect(self) -> bool:
        self.connected = not self.fail_connect
        return self.connected

    def _check(self, kwargs):
        if set(kwargs) != {self.keyword}:
            raise TypeError(f"unexpected keyword {set(kwargs)}")

    def write_register(self, address, value, **kwargs):
        self._check(kwargs)
        self.writes.append(("holding", address, value, kwargs[self.keyword]))
        return FakeResult()

    def write_coil(self, address, value, **kwargs):
        self._check(kwargs)
        self.writes.append(("coil", address, value, kwargs[self.keyword]))
        return FakeResult()

    def close(self) -> None:
        self.closed = True
        self.connected = False


class FakeResult:
    def __init__(self, error: bool = False) -> None:
        self.error = error

    def isError(self) -> bool:  # noqa: N802 - pymodbus naming
        return self.error


class FakeMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple] = []
        self.connected_to = None
        self.loop = False

    def connect(self, host, port, keepalive=60):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop = True

    def loop_stop(self):
        self.loop = False

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return FakePublishInfo()

    def disconnect(self):
        self.connected_to = None


class FakePublishInfo:
    rc = 0

    def wait_for_publish(self, timeout=None):
        return None


class SGReadyTests(unittest.TestCase):
    def test_states_follow_bwp_definition(self):
        self.assertEqual(SG_READY_STATES[1], (True, False))
        self.assertEqual(SG_READY_STATES[2], (False, False))
        self.assertEqual(SG_READY_STATES[3], (False, True))
        self.assertEqual(SG_READY_STATES[4], (True, True))

    def test_modes_drive_both_contacts(self):
        a, b = FakeChannel(), FakeChannel()
        backend = SGReadyBackend(a, b)
        for mode in (Mode.BLOCK, Mode.REDUCE, Mode.NORMAL, Mode.BOOST, Mode.FORCE):
            backend.apply(mode)
        self.assertEqual(a.states, [True, False, False, False, True])
        self.assertEqual(b.states, [False, False, False, True, True])

    def test_custom_mode_state_mapping(self):
        a, b = FakeChannel(), FakeChannel()
        backend = SGReadyBackend(a, b, mode_states={Mode.BLOCK: 2, Mode.REDUCE: 1})
        self.assertEqual(backend.state_for(Mode.BLOCK), 2)
        self.assertEqual(backend.state_for(Mode.REDUCE), 1)
        self.assertEqual(backend.state_for(Mode.FORCE), 4)

    def test_invalid_state_rejected(self):
        with self.assertRaises(BackendError):
            SGReadyBackend(FakeChannel(), FakeChannel(), mode_states={Mode.BLOCK: 5})

    def test_close_returns_to_normal(self):
        a, b = FakeChannel(), FakeChannel()
        backend = SGReadyBackend(a, b)
        backend.apply(Mode.FORCE)
        backend.close()
        self.assertEqual((a.states[-1], b.states[-1]), (False, False))

    def test_http_channel_hits_on_and_off_urls(self):
        sender = RecordingSender()
        channel = HttpChannel("http://relay/on", "http://relay/off", sender=sender)
        channel.set(True)
        channel.set(False)
        self.assertEqual([c[0] for c in sender.calls], ["http://relay/on", "http://relay/off"])


class HttpBackendTests(unittest.TestCase):
    def test_sends_configured_requests(self):
        sender = RecordingSender()
        backend = HttpBackend(
            {
                Mode.BOOST: [
                    HttpAction("http://x/boost"),
                    HttpAction("http://x/hook", method="POST", body='{"a":1}', headers={"X": "1"}),
                ]
            },
            sender=sender,
        )
        backend.apply(Mode.BOOST)
        backend.apply(Mode.NORMAL)  # nothing configured -> no call
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(sender.calls[1], ("http://x/hook", "POST", b'{"a":1}', {"X": "1"}))

    def test_failure_propagates(self):
        backend = HttpBackend({Mode.BLOCK: [HttpAction("http://x")]}, sender=RecordingSender(fail=True))
        with self.assertRaises(BackendError):
            backend.apply(Mode.BLOCK)


class ModbusBackendTests(unittest.TestCase):
    def _backend(self, client: FakeModbusClient) -> ModbusBackend:
        return ModbusBackend(
            "hp.local",
            {
                Mode.REDUCE: [ModbusWrite(100, 0, "coil"), ModbusWrite(30, -2)],
                Mode.BLOCK: [ModbusWrite(100, 1, "coil")],
            },
            unit=7,
            client_factory=lambda: client,
        )

    def test_writes_registers_and_coils_with_twos_complement(self):
        client = FakeModbusClient()
        self._backend(client).apply(Mode.REDUCE)
        self.assertEqual(client.writes, [("coil", 100, False, 7), ("holding", 30, 0xFFFE, 7)])

    def test_supports_older_pymodbus_keyword(self):
        client = FakeModbusClient(keyword="slave")
        self._backend(client).apply(Mode.BLOCK)
        self.assertEqual(client.writes, [("coil", 100, True, 7)])

    def test_connect_failure(self):
        backend = self._backend(FakeModbusClient(fail_connect=True))
        with self.assertRaises(BackendError):
            backend.apply(Mode.BLOCK)

    def test_error_result_raises_and_closes(self):
        client = FakeModbusClient()
        client.write_coil = lambda *a, **k: FakeResult(error=True)  # type: ignore[assignment]
        backend = self._backend(client)
        with self.assertRaises(BackendError):
            backend.apply(Mode.BLOCK)
        self.assertTrue(client.closed)

    def test_write_validation(self):
        with self.assertRaises(ValueError):
            ModbusWrite(1, 1, "input")
        with self.assertRaises(ValueError):
            ModbusWrite(1, 70000)


class MqttBackendTests(unittest.TestCase):
    def test_publishes_payload_with_retain(self):
        client = FakeMqttClient()
        backend = MqttBackend(
            "broker", topic="hp/mode", payloads={Mode.BLOCK: "1"}, client_factory=lambda: client
        )
        backend.apply(Mode.BLOCK)
        backend.apply(Mode.BOOST)
        self.assertEqual(client.connected_to, ("broker", 1883))
        self.assertEqual(client.published, [("hp/mode", "1", 1, True), ("hp/mode", "boost", 1, True)])
        backend.close()
        self.assertIsNone(client.connected_to)


class BuildBackendTests(unittest.TestCase):
    def test_dryrun(self):
        self.assertIsInstance(build_backend("dryrun"), DryRunBackend)

    def test_unknown_type(self):
        with self.assertRaises(BackendError):
            build_backend("telepathy")

    def test_sgready_from_options(self):
        backend = build_backend(
            "sgready",
            {
                "modes": {"reduce": 1},
                "a": {"type": "http", "on": "http://a/on", "off": "http://a/off"},
                "b": {"type": "http", "on": "http://b/on", "off": "http://b/off"},
            },
        )
        self.assertIsInstance(backend, SGReadyBackend)
        self.assertEqual(backend.state_for(Mode.REDUCE), 1)

    def test_sgready_requires_urls(self):
        with self.assertRaises(BackendError):
            build_backend("sgready", {"a": {"on": "x"}, "b": {"on": "x", "off": "y"}})

    def test_http_from_options(self):
        backend = build_backend("http", {"actions": {"boost": [{"url": "http://x", "method": "post"}]}})
        self.assertIsInstance(backend, HttpBackend)

    def test_http_rejects_unknown_mode(self):
        with self.assertRaises(BackendError):
            build_backend("http", {"actions": {"turbo": [{"url": "http://x"}]}})

    def test_modbus_from_options(self):
        backend = build_backend(
            "modbus",
            {"host": "1.2.3.4", "writes": {"block": [{"address": 1, "value": 1, "kind": "coil"}]}},
        )
        self.assertIsInstance(backend, ModbusBackend)

    def test_modbus_requires_host_and_writes(self):
        with self.assertRaises(BackendError):
            build_backend("modbus", {"writes": {"block": []}})
        with self.assertRaises(BackendError):
            build_backend("modbus", {"host": "x"})

    def test_mqtt_from_options(self):
        backend = build_backend("mqtt", {"host": "b", "payloads": {"block": 1}})
        self.assertIsInstance(backend, MqttBackend)
        self.assertEqual(backend.payload_for(Mode.BLOCK), "1")


if __name__ == "__main__":
    unittest.main()
