"""Sidecar telemetry helper.

Writes structured events to the pipeline_events table (migration 027 on
the web repo). Mirrors the shape of lib/pipeline-telemetry.ts so the
analytics queries don't have to special-case which writer produced an
event.

Design rules — same as the frontend helper:
  - Fire-and-forget; never block the request path.
  - Swallow every error; a telemetry write failure must never surface
    to the caller.
  - Batched: events accumulate until BATCH_FLUSH_S elapses OR
    BATCH_MAX_SIZE events queue, whichever comes first.

The Supabase client is constructed lazily on the first event so this
module can be imported even when the env vars are unset (CLI runs of
run_real.py don't have Supabase configured).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

BATCH_FLUSH_S = 1.5
BATCH_MAX_SIZE = 32

_queue: list[dict[str, Any]] = []
_lock = threading.Lock()
_flush_timer: threading.Timer | None = None
_supabase = None
_supabase_init_attempted = False


def _get_supabase():
    """Lazily build a service-role client. Returns None if env not set —
    in which case track() becomes a no-op."""
    global _supabase, _supabase_init_attempted
    if _supabase is not None or _supabase_init_attempted:
        return _supabase
    _supabase_init_attempted = True

    url = os.environ.get("SUPABASE_URL") or os.environ.get(
        "NEXT_PUBLIC_SUPABASE_URL"
    )
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None

    try:
        from supabase import create_client  # type: ignore

        _supabase = create_client(url, key)
    except Exception as exc:
        log.warning("telemetry: failed to build supabase client: %s", exc)
        _supabase = None
    return _supabase


def _flush_locked() -> None:
    """Caller must hold _lock."""
    global _flush_timer
    if not _queue:
        return
    batch = _queue.copy()
    _queue.clear()
    if _flush_timer is not None:
        _flush_timer.cancel()
        _flush_timer = None

    sb = _get_supabase()
    if sb is None:
        return  # env not configured; drop silently

    def _do_insert() -> None:
        try:
            sb.table("pipeline_events").insert(batch).execute()
        except Exception as exc:
            log.debug("telemetry insert failed: %s", exc)

    threading.Thread(target=_do_insert, daemon=True).start()


def _schedule_flush_locked() -> None:
    """Caller must hold _lock."""
    global _flush_timer
    if _flush_timer is not None:
        return
    _flush_timer = threading.Timer(BATCH_FLUSH_S, flush)
    _flush_timer.daemon = True
    _flush_timer.start()


def track(
    event: str,
    *,
    sample_id: str | None = None,
    duration_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget event write. Never raises."""
    if not event:
        return
    payload: dict[str, Any] = {
        "event": event,
        "sample_id": sample_id,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "metadata": metadata or {},
        "source": "sidecar",
    }
    with _lock:
        _queue.append(payload)
        if len(_queue) >= BATCH_MAX_SIZE:
            _flush_locked()
        else:
            _schedule_flush_locked()


def flush() -> None:
    """Force-drain the queue now. Always safe to call."""
    with _lock:
        _flush_locked()


class timed:
    """Context manager + decorator for timing a block.

    Usage:
        with timed("auto_panels.generated", sample_id=sid):
            run_sam(...)

    Records duration_ms when the block exits. Captures whether the
    block raised in metadata.outcome.
    """

    def __init__(
        self,
        event: str,
        *,
        sample_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.event = event
        self.sample_id = sample_id
        self.metadata = dict(metadata or {})
        self._start: float | None = None

    def __enter__(self) -> "timed":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed_ms = None
        if self._start is not None:
            elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        meta = dict(self.metadata)
        meta["outcome"] = "error" if exc_type else "ok"
        track(
            self.event,
            sample_id=self.sample_id,
            duration_ms=elapsed_ms,
            metadata=meta,
        )
