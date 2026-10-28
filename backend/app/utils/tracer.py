"""Request-scoped trace id propagation via contextvars.

The trace id is generated once per request in the logging middleware and is
read by the structlog processor so that every log line within a request shares
the same ``trace_id``. It is also returned to the client in the response
 envelope / ``x-trace-id`` header for correlation.
"""
from __future__ import annotations

import contextvars
import uuid

_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("zg_trace_id", default="-")


def set_trace_id(trace_id: str | None = None) -> str:
    """Set the current trace id (generating one if not provided)."""
    tid = trace_id or uuid.uuid4().hex
    _TRACE_ID.set(tid)
    return tid


def get_trace_id() -> str:
    """Return the current trace id (falls back to '-' outside a request)."""
    return _TRACE_ID.get()
