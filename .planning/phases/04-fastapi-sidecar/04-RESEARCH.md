# Phase 4: FastAPI Sidecar - Research

**Researched:** 2026-04-19
**Domain:** FastAPI HTTP server, Supabase integration, structured logging
**Confidence:** HIGH

## Summary

Phase 4 wraps the existing roof pipeline -- currently a CLI-only prototype -- in a FastAPI HTTP server with three endpoint groups: snap-preview, pipeline-run, and label persistence. The server lives inside `roof_pipeline/api/` as a subpackage with direct imports to existing pipeline modules. All decisions about server structure, deployment (systemd + uvicorn, no Docker), Supabase integration (`supabase-py` SDK), and pipeline execution strategy (BackgroundTasks + `asyncio.to_thread()`) are locked in CONTEXT.md.

The core technical challenge is bridging the synchronous, CPU-bound pipeline (20+ seconds of NumPy/Shapely/ReportLab work) with FastAPI's async event loop without blocking other requests. The locked decision is `asyncio.to_thread()` for CPU-bound work inside `BackgroundTasks`. This is sound for single-user MVP but requires awareness of the GIL: `to_thread` releases the event loop but Python threads still contend for the GIL on CPU-bound code. For Phase 4 (single-user, single pipeline run at a time), this is acceptable.

A secondary challenge is the pipeline's current structure: `run_real.py main()` is a monolithic CLI orchestrator that mixes argument parsing, file I/O, and pipeline stages. The API needs to call these stages programmatically. This requires extracting a callable `run_pipeline()` function from `main()` -- not a full rewrite, but a thin refactor that separates CLI concerns from pipeline orchestration.

**Primary recommendation:** Build the API subpackage incrementally: config + Supabase client first, then snap-preview (simplest endpoint, wraps existing `snap_polygons()`), then pipeline-run (requires `run_real.py` refactor + background task + Supabase Storage), then labels stub. Wire structured logging middleware across all endpoints from the start.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** FastAPI app lives inside `roof_pipeline/api/` as a subpackage. Direct imports to pipeline modules -- no separate repo or sibling directory.
- **D-02:** Router-per-domain layout: `api/snap.py`, `api/pipeline.py`, `api/labels.py` as separate FastAPI routers, mounted in `api/main.py`. Mirrors the 3 endpoint groups.
- **D-03:** Deployment via systemd + uvicorn on the existing DO droplet. No Docker, no container orchestration.
- **D-04:** Use `supabase-py` official SDK for all Supabase operations (reads, writes, storage uploads).
- **D-05:** Credentials (SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY) loaded from `.env` file via pydantic-settings. `.env` is gitignored.
- **D-06:** Phase 4 creates TWO new pipeline-owned tables: `pipeline_runs` (uuid pk, sample_id fk, status text, stage_name text, progress_pct int, error_message text null, started_at timestamptz, completed_at timestamptz null) and `snap_features` (uuid pk, sample_id fk, run_id fk, feature_graph jsonb, created_at timestamptz).
- **D-07:** Panel labels table (API-03) is deferred to Phase 5. The label endpoint reads/writes whatever Phase 5 defines. Phase 4 stubs the label endpoint with the interface contract but marks the table schema as TBD.
- **D-08:** `samples` table treated as pre-existing. User will provide Supabase schema dump before execution to confirm what exists.
- **D-09:** POST /run-pipeline returns 202 Accepted with `{"run_id": uuid, "status_url": "/api/pipeline/run/{run_id}"}`. Frontend polls status_url or subscribes via Supabase Realtime.
- **D-10:** Pipeline runs in FastAPI `BackgroundTasks`. Writes to `pipeline_runs` at each stage boundary: plane_fits -> boundaries -> snap -> mesh -> cutsheets -> shop_drawings -> done. Updates `progress_pct` and `stage_name`.
- **D-11:** Entire background task wrapped in try/except. On exception: write status='error' + error_message to `pipeline_runs`, log full traceback. Never let a background task die silently.
- **D-12:** Use `asyncio.to_thread()` for CPU-bound pipeline work. The pipeline is synchronous numpy/shapely/reportlab -- pure BackgroundTasks without `to_thread()` will block the uvicorn event loop.
- **D-13:** Output files (PDFs, OBJ, glTF, features JSON) uploaded to Supabase Storage, not served from local disk. Storage paths stored in `pipeline_runs` row for frontend download.
- **D-14:** Migration plan: when a single run exceeds 60s OR concurrent runs exceed 3, migrate to arq (Redis-backed). Not needed for Phase 4. No Celery.

