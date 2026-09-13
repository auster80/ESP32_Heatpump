"""Fake Tibber GraphQL endpoint for smoke-testing the CLI without a real token.

Serves two days of quarter-hourly prices with a cheap night and morning /
evening peaks for one home in Europe/Oslo. Run it, point the bridge at it and
use the token ``smoke-token``::

    python tools/fake_tibber.py &                      # listens on 127.0.0.1:8765
    export TIBBER_API_URL=http://127.0.0.1:8765/gql
    printf '[tibber]\\ntoken = "smoke-token"\\n' > /tmp/smoke.toml
    tibber-heatpump-bridge -c /tmp/smoke.toml plan
    tibber-heatpump-bridge -c /tmp/smoke.toml curve-plan --indoor 21 --outdoor 2

Any other token gets the same ``invalid token`` error the real API returns.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Oslo")
TOKEN = "smoke-token"
PORT = int(os.environ.get("FAKE_TIBBER_PORT", "8765"))


def prices_for(day: datetime) -> list[dict]:
    entries = []
    for i in range(96):
        start = day + timedelta(minutes=15 * i)
        hour = start.hour + start.minute / 60
        peak = 0.7 if 7 <= hour < 9 or 17 <= hour < 20 else 0.0
        total = 0.6 + 0.5 * math.sin((hour - 3) / 24 * 2 * math.pi) + peak
        if total > 1.5:
            level = "VERY_EXPENSIVE"
        elif total > 1.1:
            level = "EXPENSIVE"
        elif total < 0.4:
            level = "CHEAP"
        else:
            level = "NORMAL"
        entries.append(
            {
                "total": round(total, 4),
                "startsAt": start.isoformat(timespec="milliseconds"),
                "level": level,
                "currency": "NOK",
            }
        )
    return entries


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            document = {"errors": [{"message": "invalid token"}], "data": None}
        else:
            today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            document = {
                "data": {
                    "viewer": {
                        "homes": [
                            {
                                "id": "smoke-home",
                                "appNickname": "Smoke",
                                "timeZone": "Europe/Oslo",
                                "currentSubscription": {
                                    "priceInfo": {
                                        "today": prices_for(today),
                                        "tomorrow": prices_for(today + timedelta(days=1)),
                                    }
                                },
                            }
                        ]
                    }
                }
            }
            sys.stderr.write(f"query variables={body.get('variables')}\n")
        payload = json.dumps(document).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    sys.stderr.write(f"fake Tibber API on http://127.0.0.1:{PORT}/gql (token {TOKEN})\n")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
