# Phase 4: FastAPI Sidecar - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 04-fastapi-sidecar
**Areas discussed:** Server structure, Supabase integration, Pipeline run strategy

---

## Server structure

### App location

| Option | Description | Selected |
|--------|-------------|----------|
| Inside roof_pipeline/ | e.g. roof_pipeline/api/ -- keeps everything in one Python package, direct imports | |
| Sibling directory | e.g. api/ at repo root -- separates concerns, imports roof_pipeline as a package | |
| Separate repo | New repo for the API server -- installs roof_pipeline as a dependency | |

**User's choice:** Inside roof_pipeline/
**Notes:** None

### Internal layout

| Option | Description | Selected |
|--------|-------------|----------|
| Single module | One file (roof_pipeline/api/main.py) with all routes | |
| Router-per-domain | Separate routers: api/snap.py, api/pipeline.py, api/labels.py | |
| You decide | Claude picks the right granularity | |

**User's choice:** Router-per-domain
**Notes:** None

### Deployment strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Systemd + uvicorn | Direct uvicorn process managed by systemd | |
| Docker container | Dockerfile + docker-compose on the droplet | |
| You decide | Claude picks based on existing DO setup | |

**User's choice:** Systemd + uvicorn
**Notes:** None

---

## Supabase integration

### Client library

| Option | Description | Selected |
|--------|-------------|----------|
| supabase-py client | Official supabase-py SDK -- high-level, handles auth/realtime | |
| Direct REST via httpx | Call Supabase PostgREST API directly -- no new SDK dep | |
| You decide | Claude picks based on what endpoints actually need | |

**User's choice:** supabase-py client
**Notes:** None

### Credentials

| Option | Description | Selected |
|--------|-------------|----------|
| .env file | Standard .env loaded by python-dotenv or pydantic-settings | |
| Environment vars only | Set in systemd unit file or shell profile | |
| You decide | Claude picks the standard approach | |

**User's choice:** .env file
**Notes:** None

### Table strategy

| Option | Description | Selected |
|--------|-------------|----------|
| New tables | Create pipeline_runs + panel_labels with API-designed schema | |
| Reuse existing | Write to whatever tables the Next.js frontend already uses | |
| You decide | Claude investigates and picks | |

**User's choice:** Other (detailed proposal)
**Notes:** User provided detailed 3-part proposal:
1. Two new pipeline-owned tables: `pipeline_runs` (status tracking) and `snap_features` (feature graph storage) with full schema specified
2. Label table deferred to Phase 5 -- labeler owns that schema
3. `samples` table treated as pre-existing; user will provide schema dump before execution

---

## Pipeline run strategy

### Execution model

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI BackgroundTasks | Return 202 immediately, run pipeline in background task | |
| Async queue (Celery/ARQ) | Enqueue job to Redis-backed worker | |
| Subprocess + polling | Spawn run_real.py as subprocess, poll for completion | |
| You decide | Claude picks based on concurrency/droplet constraints | |

**User's choice:** FastAPI BackgroundTasks (with 7 specifics)
**Notes:** User provided detailed 7-point specification:
1. Return 202 with run_id and status_url
2. Stage-boundary status updates to pipeline_runs
3. Try/except wrapping entire background task -- never silent failures
4. asyncio.to_thread() for CPU-bound pipeline work
5. Output files uploaded to Supabase Storage, paths in pipeline_runs
6. Migration to arq when >60s or >3 concurrent runs
7. No Celery -- too heavyweight; arq is the escape hatch

Explicitly rejected: Celery (too heavyweight), subprocess (worse than BackgroundTasks), Claude decides (durable architectural decision)

---

## Claude's Discretion

- Pydantic-settings config model layout
- Structured logging middleware implementation details
- FastAPI dependency injection patterns for Supabase client
- Error response JSON shape details
- CORS configuration

## Deferred Ideas

None
