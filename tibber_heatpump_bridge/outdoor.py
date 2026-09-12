"""Optional outdoor temperature source: any HTTP endpoint returning JSON.

``json_path`` is a dotted path into the document, e.g. ``state`` for a Home
Assistant entity (``/api/states/sensor.outdoor``) or ``tmp.tC`` for a Shelly
H&T. Failures are logged and yield ``None``; the plan then simply skips the
outdoor-temperature guard.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from .backends._http import Sender, send_request
from .backends.base import BackendError
from .config import OutdoorConfig

log = logging.getLogger(__name__)

TemperatureFetcher = Callable[[], float | None]


def extract_path(document: Any, path: str) -> Any:
    current = document
    for part in [p for p in path.split(".") if p]:
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(part)
    return current


def fetch_outdoor_temperature(cfg: OutdoorConfig, *, sender: Sender | None = None) -> float | None:
    send = sender or send_request
    try:
        _, body = send(cfg.url, "GET", None, cfg.headers, cfg.timeout_seconds)
        value = extract_path(json.loads(body), cfg.json_path)
        return float(value)
    except BackendError as exc:
        log.warning("outdoor temperature unavailable: %s", exc)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        log.warning("outdoor temperature response not understood (%s at %r)", exc, cfg.json_path)
    return None


def make_fetcher(cfg: OutdoorConfig | None, *, sender: Sender | None = None) -> TemperatureFetcher | None:
    if cfg is None:
        return None
    return lambda: fetch_outdoor_temperature(cfg, sender=sender)
