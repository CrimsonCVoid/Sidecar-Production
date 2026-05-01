"""SAM auto-panel service — FastAPI entrypoint.

This is a SEPARATE FastAPI app from roof_pipeline.api.main:app. The two
processes share the roof_pipeline package source, but the SAM service
runs on a GPU host, owns its own venv, listens on its own port (8001),
and never imports the legacy api/* routers.

Surface (Phase 2):
  POST /api/v2/auto-panels/{sample_id}  — kick off generation; 202
  GET  /health                          — liveness probe

Auth: only X-Internal-API-Key. There is no browser path here — the web
v2 proxy is the only legitimate caller.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from roof_pipeline import telemetry

from .service import MODEL_VERSION, generate_auto_panels

log = logging.getLogger(__name__)

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")

app = FastAPI(
    title="My Metal Roofer SAM Service",
    version="0.1.0",
    description=(
        "Auto-panel suggestions backed by Segment Anything (ViT-H). "
        "Phase 2 of the pipeline upgrade."
    ),
)


# ---------------------------------------------------------------------------
# Auth — single shared-secret gate. No browser path on this service so we
# don't carry the JWT half of the deps.py dual-mode.
# ---------------------------------------------------------------------------


def require_internal_key(
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-API-Key"),
) -> None:
    if not INTERNAL_API_KEY:
        # Refuse to start serving authenticated traffic when the secret
        # isn't even configured — fail closed instead of fail open.
        raise HTTPException(
            status_code=503,
            detail="SAM service is not configured (INTERNAL_API_KEY missing)",
        )
    if x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe.

    Reports the model version so the web proxy can detect SAM model
    drift without a separate config endpoint. Does NOT touch the model
    — keep this fast (no GPU work).
    """
    return {
        "status": "ok",
        "model_version": MODEL_VERSION,
        "internal_api_key_configured": bool(INTERNAL_API_KEY),
    }


@app.post("/api/v2/auto-panels/{sample_id}", dependencies=[Depends(require_internal_key)])
async def kick_off_generation(
    sample_id: str,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Schedule auto-panel generation for `sample_id`.

    Returns 202 immediately. The caller should poll training_samples row
    via Supabase or via the web proxy's GET endpoint until
    `auto_panels` is non-null. Generation takes ~30-60s on the A100,
    longer on CPU fallback.
    """
    telemetry.track(
        "auto_panels.requested",
        sample_id=sample_id,
        metadata={"source": "sam_service"},
    )
    background_tasks.add_task(_run_safe, sample_id)
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "sample_id": sample_id,
            "model_version": MODEL_VERSION,
        },
    )


def _run_safe(sample_id: str) -> None:
    """Background-task wrapper that swallows every exception so a thrown
    error never escapes to the FastAPI worker (where it'd be logged but
    invisible to the client). Telemetry covers the failure paths.
    """
    try:
        result = generate_auto_panels(sample_id)
        log.info("sam_service: %s -> %s", sample_id, result)
    except Exception as exc:  # noqa: BLE001
        log.exception("sam_service: unhandled error for %s: %s", sample_id, exc)
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "unhandled_exception", "exception": type(exc).__name__},
        )


# ---------------------------------------------------------------------------
# Logging — minimal compared to the existing api/middleware.py. The SAM
# service has one route; structured per-request logging would be noise.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("SAM_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
