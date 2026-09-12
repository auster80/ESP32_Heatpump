from __future__ import annotations

import logging

from ..schedule import Mode
from .base import Backend

log = logging.getLogger(__name__)


class DryRunBackend(Backend):
    """Logs what would be sent. Also records modes for tests."""

    name = "dryrun"

    def __init__(self) -> None:
        self.applied: list[Mode] = []

    def apply(self, mode: Mode) -> None:
        self.applied.append(mode)
        log.info("DRY RUN: heat pump mode -> %s", mode.value)
