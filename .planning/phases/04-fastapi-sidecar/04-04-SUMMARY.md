---
phase: 04-fastapi-sidecar
plan: 04
subsystem: api
tags: [fastapi, pipeline-run, background-task, supabase-storage, labels, api-02, api-03, integration-tests]

# Dependency graph
requires:
  - phase: 04-fastapi-sidecar
    plan: 01
    provides: "FastAPI app factory with CORS, structured logging, error handlers, stub routers, schemas"
  - phase: 04-fastapi-sidecar
    plan: 02
    provides: "run_pipeline() callable function and _load_dsm() at module level"
provides:
  - "Working POST /api/pipeline/run endpoint with 202 Accepted and background task (API-02)"
  - "Working GET /api/pipeline/run/{run_id} status polling endpoint (API-02)"
  - "Working POST/GET /api/labels/{sample_id} CRUD endpoints (API-03)"
  - "8-test pipeline test suite covering trigger, status polling, background task"
  - "6-test labels test suite covering save, retrieve, round-trip coordinate preservation"
affects: [05-labeling-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns: [background-task-with-status-tracking, supabase-storage-upload, content-type-mapping, upsert-on-conflict, d11-error-handler]

key-files:
  created:
    - roof_pipeline/api/tests/test_pipeline.py
    - roof_pipeline/api/tests/test_labels.py
  modified:
    - roof_pipeline/api/pipeline.py
    - roof_pipeline/api/labels.py

key-decisions:
  - "Pipeline background task downloads DSM/mask from Supabase Storage to temp directory, runs pipeline via asyncio.to_thread, uploads outputs back to Storage"
  - "Feature graph from snap v2 stored in snap_features table alongside pipeline_runs for downstream dashboard use"
  - "Labels endpoint uses upsert with on_conflict=sample_id for idempotent save operations"

patterns-established:
  - "_upload_output() with explicit content-type mapping per file extension to prevent Supabase defaulting to text/plain"
  - "_update_status() helper for consistent pipeline_runs table updates at stage boundaries"
  - "D-11 double try/except: outer catches pipeline errors, inner catches DB-write errors, log.exception always fires"
  - "Labels upsert pattern: insert-or-update on sample_id conflict key"

requirements-completed: [API-02, API-03]

# Metrics
duration: 22min
completed: 2026-04-19
---

# Phase 4 Plan 4: Pipeline Run + Labels Endpoints Summary

**Pipeline run endpoint with BackgroundTasks + asyncio.to_thread, Supabase Storage upload with explicit content-types, labels CRUD with upsert, and 14-test API suite for API-02 and API-03**

## Performance

- **Duration:** 22 min
- **Started:** 2026-04-19T16:58:56Z
- **Completed:** 2026-04-19T17:21:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- POST /api/pipeline/run returns 202 with run_id and status_url, inserts queued row in pipeline_runs
- Background task downloads DSM/mask from Supabase Storage, runs full pipeline via asyncio.to_thread (D-12), updates status at stage boundaries (D-10), uploads output files with explicit content-types (D-13)
- Exception handler writes status=error + error_message on any failure, never dies silently (D-11)
- Feature graph stored in snap_features table when snap v2 is used
- GET /api/pipeline/run/{run_id} returns current status from pipeline_runs table
- POST /api/labels/{sample_id} upserts panel label data with coordinate preservation
- GET /api/labels/{sample_id} retrieves label data, returns 404 when absent
- Full test suite: 80 tests pass (49 panel_snap_v2 + 31 API tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement pipeline run endpoint with background task and Supabase integration** - `a925c91` (feat)
2. **Task 2: Implement labels endpoint and create pipeline + labels test suites** - `b93f7bb` (feat)

## Files Created/Modified

- `roof_pipeline/api/pipeline.py` - Replaced stub with full implementation: trigger_pipeline_run (202), get_run_status, _run_pipeline_bg (background task with stage-boundary status tracking), _upload_output (Storage with content-types), _update_status helper
- `roof_pipeline/api/labels.py` - Replaced stub with full implementation: save_labels (upsert), get_labels (select with 404)
- `roof_pipeline/api/tests/test_pipeline.py` - 8 tests: TestPipelineRunTrigger (trigger 202, run_id + status_url, queued row insert, malformed 422), TestPipelineRunStatus (existing run 200, nonexistent 404), TestPipelineBackgroundTask (status update calls, content type mapping)
- `roof_pipeline/api/tests/test_labels.py` - 6 tests: TestLabelSave (save 200, upsert call, coordinate preservation), TestLabelRetrieve (existing 200, nonexistent 404, round-trip coordinate fidelity)

## Decisions Made

- **Storage download/upload pattern:** Background task downloads DSM and mask files from Supabase Storage to a temporary directory, runs the pipeline locally, then uploads all output files back to Storage. The temp directory is cleaned up automatically via context manager (T-04-13).
- **Feature graph persistence:** When snap v2 is used, the feature graph JSON is stored in the snap_features table alongside the pipeline_runs row. This provides the downstream dashboard with topology data without re-running the snap engine.
- **Labels upsert:** Uses Supabase upsert with on_conflict="sample_id" for idempotent save operations. Repeat saves for the same sample overwrite the previous label data.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - both tasks completed cleanly.

## Self-Check: PASSED
