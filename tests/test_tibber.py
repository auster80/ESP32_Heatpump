from __future__ import annotations

import json
import unittest
from datetime import timedelta

from tibber_heatpump_bridge.tibber import (
    PriceSlot,
    TibberClient,
    TibberError,
    build_slots,
    parse_price_response,
    parse_timestamp,
)

from .helpers import day_start, tibber_document, tibber_entries


class FakeTransport:
    def __init__(self, document: dict | bytes) -> None:
        self.document = document
        self.calls: list[dict] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body)})
        if isinstance(self.document, bytes):
            return self.document
        return json.dumps(self.document).encode()


class TimestampTests(unittest.TestCase):
    def test_parses_tibber_format_with_millis_and_offset(self):
        parsed = parse_timestamp("2025-10-01T00:00:00.000+02:00")
        self.assertEqual(parsed.utcoffset(), timedelta(hours=2))
        self.assertEqual(parsed.hour, 0)

    def test_rejects_naive_timestamp(self):
        with self.assertRaises(ValueError):
            parse_timestamp("2025-10-01T00:00:00")


class BuildSlotsTests(unittest.TestCase):
    def test_quarter_hourly_slots_get_15_minute_ends(self):
        slots = build_slots(tibber_entries([1.0] * 96), default_minutes=15)
        self.assertEqual(len(slots), 96)
        self.assertTrue(all(slot.minutes == 15 for slot in slots))
        self.assertEqual(slots[-1].end, day_start() + timedelta(days=1))

    def test_hourly_slots_are_inferred_from_gaps(self):
        slots = build_slots(tibber_entries([1.0] * 24, minutes=60), default_minutes=15)
        self.assertTrue(all(slot.minutes == 60 for slot in slots))

    def test_unsorted_and_duplicate_entries_are_normalised(self):
        entries = tibber_entries([1.0, 2.0, 3.0])
        shuffled = [entries[2], entries[0], entries[1], dict(entries[1], total=9.0)]
        slots = build_slots(shuffled, default_minutes=15)
        self.assertEqual([s.total for s in slots], [1.0, 9.0, 3.0])

    def test_gap_in_data_does_not_stretch_slot(self):
        entries = tibber_entries([1.0, 2.0])
        entries[1]["startsAt"] = (day_start() + timedelta(hours=5)).isoformat()
        slots = build_slots(entries, default_minutes=15)
        self.assertEqual(slots[0].minutes, 15)

    def test_malformed_entry_raises(self):
        with self.assertRaises(TibberError):
            build_slots([{"startsAt": "nope", "total": 1}], default_minutes=15)

    def test_unknown_level_falls_back_to_normal(self):
        entries = tibber_entries([1.0])
        entries[0]["level"] = "WEIRD"
        self.assertEqual(build_slots(entries, default_minutes=15)[0].level, "NORMAL")


class ParseResponseTests(unittest.TestCase):
    def test_selects_first_home_with_prices_and_combines_days(self):
        today = tibber_entries([1.0] * 96)
        tomorrow = tibber_entries([2.0] * 96, start=day_start() + timedelta(days=1))
        data = tibber_document(today, tomorrow)["data"]
        prices = parse_price_response(data)
        self.assertEqual(prices.home_id, "home-1")
        self.assertEqual(prices.time_zone, "Europe/Oslo")
        self.assertEqual(prices.currency, "NOK")
        self.assertEqual(len(prices.slots), 192)

    def test_unknown_home_id_is_an_error(self):
        data = tibber_document(tibber_entries([1.0]))["data"]
        with self.assertRaises(TibberError) as ctx:
            parse_price_response(data, home_id="other")
        self.assertIn("home-1", str(ctx.exception))

    def test_no_homes_is_an_error(self):
        with self.assertRaises(TibberError):
            parse_price_response({"viewer": {"homes": []}})

    def test_empty_prices_is_an_error(self):
        data = tibber_document([])["data"]
        data["viewer"]["homes"][0]["currentSubscription"]["priceInfo"] = {"today": [], "tomorrow": []}
        with self.assertRaises(TibberError):
            parse_price_response(data, home_id="home-1")


class ClientTests(unittest.TestCase):
    def test_sends_bearer_token_and_resolution(self):
        transport = FakeTransport(tibber_document(tibber_entries([1.0] * 4)))
        client = TibberClient("secret", transport=transport)
        prices = client.fetch_prices(resolution="HOURLY")
        self.assertEqual(len(prices.slots), 4)
        call = transport.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(call["body"]["variables"], {"resolution": "HOURLY"})
        self.assertIn("priceInfo(resolution: $resolution)", call["body"]["query"])

    def test_graphql_errors_become_tibber_error(self):
        transport = FakeTransport({"errors": [{"message": "invalid token"}], "data": None})
        with self.assertRaises(TibberError) as ctx:
            TibberClient("bad", transport=transport).fetch_prices()
        self.assertIn("invalid token", str(ctx.exception))

    def test_invalid_json_becomes_tibber_error(self):
        with self.assertRaises(TibberError):
            TibberClient("x", transport=FakeTransport(b"<html>")).fetch_prices()

    def test_missing_token_rejected(self):
        with self.assertRaises(TibberError):
            TibberClient("")

    def test_invalid_resolution_rejected(self):
        with self.assertRaises(ValueError):
            TibberClient("x", transport=FakeTransport({})).fetch_prices(resolution="DAILY")


class PriceSlotTests(unittest.TestCase):
    def test_contains_is_half_open(self):
        start = day_start()
        slot = PriceSlot(start, start + timedelta(minutes=15), 1.0)
        self.assertTrue(slot.contains(start))
        self.assertFalse(slot.contains(start + timedelta(minutes=15)))


if __name__ == "__main__":
    unittest.main()
