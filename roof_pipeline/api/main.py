"""FastAPI application factory: mounts routers, middleware, and CORS (D-01, D-02)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import router as errors_router
from .labels import router as labels_router
from .middleware import configure_logging, structured_logging_middleware
from .pipeline import router as pipeline_router
from .schemas import ErrorResponse
from .snap import router as snap_router
from .solar import router as solar_router

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Logging setup (once per process)
# ---------------------------------------------------------------------------
configure_logging()

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="My Metal Roofer Pipeline API",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Settings (graceful fallback when .env is absent)
# ---------------------------------------------------------------------------
_cors_origins: list[str] = ["http://localhost:3000"]

try:
    _settings = Settings()
    _cors_origins = _settings.cors_origins
except Exception:
    log.warning(
        "Could not load Settings (missing .env or env vars) "
        "-- using default CORS origins. "
        "Supabase-dependent endpoints will fail until credentials are provided.",
    )

# ---------------------------------------------------------------------------
# CORS (T-04-01)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Structured logging middleware (OBSERVABILITY-01a)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Delegate to the structured logging middleware."""
    return await structured_logging_middleware(request, call_next)


# ---------------------------------------------------------------------------
# Routers (D-02)
# ---------------------------------------------------------------------------
app.include_router(snap_router, prefix="/api/snap", tags=["snap"])
app.include_router(pipeline_router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(labels_router, prefix="/api/labels", tags=["labels"])
app.include_router(errors_router, prefix="/api/errors", tags=["errors"])
app.include_router(solar_router, prefix="/api/solar", tags=["solar"])


# ---------------------------------------------------------------------------
# Global exception handlers (T-04-03 -- no traceback leak)
# ---------------------------------------------------------------------------
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Return 422 for input validation errors."""
    trace_id = getattr(request.state, "trace_id", None)
    log.exception("ValueError in %s", request.url.path)
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_type="ValueError",
            message=str(exc),
            trace_id=trace_id,
        ).model_dump(),
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    """Return 500 for runtime / algorithmic failures."""
    trace_id = getattr(request.state, "trace_id", None)
    log.exception("RuntimeError in %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_type="RuntimeError",
            message=str(exc),
            trace_id=trace_id,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all -- return 500 with generic message, log full traceback."""
    trace_id = getattr(request.state, "trace_id", None)
    log.exception("Unhandled %s in %s", type(exc).__name__, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_type=type(exc).__name__,
            message=str(exc),
            trace_id=trace_id,
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    """Liveness probe -- returns 200 when the app is running."""
    return {"status": "ok"}
