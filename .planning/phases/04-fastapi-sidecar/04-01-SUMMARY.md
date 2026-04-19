---
phase: 04-fastapi-sidecar
plan: 01
subsystem: api
tags: [fastapi, uvicorn, pydantic-settings, supabase, cors, structured-logging, middleware]

# Dependency graph
requires:
  - phase: 02-apex-solver-integration
    provides: "PanelsInput Pydantic schema in panel_snap_v2/schema.py"
provides:
  - "FastAPI app factory with CORS, structured logging, error handlers"
  - "Settings model loading from .env via pydantic-settings"
  - "Supabase client dependency injection"
  - "Response schemas for snap-preview, pipeline-run, labels"
  - "Stub routers for all 3 endpoint groups"
  - "Structured JSON logging middleware (OBSERVABILITY-01a)"
affects: [04-02, 04-03, 04-04, 05-labeling-dashboard]

# Tech tracking
tech-stack:
  added: [fastapi 0.136.0, uvicorn 0.44.0, pydantic-settings 2.13.1, supabase 2.28.3, python-multipart 0.0.26]
  patterns: [pydantic-settings BaseSettings, lru_cache dependency injection, structured JSON logging middleware, router-per-domain mount, graceful Settings fallback]

key-files:
  created:
    - roof_pipeline/api/__init__.py
    - roof_pipeline/api/config.py
    - roof_pipeline/api/deps.py
    - roof_pipeline/api/middleware.py
    - roof_pipeline/api/schemas.py
    - roof_pipeline/api/snap.py
    - roof_pipeline/api/pipeline.py
    - roof_pipeline/api/labels.py
    - roof_pipeline/api/main.py
    - .env.example
  modified:
    - requirements.txt
    - .gitignore

key-decisions:
  - "Graceful Settings fallback: main.py wraps Settings() in try/except so app starts without .env (uses default CORS origins, logs warning)"
  - "JSONFormatter deduplication guard: configure_logging() checks for existing JSONFormatter handlers to avoid duplicate log lines during test reimports"
  - ".env.example tracked via !.env.example gitignore exception (the .env.* glob would otherwise ignore it)"

patterns-established:
  - "pydantic-settings BaseSettings with env_file='.env' and extra='ignore' for server config"
  - "lru_cache on get_settings() for singleton Settings instance"
  - "Supabase client via FastAPI Depends() chain from get_settings -> get_supabase"
  - "Structured JSON logging middleware with trace_id, sample_id, endpoint, method, status_code, latency_ms, error_type"
  - "JSONFormatter for root logger producing single-line JSON log records"
  - "Global exception handlers returning ErrorResponse (error_type + message + trace_id, no traceback leak)"
  - "Router-per-domain: snap.py, pipeline.py, labels.py mounted at /api/snap, /api/pipeline, /api/labels"

requirements-completed: [OBSERVABILITY-01a]

# Metrics
duration: 4min
completed: 2026-04-19
---

# Phase 4 Plan 1: FastAPI Skeleton Summary

**FastAPI sidecar with pydantic-settings config, Supabase DI, structured JSON logging middleware, response schemas, and 3 mounted stub routers returning 501**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-19T16:19:36Z
- **Completed:** 2026-04-19T16:23:59Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments
- FastAPI app starts and serves health check at /health (200 OK)
- Structured JSON logging middleware emits trace_id, sample_id, endpoint, method, status_code, latency_ms, error_type on every request (OBSERVABILITY-01a)
- All 3 router groups mounted as stubs: /api/snap/preview, /api/pipeline/run, /api/labels/{sample_id}
- CORS configured for localhost:3000 with graceful fallback when .env is absent
- Global exception handlers for ValueError (422), RuntimeError (500), Exception (500) -- no traceback leak (T-04-03)
- X-Trace-ID header on every response
- All 49 existing panel_snap_v2 tests still pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Install dependencies and create config + deps + middleware** - `7e9bab8` (feat)
2. **Task 2: Create response schemas, stub routers, and app factory** - `81b4a10` (feat)

