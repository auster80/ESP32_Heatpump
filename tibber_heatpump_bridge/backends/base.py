from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..schedule import Mode

log = logging.getLogger(__name__)


class BackendError(RuntimeError):
    """Raised when a mode could not be pushed to the heat pump."""


class Backend(ABC):
    """Pushes a :class:`Mode` to the heat pump. Implementations must be idempotent."""

    name: str = "base"

    @abstractmethod
    def apply(self, mode: Mode) -> None:
        """Set the heat pump to ``mode``. Raise :class:`BackendError` on failure."""

    def check(self) -> None:
        """Optional connectivity check used by the ``check`` command."""
        return None

    def close(self) -> None:
        """Release connections. Safe to call more than once."""
        return None

    def describe(self) -> str:
        return self.name
