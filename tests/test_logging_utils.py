from __future__ import annotations

import logging

from shared.logging_utils import suppress_tornado_websocket_errors


TORNADO_LOGGERS = ("tornado.application", "tornado.general", "tornado.access")


def _restore(previous: dict[str, tuple[int, bool]]) -> None:
    for name, (level, propagate) in previous.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = propagate


def test_suppress_tornado_websocket_errors_defaults_to_critical() -> None:
    previous = {name: (logging.getLogger(name).level, logging.getLogger(name).propagate) for name in TORNADO_LOGGERS}
    try:
        suppress_tornado_websocket_errors()

        for name in TORNADO_LOGGERS:
            logger = logging.getLogger(name)
            assert logger.level == logging.CRITICAL
            assert logger.propagate is False
    finally:
        _restore(previous)


def test_suppress_tornado_websocket_errors_accepts_custom_level() -> None:
    previous = {name: (logging.getLogger(name).level, logging.getLogger(name).propagate) for name in TORNADO_LOGGERS}
    try:
        suppress_tornado_websocket_errors(logging.WARNING)

        for name in TORNADO_LOGGERS:
            assert logging.getLogger(name).level == logging.WARNING
    finally:
        _restore(previous)
