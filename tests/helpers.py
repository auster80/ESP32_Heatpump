from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tibber_heatpump_bridge.tibber import PriceSlot

TZ = ZoneInfo("Europe/Oslo")


def day_start(day: str = "2026-09-12") -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=TZ)


def make_slots(prices: list[float], *, start: datetime | None = None, minutes: int = 60) -> list[PriceSlot]:
    """Contiguous slots starting at local midnight with the given prices."""
    begin = start or day_start()
    slots = []
    for index, price in enumerate(prices):
        s = begin + timedelta(minutes=index * minutes)
        slots.append(PriceSlot(start=s, end=s + timedelta(minutes=minutes), total=price, currency="NOK"))
    return slots


def tibber_entries(prices: list[float], *, start: datetime | None = None, minutes: int = 15) -> list[dict]:
    begin = start or day_start()
    return [
        {
            "total": price,
            "startsAt": (begin + timedelta(minutes=index * minutes)).isoformat(timespec="milliseconds"),
            "level": "NORMAL",
            "currency": "NOK",
        }
        for index, price in enumerate(prices)
    ]


def tibber_document(
    today: list[dict], tomorrow: list[dict] | None = None, *, home_id: str = "home-1"
) -> dict:
    return {
        "data": {
            "viewer": {
                "homes": [
                    {
                        "id": home_id,
                        "appNickname": "Test",
                        "timeZone": "Europe/Oslo",
                        "currentSubscription": {"priceInfo": {"today": today, "tomorrow": tomorrow or []}},
                    }
                ]
            }
        }
    }