## Files Created/Modified

- `requirements.txt` - Added fastapi, uvicorn, pydantic-settings, supabase, python-multipart
- `.env.example` - Template with Supabase URL/keys, CORS origins, storage bucket
- `.gitignore` - Added !.env.example exception to track template file
- `roof_pipeline/api/__init__.py` - Package marker
- `roof_pipeline/api/config.py` - Settings(BaseSettings) with Supabase and CORS config (D-05)
- `roof_pipeline/api/deps.py` - get_settings() with lru_cache, get_supabase() with Depends (D-04)
- `roof_pipeline/api/middleware.py` - JSONFormatter + structured_logging_middleware (OBSERVABILITY-01a)
- `roof_pipeline/api/schemas.py` - SnapPreviewResponse, PipelineRunCreated/Status/Request, LabelData, ErrorResponse
- `roof_pipeline/api/snap.py` - Stub router POST /preview -> 501
- `roof_pipeline/api/pipeline.py` - Stub router POST /run, GET /run/{run_id} -> 501
- `roof_pipeline/api/labels.py` - Stub router POST/GET /{sample_id} -> 501
- `roof_pipeline/api/main.py` - App factory with CORS, logging middleware, routers, error handlers, /health

## Decisions Made

- **Graceful Settings fallback:** main.py wraps Settings() in try/except so the app can start and serve health checks without a .env file. Logs a warning and uses default CORS origins. This allows testing and development without Supabase credentials.
- **JSONFormatter dedup guard:** configure_logging() checks for existing JSONFormatter handlers before adding a new one, preventing duplicate log lines when modules are reimported during testing.
- **.env.example gitignore exception:** Added `!.env.example` to .gitignore because the existing `.env.*` glob pattern would otherwise exclude the template file from version control.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added !.env.example to .gitignore**
- **Found during:** Task 1 (creating .env.example)
- **Issue:** The existing `.env.*` glob in .gitignore would prevent .env.example from being tracked
- **Fix:** Added `!.env.example` negation rule after `.env.*` in .gitignore
- **Files modified:** .gitignore
- **Verification:** `git add .env.example` succeeds
- **Committed in:** 7e9bab8 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix to ensure .env.example is version-controlled. No scope creep.

## Known Stubs

These are intentional stub endpoints that return 501. They will be implemented in subsequent plans:

| Stub | File | Target Plan |
|------|------|-------------|
| POST /api/snap/preview | roof_pipeline/api/snap.py:24 | Plan 03 |
| POST /api/pipeline/run | roof_pipeline/api/pipeline.py:23 | Plan 04 |
| GET /api/pipeline/run/{run_id} | roof_pipeline/api/pipeline.py:32 | Plan 04 |
| POST /api/labels/{sample_id} | roof_pipeline/api/labels.py:22 | Plan 04 |
| GET /api/labels/{sample_id} | roof_pipeline/api/labels.py:31 | Plan 04 |

These stubs are required by the plan and do not block this plan's goal (skeleton infrastructure).

## Issues Encountered

None - plan executed cleanly.

## User Setup Required

**External services require manual configuration.** The plan's `user_setup` section documents:
- Supabase project credentials (SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY) must be added to `.env`
- Database tables (samples, labels, pipeline_runs, snap_features) must be created via Supabase Dashboard SQL Editor
- Storage bucket `pipeline-outputs` must be created via Supabase Dashboard

The app starts and serves health checks without these credentials (graceful fallback).

## Next Phase Readiness

- FastAPI skeleton is complete and serving requests
- Plan 02 (tests) can create conftest.py with TestClient fixture against this app
- Plan 03 (snap-preview) can implement snap.py endpoint logic against the mounted router
- Plan 04 (pipeline-run + labels) can implement the remaining endpoints
- All response schemas are defined and ready for endpoint implementation

## Self-Check: PASSED

All 10 created files verified on disk. Both task commits (7e9bab8, 81b4a10) verified in git log.

---
*Phase: 04-fastapi-sidecar*
*Completed: 2026-04-19*
