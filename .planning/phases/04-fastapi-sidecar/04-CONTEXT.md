# Phase 4: FastAPI Sidecar - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose the snap engine and pipeline over HTTP from a FastAPI sidecar on the existing DigitalOcean droplet. Three endpoint groups: snap-preview, pipeline-run, and label persistence. Structured JSON logging for production observability. No frontend work, no dashboard UI.

</domain>

<decisions>
## Implementation Decisions

### Server structure
- **D-01:** FastAPI app lives inside `roof_pipeline/api/` as a subpackage. Direct imports to pipeline modules — no separate repo or sibling directory.
- **D-02:** Router-per-domain layout: `api/snap.py`, `api/pipeline.py`, `api/labels.py` as separate FastAPI routers, mounted in `api/main.py`. Mirrors the 3 endpoint groups.
- **D-03:** Deployment via systemd + uvicorn on the existing DO droplet. No Docker, no container orchestration.

### Supabase integration
- **D-04:** Use `supabase-py` official SDK for all Supabase operations (reads, writes, storage uploads).
- **D-05:** Credentials (SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY) loaded from `.env` file via pydantic-settings. `.env` is gitignored.
- **D-06:** Phase 4 creates TWO new pipeline-owned tables:
  - `pipeline_runs`: id (uuid pk), sample_id (uuid fk -> samples), status (text: 'queued'|'running'|'done'|'error'), stage_name (text), progress_pct (int), error_message (text null), started_at (timestamptz), completed_at (timestamptz null)
  - `snap_features`: id (uuid pk), sample_id (uuid fk -> samples), run_id (uuid fk -> pipeline_runs), feature_graph (jsonb — the snap_v2_features.json content), created_at (timestamptz)
- **D-07:** Panel labels table (API-03) is deferred to Phase 5. The labeler is the natural owner of that table's schema. Phase 4's label endpoint reads/writes whatever Phase 5 defines. For Phase 4 planning, stub the label endpoint with the interface contract but mark the table schema as TBD.
- **D-08:** `samples` table treated as pre-existing. User will provide Supabase schema dump before Phase 4 execution to confirm what exists.

### Pipeline run strategy
- **D-09:** POST /run-pipeline returns 202 Accepted with `{"run_id": uuid, "status_url": "/api/pipeline/run/{run_id}"}`. Frontend polls status_url or subscribes via Supabase Realtime on `pipeline_runs` table.
- **D-10:** Pipeline runs in FastAPI `BackgroundTasks`. Writes to `pipeline_runs` at each stage boundary: plane_fits -> boundaries -> snap -> mesh -> cutsheets -> shop_drawings -> done. Updates `progress_pct` and `stage_name` on each boundary.
- **D-11:** Entire background task wrapped in try/except. On any exception: write status='error' + error_message to `pipeline_runs`, log full traceback. Never let a background task die silently.
- **D-12:** Use `asyncio.to_thread()` for the CPU-bound pipeline work. The pipeline is synchronous numpy/shapely/reportlab — pure BackgroundTasks without `to_thread()` will block the uvicorn event loop on a 20-second mesh build.
- **D-13:** Output files (PDFs, OBJ, glTF, features JSON) uploaded to Supabase Storage, not served from local disk. Storage paths stored in `pipeline_runs` row for frontend download.
- **D-14:** Migration plan: when a single run exceeds 60s OR concurrent runs exceed 3, migrate to arq (Redis-backed, lightweight). Not needed for Phase 4/5 — droplet is single-user for MVP. Do NOT use Celery — too heavyweight for current scale. arq is the escape hatch.

### Claude's Discretion
- Exact pydantic-settings config model layout
- Structured logging middleware implementation details (trace_id generation, timing hooks)
- FastAPI dependency injection patterns for Supabase client
- Exact error response JSON shape (beyond the requirement for trace_id, sample_id, endpoint, latency_ms, error_type)
- CORS configuration for the Next.js frontend origin

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Pipeline entry points (what the API wraps)
- `roof_pipeline/run_real.py` -- Current CLI orchestrator. The `/run-pipeline` endpoint wraps this logic. Read the `main()` function and `_load_dsm()` to understand the pipeline stages.
- `roof_pipeline/panel_snap_v2/__init__.py` -- `snap_polygons()` public API. The `/snap-preview` endpoint calls this directly.
- `roof_pipeline/panel_snap_v2/graph.py` -- `build_feature_graph()` and `print_dryrun()`. Feature graph construction that `/snap-preview` needs.

