"""Structured JSON logging via structlog with request-level trace_id binding."""
from __future__ import annotations

import logging
import sys

import structlog

from app.utils.tracer import get_trace_id


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit JSON lines carrying the trace_id."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            lambda _logger, _method, event_dict: {**event_dict, "trace_id": get_trace_id()},
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
