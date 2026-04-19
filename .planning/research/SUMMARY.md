# Research Summary -- Milestone 2

**Project:** FastAPI Sidecar + Labeling Dashboard (Milestone 2 of 2)
**Domain:** HTTP API wrapping topology-aware snap engine + interactive canvas-based polygon annotation with real-time pipeline monitoring
**Researched:** 2026-04-19
**Overall confidence:** HIGH

## Executive Summary

Milestone 1 delivered the `panel_snap_v2` topology-aware snap engine with 41 passing tests and all 22 requirements complete. The engine handles hip/ridge apex convergences correctly via union-find clustering, multi-plane intersection solving, edge densification, and Shapely validation. It is integrated behind `--snap-v2` in `run_real.py` with zero regressions on downstream modules.

Milestone 2 wraps this engine in a FastAPI sidecar and builds the Next.js labeling dashboard that replaces the matplotlib CLI labeler. Two real-data bugs (densify MultiPolygon at 65.9% area on fb7e705c panel 8, and labeler duplicate-corner dedup) must be fixed before the engine is exposed via API. The dashboard adds Konva-based polygon drawing with a shared-node magnet (12px snap radius) that eliminates the 3-8px ridge pair drift at the source, undo/redo via Zustand + zundo, snap preview with valence-colored feature dots, and a run monitor via Supabase Realtime.

The stack additions are conservative and well-verified. The Python sidecar adds three runtime dependencies (FastAPI, uvicorn, supabase-py) and two dev dependencies (httpx, pytest-cov). The frontend adds four packages (konva, react-konva, zustand, zundo) totaling under 200KB gzipped. Every library was verified against Context7 documentation and current PyPI/npm versions. The architectural decision to route pipeline monitoring through Supabase Postgres Changes (rather than a separate WebSocket server) eliminates an entire service from the deployment.

The highest-risk item in Milestone 2 is the densify bug on complex hip-and-valley roofs -- the `make_valid` repair produces a MultiPolygon where the largest piece is only 65.9% of the original area. This must be fixed before the FastAPI endpoint can accept production workloads. The second risk is the shared-node magnet UX: the client-side proximity detection is simple (~160 distance calculations per mousemove), but coordinating snap indicator rendering, shift-click override, and zundo transaction boundaries during drag operations requires careful Konva-specific implementation.

## Key Findings

**Stack:** FastAPI >=0.115 + uvicorn + supabase-py for Python sidecar; Konva 10.x + react-konva 19.x + Zustand 5.x + zundo 2.x for frontend. Zero changes to existing Python pipeline deps.

**Architecture:** Three-tier separation -- `panel_snap_v2` (pure geometry, no HTTP), FastAPI sidecar (thin adapter, direct function imports), Next.js dashboard (Konva canvas + Supabase data layer). Pipeline monitoring via Supabase Postgres Changes, not WebSocket from sidecar.

**Critical pitfall:** Densify bug (65.9% area loss on fb7e705c panel 8) must be fixed before FastAPI exposure. Undo state explosion from drag operations requires zundo `handleSet` + transaction boundaries.

## Implications for Roadmap

Based on research, the Milestone 2 work splits into phases ordered by dependency and risk:

1. **Bug Fixes (Python)** -- Fix densify and duplicate-corner bugs
   - Addresses: Densify MultiPolygon rejection, labeler dedup
   - Avoids: Shipping a broken API endpoint
   - Rationale: These block production use on complex roofs. Must fix before exposing via HTTP.

2. **FastAPI Sidecar + Schemas (Python)** -- API boundary and endpoints
   - Addresses: API-01, API-02 (snap-preview, run-pipeline endpoints)
   - Avoids: Schema drift (Pitfall 12) by defining Pydantic contracts first
   - Rationale: The sidecar is the bridge between the validated engine and the dashboard. Schemas must be locked before any frontend code writes or reads JSON.

3. **Labeling Canvas Core (Next.js)** -- Konva canvas with magnet snap and undo/redo
   - Addresses: DASH-01 through DASH-05 (canvas, magnet, undo, snap preview, mask.json output)
   - Avoids: Undo state explosion (Pitfall 8), Konva performance (Pitfall 9)
   - Rationale: Primary user interaction surface. Shared-node magnet is the key differentiator.

4. **Dashboard Index + Monitoring (Next.js)** -- Sample table, run monitor, diff viewer
   - Addresses: DIDX-01 through DIDX-04 (table, filters, diff, run monitor)
   - Avoids: Supabase Realtime silent disconnection (Pitfall 10)
   - Rationale: Secondary chrome around the canvas. Depends on both the API (to trigger runs) and the canvas (to display overlays).

### Phase Ordering Rationale

- **Bug fixes before API:** A broken densify path exposed via HTTP is worse than no API at all.
- **Schemas before canvas:** The mask.json and snap_v2_features.json contracts must be locked before the canvas writes or reads them. Schema drift between Pydantic and Zod is expensive to fix after both sides are implemented.
- **Canvas before dashboard index:** The labeling canvas is what users spend 90% of their time in. The index page is navigation. Ship the core interaction first.
- **Run monitor last:** Depends on both the API (to trigger pipeline runs with status writes) and Supabase Realtime (which is already in the stack). Standard patterns, low risk.

### Research Flags

- **Phase 3 (labeling canvas):** RESEARCH RECOMMENDED during planning. The shared-node magnet snap interaction (proximity detection during mousemove, visual indicator rendering, shift-click override coordination with Zustand), and zundo's `handleSet` API for drag-boundary transactions, involve enough Konva-specific API surface to warrant targeted research.
- **All other phases:** Standard patterns, SKIP research-phase. FastAPI + Pydantic, Supabase Realtime subscriptions, and Next.js server/client components are well-documented.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library APIs verified via Context7 against current stable versions. Version pins validated against PyPI/npm. |
| Features | HIGH | Feature set directly from PROJECT.md requirements. No speculative features. |
| Architecture | HIGH | Three-tier separation grounded in existing codebase. Supabase-as-pubsub eliminates a service. |
| Pitfalls | HIGH | Densify bug confirmed with specific data (65.9% on fb7e705c). Undo/drag pitfall confirmed in zundo docs. Supabase disconnection confirmed in official troubleshooting docs. |

## Gaps to Address

- **Densify root cause:** The 65.9% area loss may be a fundamental issue with edge-walking densification on panels sharing edges with 3+ neighbors, not just a tolerance tuning problem. Needs debugging before planning the fix.
- **Snap preview latency budget:** The <500ms target depends on DSM files being cached in-memory. Actual latency split between preprocessing (`polygons_from_clicks` + `fit_all_panels`) and the snap engine itself needs measurement.
- **JSON Schema single-source tooling:** No tool natively generates both Pydantic models and Zod schemas from a single source. The recommended approach (`datamodel-code-generator` for Python, `json-schema-to-zod` for TypeScript) needs a quick spike during Phase 2 planning.
- **Konva magnet indicator rendering:** The visual snap indicator ("-> P3.C1" label near cursor during hover) needs Konva-specific implementation details confirmed during Phase 3 planning.

---
*Research completed: 2026-04-19*
*Ready for roadmap: yes*
