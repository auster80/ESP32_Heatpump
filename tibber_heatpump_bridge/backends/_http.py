from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable

from .base import BackendError

# (url, method, body, headers, timeout) -> (status, body)
Sender = Callable[[str, str, bytes | None, dict[str, str], float], tuple[int, bytes]]


def send_request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        raise BackendError(f"{method.upper()} {url} -> HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise BackendError(f"{method.upper()} {url} failed: {exc}") from exc
