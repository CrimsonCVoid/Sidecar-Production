---
phase: 04-fastapi-sidecar
verified: 2026-04-19T17:26:36Z
status: human_needed
score: 4/4
overrides_applied: 0
must_haves:
  truths:
    - "POST /snap-preview with a valid mask.json body returns a JSON response containing the feature graph and snapped polygon coordinates"
    - "POST /run-pipeline triggers a full pipeline run and writes status updates to a Supabase pipeline_runs table"
    - "POST /labels/{sampleId} persists panel label data to Supabase and GET retrieves it with round-trip coordinate preservation"
    - "Every request logs a structured JSON line containing trace_id, sample_id, endpoint, latency_ms, and error_type"
  artifacts:
    - path: "roof_pipeline/api/__init__.py"
      provides: "Package marker"
    - path: "roof_pipeline/api/config.py"
      provides: "pydantic-settings BaseSettings model"
      contains: "class Settings"
    - path: "roof_pipeline/api/deps.py"
      provides: "FastAPI dependency injection for settings and Supabase client"
    - path: "roof_pipeline/api/middleware.py"
      provides: "Structured JSON logging middleware"
      contains: "trace_id"
    - path: "roof_pipeline/api/schemas.py"
      provides: "Response models for all API endpoints"
      contains: "SnapPreviewResponse"
    - path: "roof_pipeline/api/main.py"
      provides: "FastAPI app with routers mounted and middleware applied"
      contains: "app = FastAPI"
    - path: "roof_pipeline/api/snap.py"
      provides: "Snap preview endpoint implementation"
      contains: "snap_polygons"
    - path: "roof_pipeline/api/pipeline.py"
      provides: "Pipeline run trigger + status polling endpoints"
      contains: "BackgroundTasks"
    - path: "roof_pipeline/api/labels.py"
      provides: "Label persistence CRUD endpoints"
      contains: "sample_id"
    - path: "roof_pipeline/api/tests/conftest.py"
      provides: "TestClient fixture and mock Supabase"
      contains: "TestClient"
    - path: "roof_pipeline/api/tests/test_snap.py"
      provides: "API-01 integration tests"
      contains: "TestSnapPreview"
    - path: "roof_pipeline/api/tests/test_middleware.py"
      provides: "OBSERVABILITY-01a middleware tests"
      contains: "trace_id"
    - path: "roof_pipeline/api/tests/test_pipeline.py"
      provides: "API-02 integration tests"
      contains: "TestPipelineRunTrigger"
    - path: "roof_pipeline/api/tests/test_labels.py"
      provides: "API-03 integration tests"
      contains: "TestLabelSave"
    - path: "roof_pipeline/run_real.py"
      provides: "Extracted run_pipeline() callable + unchanged CLI main()"
    - path: "requirements.txt"
      provides: "Updated dependencies including fastapi, uvicorn, supabase, pydantic-settings"
    - path: ".env.example"
      provides: "Template environment configuration"
  key_links:
    - from: "roof_pipeline/api/main.py"
      to: "roof_pipeline/api/middleware.py"
      via: "app.middleware registration"
    - from: "roof_pipeline/api/main.py"
      to: "roof_pipeline/api/snap.py"
      via: "app.include_router"
    - from: "roof_pipeline/api/deps.py"
      to: "roof_pipeline/api/config.py"
      via: "Settings import"
    - from: "roof_pipeline/api/snap.py"
      to: "roof_pipeline/panel_snap_v2/__init__.py"
      via: "snap_polygons() call"
    - from: "roof_pipeline/api/pipeline.py"
      to: "roof_pipeline/run_real.py"
      via: "run_pipeline() call in background task"
    - from: "roof_pipeline/api/pipeline.py"
      to: "supabase.table(pipeline_runs)"
      via: "Status updates at stage boundaries"
    - from: "roof_pipeline/api/labels.py"
      to: "supabase.table(labels)"
      via: "CRUD operations"
    - from: "roof_pipeline/run_real.py:main()"
      to: "roof_pipeline/run_real.py:run_pipeline()"
      via: "main() calls run_pipeline() after parsing args"
