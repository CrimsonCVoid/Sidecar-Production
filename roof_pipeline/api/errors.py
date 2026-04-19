"""Browser error capture endpoint for OBSERVABILITY-01b.

Receives structured browser error payloads from the Next.js frontend
and logs them as structured JSON lines using the existing logging
infrastructure.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


class BrowserError(BaseModel):
    """Payload shape for browser-side error reports."""

    timestamp: str
    page: str
    error_type: str
    message: str
    stack: str | None = None
    user_agent: str
    sample_id: str | None = None


@router.post("")
async def receive_browser_error(body: BrowserError, request: Request):
    """Log a browser error as a structured JSON line (fire-and-forget)."""
    log.warning(
        "browser_error sample_id=%s type=%s page=%s message=%s",
        body.sample_id,
        body.error_type,
        body.page,
        body.message,
    )
    return {"status": "logged"}
