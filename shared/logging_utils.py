"""Helpers to adjust logging noise from third-party libraries."""

from __future__ import annotations

import logging
from typing import Iterable


def suppress_tornado_websocket_errors(level: int = logging.CRITICAL) -> None:
    """Reduce noisy Tornado WebSocketClosedError logs when users navigate away."""
    targets: Iterable[str] = (
        "tornado.application",
        "tornado.general",
        "tornado.access",
    )
    for name in targets:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False