### Input validation (shared with API)
- `roof_pipeline/panel_snap_v2/schema.py` -- Pydantic schema for panel click data. Already handles duplicate-corner dedup. The HTTP API reuses this exact schema (D-01 from Phase 3).
- `roof_pipeline/boundaries.py` -- `polygons_from_clicks()` consumes `PanelsInput` from schema.py. The API calls this function.

### Output formats (what the API serves)
- `roof_pipeline/mesh.py` -- `export_mesh()` returns dict of output paths (OBJ, glTF). These get uploaded to Supabase Storage per D-13.
- `roof_pipeline/ts_export.py` -- JSON sidecar format. Feature graph JSON schema documented in INTG-02.

### Prior phase decisions
- `.planning/phases/02-apex-solver-integration/02-CONTEXT.md` -- D-04 (two-pass validation), D-08 (Pydantic at boundary). Locked.
- `.planning/phases/03-bug-fixes/03-CONTEXT.md` -- D-01 (dedup in schema.py serves both CLI and HTTP). Locked.

### Requirements
- `.planning/REQUIREMENTS.md` -- Phase 4 requirements: API-01, API-02, API-03, OBSERVABILITY-01a

### Pitfalls
- `.planning/STATE.md` -- Pitfall #5: Schema drift between Pydantic and Zod. Define contracts before implementing both sides.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `panel_snap_v2/schema.py` (PanelsInput, PanelCorners): Pydantic input validation — reuse directly as the request body schema for `/snap-preview` and `/labels`
- `snap_polygons()` in `panel_snap_v2/__init__.py`: The core function `/snap-preview` wraps
- `run_real.py` main() pipeline stages: Template for the background task's stage-boundary status updates
- `build_feature_graph()` in `graph.py`: Produces the feature graph JSON that gets stored in `snap_features` table

### Established Patterns
- Pydantic `BaseModel` with `ConfigDict(strict=True, extra="forbid")` for input schemas
- Module-level logger: `log = logging.getLogger(__name__)` in every file
- `from __future__ import annotations` in every file
- Copy-on-write: `out = {pid: poly.copy() ...}` for polygon mutation
- All geometry internal in meters; conversion at output boundaries only

### Integration Points
- `roof_pipeline/api/main.py` -- New FastAPI app entry point, mounts routers
- `roof_pipeline/api/snap.py` -- Imports `snap_polygons`, `build_feature_graph` from `panel_snap_v2`
- `roof_pipeline/api/pipeline.py` -- Imports pipeline stages from `run_real.py` (needs refactoring into callable functions, not just `main()`)
- `roof_pipeline/api/labels.py` -- Supabase read/write for panel labels (stub until Phase 5 defines table)
- `requirements.txt` -- Needs: `fastapi`, `uvicorn[standard]`, `supabase`, `python-dotenv` (or `pydantic-settings`)

</code_context>

<specifics>
## Specific Ideas

- The user explicitly rejected Celery and subprocess approaches. arq is the only acceptable queue migration path, and only when triggered by the 60s/3-concurrent thresholds.
- Output files must go to Supabase Storage, not local disk — the frontend downloads from Supabase, not from the sidecar.
- The label endpoint (API-03) is intentionally deferred in table schema — Phase 5 owns that. Phase 4 builds the endpoint interface but the backing table comes later.
- User will provide Supabase schema dump before execution to confirm what tables already exist in the My Metal Roofer project.
- `asyncio.to_thread()` is mandatory for the pipeline background task — the pipeline is CPU-bound synchronous code that would block the event loop otherwise.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 04-fastapi-sidecar*
*Context gathered: 2026-04-19*
