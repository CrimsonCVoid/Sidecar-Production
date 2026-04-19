"""Structured JSON logging middleware for every HTTP request (OBSERVABILITY-01a)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import Request

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON log formatter
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


# ---------------------------------------------------------------------------
# HTTP middleware
# ---------------------------------------------------------------------------

async def structured_logging_middleware(request: Request, call_next):
    """Log every HTTP request with trace_id, latency, endpoint, and status.

    Attaches *trace_id* to ``request.state`` so downstream handlers can
    reference it (e.g. for error responses).  Emits a single structured
    JSON log line after the response completes.
    """
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    start = time.perf_counter()

    response = await call_next(request)

    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    sample_id = getattr(request.state, "sample_id", None)

    log_entry = {
        "trace_id": trace_id,
        "sample_id": sample_id,
        "endpoint": request.url.path,
        "method": request.method,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "error_type": None,
    }
    log.info(json.dumps(log_entry))

    response.headers["X-Trace-ID"] = trace_id
    return response


# ---------------------------------------------------------------------------
# Logging configuration helper
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """Set up the root logger with the JSON formatter at INFO level.

    Called once at application startup from ``main.py``.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers when module is re-imported (e.g. tests)
    if not any(isinstance(h, logging.StreamHandler) and
               isinstance(h.formatter, JSONFormatter) for h in root.handlers):
        root.addHandler(handler)