### Claude's Discretion
- Exact pydantic-settings config model layout
- Structured logging middleware implementation details (trace_id generation, timing hooks)
- FastAPI dependency injection patterns for Supabase client
- Exact error response JSON shape (beyond the requirement for trace_id, sample_id, endpoint, latency_ms, error_type)
- CORS configuration for the Next.js frontend origin

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| API-01 | POST /snap-preview accepts mask.json, returns feature graph + snapped polygons (<500ms target) | Wraps existing `snap_polygons()` + `build_feature_graph()` from `panel_snap_v2`. Reuses `PanelsInput` Pydantic schema as request body. |
| API-02 | POST /run-pipeline triggers full pipeline run, writes status to Supabase `pipeline_runs` table | Requires refactoring `run_real.py main()` into a callable function. BackgroundTasks + `asyncio.to_thread()` for CPU-bound work. Supabase Storage for output files. |
| API-03 | POST/GET /labels/{sampleId} persists and retrieves panel label data via Supabase | Stub endpoint -- table schema deferred to Phase 5 (D-07). Build interface contract only. |
| OBSERVABILITY-01a | Structured JSON logging for FastAPI sidecar (trace_id, sample_id, endpoint, latency_ms, error_type) | HTTP middleware generates trace_id (uuid4), measures latency, captures error_type. JSON formatter via `python-json-logger` or stdlib. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Snap preview computation | API / Backend | -- | CPU-bound geometry computation runs server-side; client sends click data, receives results |
| Pipeline orchestration | API / Backend | -- | Full pipeline is Python-only, triggered via HTTP, runs as background task |
| Status tracking | Database / Storage | API / Backend | `pipeline_runs` table in Supabase is the source of truth; API writes, frontend reads |
| File storage (PDFs, meshes) | Database / Storage | -- | Supabase Storage holds output files; API uploads, frontend downloads via signed URLs |
| Label persistence | Database / Storage | API / Backend | Supabase table is persistence layer; API is thin CRUD proxy |
| Structured logging | API / Backend | -- | Server-side concern; middleware captures request metadata into JSON log lines |
| CORS / auth boundary | API / Backend | -- | FastAPI middleware; no auth in Phase 4 but CORS must allow Next.js origin |
| Request validation | API / Backend | -- | Pydantic models at API boundary (reuses existing `PanelsInput` schema) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >= 0.115 | HTTP framework | [VERIFIED: pip index] Latest 0.136.0. Pydantic-native, async-first, auto-generates OpenAPI docs. |
| uvicorn[standard] | >= 0.30 | ASGI server | [VERIFIED: pip index] Latest 0.44.0. Standard deployment server for FastAPI. `[standard]` adds uvloop + httptools for production. |
| pydantic | >= 2.0 | Request/response validation | [VERIFIED: pip show] Already installed at 2.13.2. Already used in `panel_snap_v2/schema.py`. |
| pydantic-settings | >= 2.5 | Config from .env | [VERIFIED: pip index] Latest 2.13.1. Loads SUPABASE_URL etc. from `.env` via `BaseSettings`. |
| supabase | >= 2.7 | Supabase Python SDK | [VERIFIED: pip index] Latest 2.28.3. Sync client for table CRUD + Storage uploads. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-multipart | >= 0.0.9 | Form/file upload parsing | [VERIFIED: pip index] Latest 0.0.26. Required by FastAPI for file upload endpoints (if needed). |
| python-json-logger | >= 2.0 | Structured JSON log formatter | [ASSUMED] Stdlib logging + JSON formatter. Lightweight alternative to structlog. |
| httpx | (transitive) | HTTP client | [VERIFIED: supabase-py dependency] Comes with supabase-py. Available for health checks. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-json-logger | structlog | structlog is more powerful but adds a dependency; stdlib logging + JSON formatter is lighter for this MVP |
| supabase sync client | supabase async client (acreate_client) | Async client exists but pipeline code is synchronous; sync client in `to_thread()` is simpler and avoids mixing async contexts |
| BackgroundTasks | arq (Redis-backed queue) | arq is the locked escape hatch (D-14) but not needed for single-user MVP |