human_verification:
  - test: "Start the FastAPI server with valid .env and POST /api/snap/preview with a 12-panel roof body"
    expected: "Response returns in under 500ms with feature_graph and snapped_polygons"
    why_human: "Performance target (500ms on representative data) cannot be verified without real 12-panel roof data and a running server"
  - test: "Trigger POST /api/pipeline/run with a valid sample_id, then poll GET /api/pipeline/run/{run_id}"
    expected: "Status progresses through queued -> running -> done; output files appear in Supabase Storage"
    why_human: "End-to-end pipeline requires real Supabase credentials, DSM/mask files in Storage, and a running server"
  - test: "POST /api/labels/{sampleId} with panel data, then GET /api/labels/{sampleId}"
    expected: "Retrieved data matches posted data exactly -- all vertex coordinates preserved"
    why_human: "Round-trip through real Supabase requires live database connection"
---

# Phase 4: FastAPI Sidecar Verification Report

**Phase Goal:** The snap engine and pipeline are accessible over HTTP from the Next.js frontend, with structured server-side logging for production observability
**Verified:** 2026-04-19T17:26:36Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /snap-preview with a valid mask.json body returns a JSON response containing the feature graph and snapped polygon coordinates | VERIFIED | `snap.py` implements `snap_preview()` calling `snap_polygons()` via `asyncio.to_thread()`, returns `SnapPreviewResponse` with `feature_graph` and `snapped_polygons`. 11 tests pass including `test_two_panels_returns_200`, `test_response_has_features_and_edges`, `test_shared_edge_detected`, `test_feature_nodes_have_required_fields`. |
| 2 | POST /run-pipeline triggers a full pipeline run and writes status updates to a Supabase pipeline_runs table | VERIFIED | `pipeline.py` implements `trigger_pipeline_run()` returning 202 with `run_id` + `status_url`, inserts `status=queued` row, schedules `_run_pipeline_bg()` which calls `run_pipeline()` via `asyncio.to_thread()`, calls `_update_status()` at stage boundaries, uploads outputs to Storage, catches exceptions with D-11 double try/except. 8 tests pass. |
| 3 | POST /labels/{sampleId} persists panel label data and GET retrieves it with round-trip coordinate preservation | VERIFIED | `labels.py` implements `save_labels()` (upsert on `sample_id` conflict) and `get_labels()` (select with 404). 6 tests pass including `test_round_trip_preserves_coordinates` verifying exact float preservation. |
| 4 | Every request logs a structured JSON line containing trace_id, sample_id, endpoint, latency_ms, and error_type | VERIFIED | `middleware.py` `structured_logging_middleware()` generates `trace_id = uuid4()`, measures `latency_ms` via `time.perf_counter()`, extracts `sample_id` from `request.state`, builds log dict with all 5 fields, emits via `log.info(json.dumps(log_entry))`, sets `X-Trace-ID` header. 6 middleware tests pass including `test_log_entry_contains_required_fields`. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `roof_pipeline/api/__init__.py` | Package marker | VERIFIED | 1 line, docstring only -- correct for package marker |
| `roof_pipeline/api/config.py` | pydantic-settings BaseSettings model | VERIFIED | 31 lines. `class Settings(BaseSettings)` with `supabase_url`, `supabase_anon_key`, `supabase_service_role_key`, `cors_origins`, `storage_bucket`. `env_file=".env"`. |
| `roof_pipeline/api/deps.py` | DI for settings and Supabase client | VERIFIED | 34 lines. `get_settings()` with `@lru_cache`, `get_supabase()` with `Depends(get_settings)`, `create_client()`. |
| `roof_pipeline/api/middleware.py` | Structured JSON logging middleware | VERIFIED | 89 lines. `JSONFormatter`, `structured_logging_middleware()` with trace_id/latency_ms/sample_id/error_type, `configure_logging()` with dedup guard. |
| `roof_pipeline/api/schemas.py` | Response models | VERIFIED | 100 lines. `SnapPreviewResponse`, `PipelineRunCreated`, `PipelineRunStatus`, `PipelineRunRequest`, `LabelData`, `ErrorResponse`, `FeatureNode`, `FeatureEdge`. |
| `roof_pipeline/api/main.py` | App factory with routers + middleware | VERIFIED | 132 lines. `app = FastAPI(...)`, CORSMiddleware, structured_logging_middleware via `@app.middleware("http")`, 3 routers mounted, global exception handlers (ValueError->422, RuntimeError->500, Exception->500), `/health` endpoint. Graceful Settings fallback. |
| `roof_pipeline/api/snap.py` | Snap preview endpoint | VERIFIED | 96 lines. `_planes_from_clicks()` builds flat z=0 planes, `snap_preview()` calls `snap_polygons()` via `asyncio.to_thread()`, serializes ndarray to JSON. Not a stub. |
| `roof_pipeline/api/pipeline.py` | Pipeline run endpoints | VERIFIED | 293 lines. `trigger_pipeline_run()` (202), `get_run_status()`, `_run_pipeline_bg()` with stage-boundary updates, `_upload_output()` with content-type mapping, `_update_status()`, D-11 double try/except. Not a stub. |
| `roof_pipeline/api/labels.py` | Label CRUD endpoints | VERIFIED | 92 lines. `save_labels()` with upsert, `get_labels()` with 404 on missing. Not a stub. |
| `roof_pipeline/api/tests/conftest.py` | TestClient + mock Supabase | VERIFIED | 61 lines. `client` fixture with `dependency_overrides`, `mock_supabase_client`, `two_panel_input`, `single_panel_input`. Env vars set before import. |
| `roof_pipeline/api/tests/test_snap.py` | API-01 tests | VERIFIED | 99 lines. `TestSnapPreview` with 11 test methods covering happy path, errors, response structure, trace_id. |
| `roof_pipeline/api/tests/test_middleware.py` | OBSERVABILITY-01a tests | VERIFIED | 92 lines. `TestStructuredLogging` with 6 tests covering trace_id header, JSON log fields, latency, unique IDs. |
| `roof_pipeline/api/tests/test_pipeline.py` | API-02 tests | VERIFIED | 141 lines. `TestPipelineRunTrigger` (4 tests), `TestPipelineRunStatus` (2 tests), `TestPipelineBackgroundTask` (2 tests). |
| `roof_pipeline/api/tests/test_labels.py` | API-03 tests | VERIFIED | 137 lines. `TestLabelSave` (3 tests), `TestLabelRetrieve` (3 tests including round-trip preservation). |
| `roof_pipeline/run_real.py` | Extracted `run_pipeline()` callable | VERIFIED | `run_pipeline()` at line 58 with 14 params, returns `dict[str, Path]`. `main()` at line 220 as thin CLI wrapper calling `run_pipeline()` at line 282. `_load_dsm()` at module level. |
| `requirements.txt` | Updated dependencies | VERIFIED | Contains `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `pydantic-settings>=2.5`, `supabase>=2.7`, `python-multipart>=0.0.9`. |
| `.env.example` | Template env config | VERIFIED | 5 lines with `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `CORS_ORIGINS`, `STORAGE_BUCKET`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `api/main.py` | `api/middleware.py` | `@app.middleware("http")` registration | WIRED | Line 13 imports `structured_logging_middleware`, line 64-66 registers as `@app.middleware("http")` |
| `api/main.py` | `api/snap.py` | `app.include_router` | WIRED | Line 16 imports `snap_router`, line 72 mounts at `/api/snap` |
| `api/main.py` | `api/pipeline.py` | `app.include_router` | WIRED | Line 14 imports `pipeline_router`, line 73 mounts at `/api/pipeline` |
| `api/main.py` | `api/labels.py` | `app.include_router` | WIRED | Line 12 imports `labels_router`, line 74 mounts at `/api/labels` |
| `api/deps.py` | `api/config.py` | `from .config import Settings` | WIRED | Line 11 imports Settings, line 23 instantiates it |
| `api/snap.py` | `panel_snap_v2/__init__.py` | `snap_polygons()` call | WIRED | Line 11 imports `snap_polygons`, line 78 calls via `asyncio.to_thread()` |
| `api/pipeline.py` | `run_real.py` | `run_pipeline()` call | WIRED | Line 22 imports `run_pipeline` and `_load_dsm`, line 157 calls via `asyncio.to_thread()` |
| `api/pipeline.py` | `supabase.table("pipeline_runs")` | Status updates | WIRED | Lines 85, 198, 243, 278 all reference `pipeline_runs` table |
| `api/pipeline.py` | `supabase.storage` | Output file upload | WIRED | Line 55 calls `storage.from_(bucket).upload()`, lines 124/132/141 download |
| `api/labels.py` | `supabase.table("labels")` | CRUD operations | WIRED | Line 53 upserts, line 80 selects |
| `run_real.py:main()` | `run_real.py:run_pipeline()` | Direct call | WIRED | Line 282 calls `run_pipeline()` with all params from argparse |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `api/snap.py` | `snapped`, `feature_graph` | `snap_polygons()` from `panel_snap_v2` | Yes -- calls real engine | FLOWING |
| `api/pipeline.py` | `output_paths` | `run_pipeline()` from `run_real.py` | Yes -- calls real pipeline | FLOWING |
| `api/labels.py` | `row["panels"]` | `supabase.table("labels").select()` | Yes -- reads from Supabase | FLOWING |
| `api/middleware.py` | `log_entry` | Computed from `request` + `response` | Yes -- real request data | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite passes | `python3 -m pytest roof_pipeline/ -x -q` | 80 passed in 3.34s | PASS |
| FastAPI app imports without error | `python3 -c "from roof_pipeline.api.main import app"` | `app import OK` (with Settings warning, expected without .env) | PASS |
| `run_pipeline()` imports with correct signature | `python3 -c "from roof_pipeline.run_real import run_pipeline, main, _load_dsm; print('OK')"` | 14 params, returns `dict[str, Path]` | PASS |
| `from __future__ import annotations` in all API modules | grep across `roof_pipeline/api/` | 13 files matched (all `.py` except `__init__.py` which is a 1-line docstring) | PASS |
| No TODO/FIXME/placeholder anti-patterns | grep across `roof_pipeline/api/` | 0 matches | PASS |
| `.env` is gitignored, `.env.example` is tracked | grep `.gitignore` | `.env`, `.env.*`, `!.env.example` all present | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| API-01 | 04-03 | POST /snap-preview accepts mask.json, returns feature graph + snapped polygons | SATISFIED | `snap.py` implements full endpoint with `snap_polygons()` via `asyncio.to_thread()`. 11 tests pass. Response contains `feature_graph.features` and `feature_graph.edges`. |
| API-02 | 04-02, 04-04 | POST /run-pipeline triggers full pipeline run, writes status to pipeline_runs | SATISFIED | `run_real.py` refactored with `run_pipeline()` callable. `pipeline.py` returns 202, inserts queued row, schedules background task with `asyncio.to_thread()`, updates status at boundaries, uploads to Storage. 8 tests pass. |
| API-03 | 04-04 | POST/GET /labels/{sampleId} persists and retrieves panel label data | SATISFIED | `labels.py` implements upsert save and select retrieve with 404 handling. 6 tests pass including round-trip coordinate preservation. |
| OBSERVABILITY-01a | 04-01, 04-03 | Structured JSON logging (trace_id, sample_id, endpoint, latency_ms, error_type) | SATISFIED | `middleware.py` generates all 5 fields, emits JSON log line, sets X-Trace-ID header. 6 middleware tests verify all fields. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | -- | -- | -- | No anti-patterns detected across all 17 API source files |

