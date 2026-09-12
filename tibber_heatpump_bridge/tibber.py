"""Minimal Tibber GraphQL client (standard library only).

Only the price curve is needed here. The query mirrors what Tibber's own
libraries request: ``priceInfo(resolution: QUARTER_HOURLY)`` with ``today`` and
``tomorrow``. Tomorrow's prices normally appear around 13:00 local time.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from . import __version__

log = logging.getLogger(__name__)

API_URL = "https://api.tibber.com/v1-beta/gql"
RESOLUTIONS = ("QUARTER_HOURLY", "HOURLY")
DEFAULT_SLOT_MINUTES = {"QUARTER_HOURLY": 15, "HOURLY": 60}
KNOWN_SLOT_MINUTES = (15, 30, 60)
API_URL_ENV = "TIBBER_API_URL"
PRICE_LEVELS = ("VERY_CHEAP", "CHEAP", "NORMAL", "EXPENSIVE", "VERY_EXPENSIVE")

PRICE_QUERY = """
query HeatPumpBridgePrices($resolution: PriceInfoResolution) {
  viewer {
    homes {
      id
      appNickname
      timeZone
      currentSubscription {
        priceInfo(resolution: $resolution) {
          today { total startsAt level currency }
          tomorrow { total startsAt level currency }
        }
      }
    }
  }
}
"""

# (url, headers, body, timeout) -> raw response bytes
Transport = Callable[[str, dict[str, str], bytes, float], bytes]


class TibberError(RuntimeError):
    """Raised for network, authentication and response-format problems."""


@dataclass(frozen=True)
class PriceSlot:
    """One price interval. ``start``/``end`` are timezone-aware."""

    start: datetime
    end: datetime
    total: float
    level: str = "NORMAL"
    currency: str = ""

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    def contains(self, when: datetime) -> bool:
        return self.start <= when < self.end


@dataclass
class PriceData:
    home_id: str
    time_zone: str
    slots: list[PriceSlot]
    currency: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def last_end(self) -> datetime | None:
        return self.slots[-1].end if self.slots else None


def _urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class TibberClient:
    def __init__(
        self,
        token: str,
        *,
        url: str | None = None,
        timeout: float = 20.0,
        transport: Transport | None = None,
    ) -> None:
        if not token:
            raise TibberError("Tibber API token is missing (set [tibber].token or TIBBER_TOKEN)")
        self._token = token
        # TIBBER_API_URL lets tests and local mocks redirect the client.
        self._url = url or os.environ.get(API_URL_ENV) or API_URL
        self._timeout = timeout
        self._transport = transport or _urllib_transport

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": f"tibber-heatpump-bridge/{__version__}",
        }
        try:
            raw = self._transport(self._url, headers, payload, self._timeout)
        except urllib.error.HTTPError as exc:
            raise TibberError(f"HTTP {exc.code} from Tibber API") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise TibberError(f"cannot reach Tibber API: {exc}") from exc
        try:
            document = json.loads(raw)
        except ValueError as exc:
            raise TibberError("Tibber API returned invalid JSON") from exc
        if not isinstance(document, dict):
            raise TibberError("Tibber API returned an unexpected document")
        if document.get("errors"):
            messages = "; ".join(str(err.get("message", err)) for err in document["errors"])
            raise TibberError(f"Tibber API error: {messages}")
        data = document.get("data")
        if not isinstance(data, dict):
            raise TibberError("Tibber API response has no data")
        return data

    def fetch_prices(self, *, home_id: str | None = None, resolution: str = "QUARTER_HOURLY") -> PriceData:
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS}, got {resolution!r}")
        data = self.query(PRICE_QUERY, {"resolution": resolution})
        prices = parse_price_response(data, home_id=home_id, resolution=resolution)
        log.debug(
            "fetched %d price slots for home %s (%s)",
            len(prices.slots),
            prices.home_id,
            prices.time_zone,
        )
        return prices


def parse_price_response(
    data: dict[str, Any], *, home_id: str | None = None, resolution: str = "QUARTER_HOURLY"
) -> PriceData:
    homes = (data.get("viewer") or {}).get("homes") or []
    if not homes:
        raise TibberError("no homes on this Tibber account")
    if home_id:
        home = next((h for h in homes if h.get("id") == home_id), None)
        if home is None:
            available = ", ".join(str(h.get("id")) for h in homes)
            raise TibberError(f"home {home_id} not found; available homes: {available}")
    else:
        home = next((h for h in homes if (h.get("currentSubscription") or {}).get("priceInfo")), None)
        if home is None:
            raise TibberError("no home with an active subscription and price info")
    price_info = (home.get("currentSubscription") or {}).get("priceInfo") or {}
    raw = list(price_info.get("today") or []) + list(price_info.get("tomorrow") or [])
    slots = build_slots(raw, default_minutes=DEFAULT_SLOT_MINUTES[resolution])
    if not slots:
        raise TibberError(f"Tibber returned no prices for home {home.get('id')}")
    currency = next((slot.currency for slot in slots if slot.currency), "")
    return PriceData(
        home_id=str(home.get("id") or ""),
        time_zone=str(home.get("timeZone") or "UTC"),
        slots=slots,
        currency=currency,
    )


def parse_timestamp(value: str) -> datetime:
    """Parse Tibber's ``startsAt`` (e.g. ``2025-10-01T00:00:00.000+02:00``)."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no UTC offset")
    return parsed


def build_slots(raw: list[dict[str, Any]], *, default_minutes: int) -> list[PriceSlot]:
    """Turn Tibber price entries into contiguous slots with an explicit end time.

    The slot length is inferred from the most common gap between consecutive
    entries, so both hourly and quarter-hourly data work; the last slot uses
    that inferred length.
    """
    points: dict[datetime, tuple[float, str, str]] = {}
    for entry in raw:
        try:
            start = parse_timestamp(entry["startsAt"])
            total = float(entry["total"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TibberError(f"malformed price entry {entry!r}") from exc
        level = str(entry.get("level") or "NORMAL")
        if level not in PRICE_LEVELS:
            level = "NORMAL"
        points[start] = (total, level, str(entry.get("currency") or ""))

    starts = sorted(points)
    gaps = {
        int((later - earlier).total_seconds() // 60)
        for earlier, later in zip(starts, starts[1:], strict=False)
    }
    # The smallest gap that matches a known Tibber resolution is the slot length;
    # larger gaps are holes in the data, not longer slots.
    known = [gap for gap in gaps if gap in KNOWN_SLOT_MINUTES]
    typical = min(known) if known else default_minutes

    slots: list[PriceSlot] = []
    for index, start in enumerate(starts):
        total, level, currency = points[start]
        end = start + timedelta(minutes=typical)
        if index + 1 < len(starts):
            following = starts[index + 1]
            gap_minutes = (following - start).total_seconds() / 60
            if 0 < gap_minutes <= typical * 2:
                end = following
        slots.append(PriceSlot(start=start, end=end, total=total, level=level, currency=currency))
    return slots