**Installation:**
```bash
pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic-settings>=2.5" "supabase>=2.7" "python-multipart>=0.0.9"
```

**Version verification:** Versions confirmed via `pip3 index versions` on 2026-04-19. All packages are actively maintained with recent releases.

## Architecture Patterns

### System Architecture Diagram

```
                        +-------------------+
                        |  Next.js Frontend |
                        |  (Phase 5/6)      |
                        +--------+----------+
                                 |
                            HTTP | (CORS-enabled)
                                 v
+----------------------------------------------------------------+
|  FastAPI Sidecar (roof_pipeline/api/)                          |
|                                                                |
|  +------------------+  +-------------------+  +--------------+ |
|  | Logging          |  | CORS              |  | Error        | |
|  | Middleware        |  | Middleware        |  | Handler      | |
|  | (trace_id, time) |  | (allow origins)   |  | (JSON shape) | |
|  +--------+---------+  +-------------------+  +--------------+ |
|           |                                                    |
|  +--------v---------+  +-------------------+  +--------------+ |
|  | /snap-preview     |  | /run-pipeline     |  | /labels/     | |
|  | (snap.py router)  |  | (pipeline.py)     |  | (labels.py)  | |
|  |                   |  |                   |  | [STUB]       | |
|  | PanelsInput ->    |  | 202 Accepted ->   |  | GET/POST     | |
|  | snap_polygons()   |  | BackgroundTask    |  | Supabase R/W | |
|  | -> feature_graph  |  | -> to_thread()    |  |              | |
|  +-------------------+  | -> pipeline stages|  +--------------+ |
|                          | -> Supabase write |                  |
|                          | -> Storage upload |                  |
|                          +-------------------+                  |
+----------------------------------------------------------------+
                                 |
                    +------------+------------+
                    |                         |
               +----v----+            +-------v--------+
               | Supabase|            | Supabase       |
               | Postgres|            | Storage        |
               |         |            |                |
               | tables: |            | buckets:       |
               | samples |            | pipeline-      |
               | pipeline|            |   outputs/     |
               |  _runs  |            |                |
               | snap_   |            |                |
               |  features|           |                |
               +---------+            +----------------+
```

### Recommended Project Structure
```
roof_pipeline/
  api/
    __init__.py          # Package marker
    main.py              # FastAPI app, mount routers, middleware, CORS
    config.py            # pydantic-settings BaseSettings model
    deps.py              # Dependency injection (Supabase client, settings)
    middleware.py         # Structured logging middleware (trace_id, timing)
    snap.py              # APIRouter: POST /snap-preview
    pipeline.py          # APIRouter: POST /run-pipeline, GET /run/{run_id}
    labels.py            # APIRouter: POST/GET /labels/{sampleId} [stub]
    schemas.py           # Response models (SnapPreviewResponse, PipelineRunResponse, etc.)
  panel_snap_v2/         # Existing -- no changes
  run_real.py            # Refactor: extract run_pipeline() callable from main()
  ... (existing modules unchanged)
```

### Pattern 1: pydantic-settings Config Model
**What:** Centralized configuration loaded from `.env` via pydantic-settings `BaseSettings`
**When to use:** Application startup -- singleton config injected via FastAPI dependency
**Example:**
```python
# Source: Context7 /pydantic/pydantic-settings, verified 2026-04-19
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    cors_origins: list[str] = ["http://localhost:3000"]
    storage_bucket: str = "pipeline-outputs"
```

### Pattern 2: FastAPI Dependency Injection for Supabase Client
**What:** Supabase client created once at startup, injected into route handlers via `Depends()`
**When to use:** Every route that needs Supabase access
**Example:**
```python
# Source: Context7 /fastapi/fastapi (dependency injection) + /supabase/supabase-py
from functools import lru_cache
from supabase import create_client, Client
from fastapi import Depends

@lru_cache
def get_settings() -> Settings:
    return Settings()

def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
```