### CONTEXT.md Decision Compliance

| Decision | Honored | Evidence |
|----------|---------|----------|
| D-01: API lives in `roof_pipeline/api/` | Yes | All API code in `roof_pipeline/api/` subpackage |
| D-02: Router-per-domain layout | Yes | `snap.py`, `pipeline.py`, `labels.py` as separate routers mounted in `main.py` |
| D-04: `supabase-py` SDK | Yes | `from supabase import create_client, Client` in deps.py |
| D-05: `.env` via pydantic-settings | Yes | `config.py` uses `BaseSettings` with `env_file=".env"` |
| D-07: Labels table schema deferred to Phase 5 | Yes | `labels.py` docstring: "Table schema is deferred to Phase 5 per D-07" |
| D-09: POST /run-pipeline returns 202 | Yes | `pipeline.py` line 223: `status_code=202` |
| D-10: BackgroundTasks with stage-boundary updates | Yes | `_run_pipeline_bg()` with `_update_status()` calls, `BackgroundTasks.add_task()` |
| D-11: Entire background task in try/except | Yes | Lines 105-220: outer try/except catches all, inner try/except catches DB write failures |
| D-12: `asyncio.to_thread()` for CPU-bound work | Yes | `snap.py` line 77, `pipeline.py` line 156 both use `asyncio.to_thread()` |
| D-13: Output files to Supabase Storage | Yes | `_upload_output()` with content-type mapping, `storage.from_(bucket).upload()` |
| D-14: No Celery, arq as future escape hatch | Yes | No Celery anywhere. Uses BackgroundTasks. |