### Pattern 3: Background Pipeline with Stage-Boundary Status Updates
**What:** Pipeline runs in `BackgroundTasks` with `asyncio.to_thread()`, writes status to Supabase at each stage boundary
**When to use:** POST /run-pipeline handler
**Example:**
```python
# Source: Context7 /fastapi/fastapi (BackgroundTasks) + D-10, D-11, D-12
import asyncio
import uuid
from fastapi import BackgroundTasks

async def _run_pipeline_bg(run_id: uuid.UUID, sample_id: uuid.UUID, supabase: Client):
    """Background task: run pipeline stages, update status at each boundary."""
    stages = [
        ("plane_fits", 15),
        ("boundaries", 30),
        ("snap", 50),
        ("mesh", 65),
        ("cutsheets", 80),
        ("shop_drawings", 90),
    ]
    try:
        for stage_name, progress_pct in stages:
            supabase.table("pipeline_runs").update({
                "status": "running",
                "stage_name": stage_name,
                "progress_pct": progress_pct,
            }).eq("id", str(run_id)).execute()

            # Run CPU-bound stage in thread to not block event loop
            result = await asyncio.to_thread(run_stage, stage_name, ...)

        # Upload outputs to Supabase Storage
        # ...

        supabase.table("pipeline_runs").update({
            "status": "done",
            "progress_pct": 100,
            "completed_at": "now()",
        }).eq("id", str(run_id)).execute()

    except Exception as exc:
        supabase.table("pipeline_runs").update({
            "status": "error",
            "error_message": str(exc),
            "completed_at": "now()",
        }).eq("id", str(run_id)).execute()
        log.exception("pipeline run %s failed", run_id)
```

### Pattern 4: Structured Logging Middleware
**What:** HTTP middleware that generates trace_id, measures latency, logs structured JSON per request
**When to use:** Applied globally to all requests via `@app.middleware("http")`
**Example:**
```python
# Source: Context7 /fastapi/fastapi (middleware) + OBSERVABILITY-01a
import time
import uuid
import json
import logging

@app.middleware("http")
async def structured_logging(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    start = time.perf_counter()

    response = await call_next(request)

    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    log_entry = {
        "trace_id": trace_id,
        "sample_id": getattr(request.state, "sample_id", None),
        "endpoint": request.url.path,
        "method": request.method,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "error_type": None,
    }
    log.info(json.dumps(log_entry))
    return response
```

### Pattern 5: Router-per-Domain Mount
**What:** Each endpoint group in its own file with `APIRouter`, mounted in `main.py`
**When to use:** Application structure (D-02)
**Example:**
```python
# Source: Context7 /fastapi/fastapi (APIRouter, include_router)
# api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .snap import router as snap_router
from .pipeline import router as pipeline_router
from .labels import router as labels_router
from .config import Settings

app = FastAPI(title="My Metal Roofer Pipeline API", version="0.1.0")

# CORS for Next.js frontend
settings = Settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(snap_router, prefix="/api/snap", tags=["snap"])
app.include_router(pipeline_router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(labels_router, prefix="/api/labels", tags=["labels"])
```