### RESEARCH.md Pitfall Coverage

| Pitfall | Mitigated | Evidence |
|---------|-----------|----------|
| 1. Event loop blocking | Yes | `asyncio.to_thread()` used in both `snap.py` and `pipeline.py` |
| 2. Storage content-type | Yes | `_CONTENT_TYPES` dict maps `.pdf`, `.gltf`, `.obj`, `.json` to explicit MIME types |
| 3. Background task silent failure | Yes | D-11 double try/except pattern in `_run_pipeline_bg()` |
| 4. Schema drift Pydantic/Zod | N/A | No Zod schemas yet (Phase 5) |
| 5. run_real.py refactor breaks CLI | Yes | `main()` preserved at line 220, `run_pipeline()` extracted cleanly, all 80 tests pass |

### Human Verification Required

### 1. Snap Preview Performance on Real Data

**Test:** Start the FastAPI server with valid `.env` credentials and POST `/api/snap/preview` with a 12-panel hip-and-valley roof body (the fb7e705c sample or equivalent).
**Expected:** Response returns in under 500ms with feature_graph containing valence-3+ features and snapped polygon coordinates.
**Why human:** The 500ms performance target from ROADMAP SC-1 requires real 12-panel roof data and a running server. Cannot be verified programmatically without the DSM/mask files.