### Anti-Patterns to Avoid
- **Running sync pipeline in async def without to_thread:** Blocks the uvicorn event loop for 20+ seconds. Every request queues behind the pipeline. Always use `asyncio.to_thread()` for CPU-bound pipeline stages. [CITED: https://github.com/fastapi/fastapi/discussions/11210]
- **Creating a new Supabase client per request:** SDK client creation has overhead (HTTP connection pool setup). Use dependency injection with `lru_cache` to create once. [ASSUMED]
- **Catching exceptions in background task but not writing to DB:** Violates D-11. The try/except MUST write status='error' to `pipeline_runs` so the frontend knows the run failed. Silent failures are the worst outcome.
- **Writing output files to local disk:** Violates D-13. The sidecar runs on a DO droplet; local files are not accessible to the Next.js frontend. Upload to Supabase Storage.
- **Using async Supabase client inside to_thread:** `to_thread` runs sync code in a thread. If you use the async client, you'd need a separate event loop in the thread. Use the sync client (`create_client`, not `acreate_client`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP framework | Custom ASGI app | FastAPI | Routing, validation, OpenAPI docs, middleware, dependency injection |
| Request validation | Manual JSON parsing | Pydantic models (via FastAPI) | Type safety, error messages, reuse existing `PanelsInput` schema |
| Config from .env | `os.getenv()` calls | pydantic-settings `BaseSettings` | Typed, validated, `.env` file support, testing override |
| Supabase access | Raw HTTP to PostgREST | `supabase-py` SDK | Auth headers, RLS, Storage API, connection pooling |
| CORS handling | Manual headers | `CORSMiddleware` | Origin validation, preflight handling, credential support |
| UUID generation | Custom ID scheme | `uuid.uuid4()` | Standard, collision-resistant, matches Supabase uuid type |
| JSON logging | Custom formatter | `python-json-logger` or stdlib JSONFormatter | Structured output for log aggregation |

**Key insight:** The API layer is a thin HTTP skin over existing pipeline functions. The pipeline logic is already written and tested. The API should NOT reimplement any geometry, mesh, or PDF logic -- it calls the existing functions and handles HTTP concerns (request parsing, response formatting, async execution, error reporting).

## Common Pitfalls

### Pitfall 1: Event Loop Blocking on CPU-Bound Pipeline
**What goes wrong:** Pipeline stages (plane fitting, snapping, mesh building) take 5-20 seconds of pure CPU work. Running synchronously in an async handler blocks ALL other requests.
**Why it happens:** Python's GIL means threads don't truly parallelize CPU-bound code, but `asyncio.to_thread()` at least releases the event loop so other I/O-bound requests (status polling, snap-preview for a different sample) can proceed.
**How to avoid:** Always wrap pipeline calls in `asyncio.to_thread()` (D-12). Never call `snap_polygons()` or pipeline stages directly in an `async def` handler.
**Warning signs:** Status polling endpoint returns 503 or times out while a pipeline run is in progress.

### Pitfall 2: Supabase Storage Upload Content-Type
**What goes wrong:** Files uploaded to Supabase Storage without explicit `content-type` are stored as `text/plain`. PDFs downloaded later open as text, OBJ/glTF files are unusable.
**Why it happens:** Supabase Storage defaults to `text/plain` when no MIME type is specified.
**How to avoid:** Always pass `{"content-type": "application/pdf"}`, `{"content-type": "model/gltf+json"}`, etc. in the upload options.
**Warning signs:** Downloaded files have wrong MIME type or fail to open in viewers.

### Pitfall 3: Background Task Silent Failure
**What goes wrong:** An exception in the background pipeline task kills the task but leaves the `pipeline_runs` row stuck at status='running' forever.
**Why it happens:** FastAPI BackgroundTasks swallow exceptions by default -- they log to stderr but don't update any external state.
**How to avoid:** Wrap the ENTIRE background task body in try/except (D-11). In the except block: write status='error' + error_message to the `pipeline_runs` row AND log the full traceback.
**Warning signs:** Pipeline runs that never complete. `pipeline_runs` rows permanently stuck at status='running'.

### Pitfall 4: Schema Drift Between Pydantic and Zod
**What goes wrong:** The Python API expects one JSON shape; the Next.js frontend sends a different shape. Requests fail at runtime.
**Why it happens:** Two validation layers (Pydantic on server, Zod on client) with no shared source of truth.
**How to avoid:** Define the API contract as Pydantic models first (Phase 4). When building the frontend (Phase 5), derive Zod schemas from the OpenAPI spec that FastAPI auto-generates. Or manually keep them in sync with explicit test coverage.
**Warning signs:** 422 Unprocessable Entity responses from the API during frontend integration.

### Pitfall 5: run_real.py Refactoring Breaks CLI
**What goes wrong:** Extracting pipeline stages from `main()` for API use accidentally breaks the `python -m roof_pipeline.run_real` CLI.
**Why it happens:** `main()` is tightly coupled to argparse and file paths. The refactor must preserve the CLI path while exposing a callable function.
**How to avoid:** Create a new function `run_pipeline(dsm, mask, res_m, ...)` that takes data arguments (not file paths). Have `main()` call it after parsing args and loading files. The API also calls `run_pipeline()` after receiving data via HTTP.
**Warning signs:** Existing test suite fails after refactoring. CLI invocation errors.

### Pitfall 6: Supabase Client in Background Thread
**What goes wrong:** The Supabase sync client is created in the main thread but used in a background thread via `asyncio.to_thread()`. Most HTTP client libraries are thread-safe for requests, but shared state mutations (auth token refresh) could race.
**Why it happens:** `to_thread()` runs in a different thread than where the client was created.
**How to avoid:** Create the Supabase client inside the background task function, or verify that `supabase-py`'s sync client is thread-safe for concurrent use (it uses httpx under the hood, which is thread-safe for requests). For MVP with single concurrent runs, this is a non-issue. [ASSUMED]
**Warning signs:** Intermittent auth errors or connection resets during concurrent pipeline runs.

## Code Examples

### Snap Preview Endpoint (API-01)

```python
# Source: Existing panel_snap_v2 API + FastAPI router pattern
from fastapi import APIRouter, Depends, HTTPException
from roof_pipeline.panel_snap_v2.schema import PanelsInput
from roof_pipeline.panel_snap_v2 import snap_polygons
from roof_pipeline.panel_snap_v2.graph import build_feature_graph
from roof_pipeline.boundaries import polygons_from_clicks
from roof_pipeline.planes import fit_all_panels
import numpy as np

router = APIRouter()

@router.post("/preview")
async def snap_preview(body: PanelsInput):
    """Snap polygons and return feature graph + snapped coordinates.

    Reuses existing PanelsInput schema (VALID-01).
    Target: <500ms for 12-panel roof.
    """
    # Build polygons from click data
    # Note: polygons_from_clicks needs dsm + res_m + planes
    # These come from the sample's DSM file -- need to load from Supabase Storage
    # or pass precomputed planes
    ...
```

### Pipeline Run Endpoint (API-02)

```python
# Source: FastAPI BackgroundTasks + D-09, D-10
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
import uuid

router = APIRouter()

@router.post("/run", status_code=202)
async def trigger_pipeline_run(
    body: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    supabase: Client = Depends(get_supabase),
):
    run_id = uuid.uuid4()
    # Insert initial pipeline_runs row
    supabase.table("pipeline_runs").insert({
        "id": str(run_id),
        "sample_id": str(body.sample_id),
        "status": "queued",
        "stage_name": None,
        "progress_pct": 0,
        "started_at": "now()",
    }).execute()

    # Schedule background task
    background_tasks.add_task(_run_pipeline_bg, run_id, body.sample_id, supabase)

    return JSONResponse(
        status_code=202,
        content={
            "run_id": str(run_id),
            "status_url": f"/api/pipeline/run/{run_id}",
        },
    )
```

### Supabase Storage Upload Pattern

```python
# Source: Context7 /supabase/supabase-py (storage upload)
import tempfile
from pathlib import Path

def _upload_output(supabase: Client, bucket: str, run_id: uuid.UUID, local_path: Path, content_type: str):
    """Upload a pipeline output file to Supabase Storage."""
    storage_path = f"runs/{run_id}/{local_path.name}"
    with open(local_path, "rb") as f:
        supabase.storage.from_(bucket).upload(
            storage_path,
            f,
            {"content-type": content_type, "upsert": "true"},
        )
    return storage_path
```

### Structured Logging Setup

```python
# Source: Python stdlib logging + JSON formatter pattern
import logging
import json
from datetime import datetime, timezone

class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON."""
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extra fields (trace_id, sample_id, etc.)
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FastAPI < 0.100 | FastAPI 0.115+ | 2024 | Pydantic v2 native, improved performance, Annotated dependency syntax |
| supabase-py 1.x | supabase-py 2.x | 2024 | Async client support, breaking API changes from v1 |
| python-dotenv | pydantic-settings | 2023 | Typed config, validation, `.env` support built-in |
| Celery for background tasks | BackgroundTasks / arq | Ongoing | Celery is heavyweight; BackgroundTasks for simple cases, arq for queues |

**Deprecated/outdated:**
- `supabase-py` v1.x API: v2 changed import paths and client creation. Use `from supabase import create_client, Client` (not the old community path).
- `fastapi.encoders.jsonable_encoder()`: Still works but direct Pydantic v2 `.model_dump()` is preferred for serialization.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | python-json-logger is the right lightweight JSON formatter | Standard Stack | Low -- stdlib JSONFormatter works fine as alternative; no external dep needed |
| A2 | supabase-py sync client is thread-safe for use inside asyncio.to_thread() | Pitfall 6 | Medium -- if not thread-safe, need per-thread client creation. Single-user MVP mitigates. |
| A3 | lru_cache on Supabase client creation is appropriate (no per-request overhead) | Architecture Patterns | Low -- standard FastAPI pattern, widely used |
| A4 | Pipeline completes in <60s for 12-panel roof (BackgroundTasks sufficient) | Pitfall 1 | Medium -- if >60s, D-14 arq migration triggered earlier than expected |
| A5 | `samples` table exists with uuid `id` column and basic metadata | D-08 constraint | High -- user committed to providing schema dump before execution |

## Open Questions

1. **`samples` table schema**
   - What we know: D-08 says it is pre-existing. User will provide schema dump before execution.
   - What's unclear: Exact column names and types. Does `sample_id` reference `samples.id`? What metadata columns exist?
   - Recommendation: Block on user providing Supabase schema dump. The `pipeline_runs` FK and queries depend on this.

2. **DSM/mask file source for /snap-preview**
   - What we know: The CLI loads DSM from local `.tif` file. The API receives click data as JSON.
   - What's unclear: Does `/snap-preview` receive the full mask.json (click coordinates + DSM reference) or does it load the DSM from Supabase Storage? The current `polygons_from_clicks()` needs `dsm`, `res_m`, and `planes` -- where do these come from in the API path?
   - Recommendation: API-01 should receive panel click data only (mask.json format). The API looks up the sample's DSM file from Supabase Storage (or a pre-computed planes cache). This needs a design decision during planning.

3. **Supabase Storage bucket creation**
   - What we know: D-13 says output files go to Supabase Storage. Need a bucket.
   - What's unclear: Does the bucket already exist? Need to create it via dashboard or API? Bucket access policies?
   - Recommendation: Include bucket creation step in Phase 4 plan. Use `pipeline-outputs` as bucket name. RLS policy: read access for authenticated users, write for service role.

4. **`run_real.py` refactoring scope**
   - What we know: `main()` is 130 lines mixing CLI parsing + pipeline stages. API needs callable stages.
   - What's unclear: Exact function signature for the extracted `run_pipeline()` function. What arguments does it take?
   - Recommendation: Extract `run_pipeline(dsm, mask, res_m, snap_tol, project_meta, out_dir, use_snap_v2)` that takes loaded data arrays and returns output file paths. `main()` becomes a thin CLI wrapper that loads files and calls `run_pipeline()`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | Partially | 3.14.3 (dev machine) | Project targets 3.11 -- DO droplet must have 3.11+. Dev works on 3.14. |
| pip | Package install | Yes | -- | -- |
| fastapi | HTTP server | No (not installed) | 0.136.0 available | Install via pip |
| uvicorn | ASGI server | No (not installed) | 0.44.0 available | Install via pip |
| supabase-py | DB/Storage SDK | No (not installed) | 2.28.3 available | Install via pip |
| pydantic-settings | Config | No (not installed) | 2.13.1 available | Install via pip |
| pydantic | Validation | Yes | 2.13.2 | Already in requirements.txt |
| pytest | Testing | Yes | 9.0.3 | Already in requirements.txt |
| Supabase project | DB + Storage | External | -- | User provides credentials |
| systemd | Deployment | On DO droplet | -- | Not needed for dev/testing |

**Missing dependencies with no fallback:**
- Supabase project credentials (SUPABASE_URL, keys) -- user must provide before API can talk to database/storage

**Missing dependencies with fallback:**
- fastapi, uvicorn, supabase-py, pydantic-settings -- all installable via pip, no system-level dependencies

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | none -- no pytest.ini/pyproject.toml (tests discovered by convention) |
| Quick run command | `python3 -m pytest roof_pipeline/panel_snap_v2/tests/ -x -q` |
| Full suite command | `python3 -m pytest roof_pipeline/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| API-01 | POST /snap-preview returns feature graph + snapped polygons | integration | `python3 -m pytest roof_pipeline/api/tests/test_snap.py -x` | No -- Wave 0 |
| API-01 | Response time <500ms for 12-panel roof | performance | Manual benchmark or `pytest --timeout` | No -- Wave 0 |
| API-02 | POST /run-pipeline returns 202 + creates pipeline_runs row | integration | `python3 -m pytest roof_pipeline/api/tests/test_pipeline.py -x` | No -- Wave 0 |
| API-02 | Background task updates status at stage boundaries | integration | `python3 -m pytest roof_pipeline/api/tests/test_pipeline.py::test_status_updates -x` | No -- Wave 0 |
| API-03 | POST/GET /labels/{sampleId} round-trip | integration | `python3 -m pytest roof_pipeline/api/tests/test_labels.py -x` | No -- Wave 0 |
| OBSERVABILITY-01a | Every request logs trace_id, sample_id, endpoint, latency_ms, error_type | unit | `python3 -m pytest roof_pipeline/api/tests/test_middleware.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest roof_pipeline/api/tests/ -x -q`
- **Per wave merge:** `python3 -m pytest roof_pipeline/ -x -q` (full suite including existing panel_snap_v2 tests)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `roof_pipeline/api/tests/__init__.py` -- package marker
- [ ] `roof_pipeline/api/tests/conftest.py` -- FastAPI TestClient fixture, mock Supabase client
- [ ] `roof_pipeline/api/tests/test_snap.py` -- covers API-01
- [ ] `roof_pipeline/api/tests/test_pipeline.py` -- covers API-02
- [ ] `roof_pipeline/api/tests/test_labels.py` -- covers API-03
- [ ] `roof_pipeline/api/tests/test_middleware.py` -- covers OBSERVABILITY-01a
- [ ] Framework install: `pip install httpx` (for FastAPI TestClient -- may come transitively via supabase)

**Testing approach:** FastAPI's `TestClient` (from `starlette.testclient`) allows synchronous testing of async endpoints. Supabase calls should be mocked (no live DB dependency in tests). Use `unittest.mock.patch` or `pytest-mock` to stub Supabase client methods.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (Phase 4 MVP, no auth) | Supabase RLS + service role key for server-to-DB. User auth deferred. |
| V3 Session Management | No | No user sessions in Phase 4 |
| V4 Access Control | Partial | CORS restricts origins; Supabase RLS for row-level access |
| V5 Input Validation | Yes | Pydantic models (PanelsInput, request bodies) at every API boundary |
| V6 Cryptography | No | No custom crypto; Supabase handles TLS |

### Known Threat Patterns for FastAPI + Supabase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthenticated access to pipeline | Spoofing | CORS origin restriction (Phase 4); add auth in future milestone |
| Malformed polygon data causing crashes | Tampering | Pydantic validation (PanelsInput) rejects bad input before pipeline runs |
| Pipeline errors leaking internal paths | Information Disclosure | Error handler returns generic error_type + error_message, not full tracebacks |
| Supabase service key exposure | Information Disclosure | Service role key in `.env` (gitignored); never sent to client |
| DoS via repeated pipeline triggers | Denial of Service | Single-user MVP mitigates; future: rate limiting + arq queue (D-14) |

## Sources

### Primary (HIGH confidence)
- [Context7 /fastapi/fastapi] - BackgroundTasks, APIRouter, middleware, CORS, dependency injection
- [Context7 /supabase/supabase-py] - Client creation, table CRUD, Storage upload
- [Context7 /pydantic/pydantic-settings] - BaseSettings, env_file configuration
- [pip index] - Version verification for fastapi (0.136.0), uvicorn (0.44.0), supabase (2.28.3), pydantic-settings (2.13.1)
- [Codebase] - `run_real.py`, `panel_snap_v2/__init__.py`, `schema.py`, `graph.py`, `boundaries.py`, `mesh.py`

### Secondary (MEDIUM confidence)
- [Supabase official docs: https://supabase.com/docs/reference/python/initializing] - Client initialization patterns
- [FastAPI discussions: https://github.com/fastapi/fastapi/discussions/11210] - BackgroundTasks blocking behavior
- [Apitally blog: https://apitally.io/blog/fastapi-logging-guide] - Structured logging patterns
- [Shesh's blog: https://www.sheshbabu.com/posts/fastapi-structured-json-logging/] - JSON logging middleware

### Tertiary (LOW confidence)
- [WebSearch: supabase-py thread safety] - Assumed thread-safe based on httpx backend, not explicitly verified

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All packages verified via pip index, versions confirmed, Context7 docs reviewed
- Architecture: HIGH - Router-per-domain is standard FastAPI pattern, BackgroundTasks + to_thread well-documented
- Pitfalls: HIGH - GIL/event-loop blocking is well-known, Supabase Storage content-type is documented
- Supabase integration: MEDIUM - Sync client in threaded context is standard but thread-safety not explicitly documented
- run_real.py refactoring: HIGH - Code reviewed, refactoring scope is clear (extract callable from main())

**Research date:** 2026-04-19
**Valid until:** 2026-05-19 (30 days -- stable stack, no fast-moving components)