### 2. End-to-End Pipeline Run via HTTP

**Test:** With a running server and Supabase configured (tables + Storage), POST `/api/pipeline/run` with a valid `sample_id` that has DSM/mask files in Supabase Storage. Then poll `GET /api/pipeline/run/{run_id}` repeatedly.
**Expected:** Status progresses through `queued` -> `running` (with stage_name updates) -> `done`. Output files (PDF, OBJ, glTF, JSON) appear in Supabase Storage under `runs/{run_id}/`.
**Why human:** Requires live Supabase instance with tables created, DSM/mask files uploaded to Storage, and a running uvicorn server. Cannot be tested without external service.

### 3. Labels Round-Trip via Live Supabase

**Test:** POST `/api/labels/test-sample` with panel data containing high-precision float coordinates, then GET `/api/labels/test-sample`.
**Expected:** Retrieved coordinates match posted coordinates exactly (no float rounding by Supabase jsonb).
**Why human:** While tests verify via mock, the actual Supabase jsonb serialization round-trip needs a live database to confirm no precision loss.

### Gaps Summary

No gaps found. All 4 observable truths are verified with full evidence at all levels (existence, substance, wiring, data flow). All 4 requirement IDs (API-01, API-02, API-03, OBSERVABILITY-01a) are satisfied with test coverage. All CONTEXT.md decisions are honored. All RESEARCH.md pitfalls are mitigated. All 80 tests pass (49 existing + 31 new API tests).

Status is `human_needed` because 3 items require human testing with a live Supabase instance and real roof data.

---

_Verified: 2026-04-19T17:26:36Z_
_Verifier: Claude (gsd-verifier)_
