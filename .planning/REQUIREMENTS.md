# Requirements: My Metal Roofer

**Defined:** 2026-04-18
**Core Value:** Hip and ridge apex convergences (3+ panels) must weld to a single geometrically-correct point with zero slivers in the output mesh.

## v1 Requirements (Milestone 1 — Complete)

All 22 requirements delivered. See traceability table below.

### Topology Engine

- [x] **TOPO-01**: `snap_polygons(polygons, planes, tol)` returns `dict[int, ndarray]` — same I/O shape as `snap_shared_edges` so orchestrator swaps with one line
- [x] **TOPO-02**: Union-find clusters all polygon vertices using three-pass expanding tolerance (0.3t -> 0.6t -> t) so transitively-connected hip apices get grouped
- [x] **TOPO-03**: Feature graph built from clusters — nodes = clusters, edges = "panel P touches cluster C", each cluster classified by valence (corner=2, ridge_apex=3, hip_apex=4+)
- [x] **TOPO-04**: Per-panel CCW winding normalization before graph build, correctly handling non-convex (L-shaped) panels without flipping due to interior notch
- [x] **TOPO-05**: Valence-2 clusters resolved via XY centroid + per-plane Z reconstruction (matches current behavior)
- [x] **TOPO-06**: Valence-3 clusters resolved via closed-form 3x3 plane intersection (`numpy.linalg.solve`)
- [x] **TOPO-07**: Valence-4+ clusters resolved via least-squares plane intersection (`numpy.linalg.lstsq`) with rows weighted by `1/rms_residual`
- [x] **TOPO-08**: Solved apex point written back into every member panel's vertex array at the correct index
- [x] **TOPO-09**: Edge-walking densify: for each shared-edge feature, collect all vertices from touching panels, sort by parameter t along the shared edge line, redistribute so every panel carries the same vertex list along that edge
- [x] **TOPO-10**: Shapely validation pass after snapping — each polygon checked with `is_valid` + `is_simple`; on failure, attempt `make_valid()` repair; if still invalid, raise with panel ID
- [x] **TOPO-11**: No new dependencies added to the pipeline module — only scipy, numpy, shapely (all already in requirements.txt). Pydantic exception accepted per D-07.

### Input Validation

- [x] **VALID-01**: JSON schema validation at `polygons_from_clicks` boundary using Pydantic — security surface since dashboard writes to this contract over HTTP
- [x] **VALID-02**: Schema rejects malformed polygon data (missing fields, wrong types, empty vertex arrays) with actionable error messages

### Integration

- [x] **INTG-01**: `run_real.py` accepts `--snap-v2` flag, default off; when on, routes through `panel_snap_v2.snap_polygons` instead of `snap_shared_edges`
- [x] **INTG-02**: When `--snap-v2` is active, emit JSON sidecar `output/snap_v2_features.json` with schema `{features: [{id, valence, position_xyz, panel_ids}], edges: [{panel_a, panel_b, feature_ids}]}`
- [x] **INTG-03**: All downstream modules produce structurally equivalent output on the synthetic gable smoke test when `--snap-v2` is used

### Test Suite

- [x] **TEST-01**: `test_gable_two_panels_unchanged` — deterministic v2 output verified via tiered golden-file comparison
- [x] **TEST-02**: `test_hip_apex_four_panels_welds` — four panels at one point, all four output polygons contain exact same (x, y, z) at that apex
- [x] **TEST-03**: `test_ridge_three_panels_welds` — three panels, ridge apex, same exact-point requirement
- [x] **TEST-04**: `test_transitive_cluster_above_tol` — three points at pairwise distances (0.9, 0.9, 1.3) with tol=1.0 must cluster via multi-pass expansion
- [x] **TEST-05**: `test_mixed_winding_hip` — two panels traversing shared edge in opposite order; winding normalization produces correct feature graph
- [x] **TEST-06**: `test_self_intersecting_input_repaired` — crossed-edge input, output must be `is_valid`
- [x] **TEST-07**: `test_l_shaped_panel_winding` — non-convex L-shaped panel, winding normalization must not flip polygon due to interior notch

## v2 Requirements (Milestone 2 — Active)

### Bug Fixes

- [ ] **FIX-01**: Investigate and fix densify make_valid MultiPolygon 65.9% area loss on fb7e705c panel 8 (12-panel hip-and-valley roof) — pipeline completes without area-change rejection
- [ ] **FIX-02**: Golden-file regression test for 12-panel hip-and-valley roof ensuring densify passes without area-change rejection
- [ ] **LABEL-01**: Silent duplicate-corner removal in winding normalization — protects legacy mask.json files already in Supabase without breaking valid polygons

### FastAPI Sidecar

- [ ] **API-01**: POST /snap-preview accepts mask.json, returns feature graph + snapped polygons (<500ms target)
- [ ] **API-02**: POST /run-pipeline triggers full pipeline run, writes status to Supabase pipeline_runs table
- [ ] **API-03**: POST/GET /labels/{sampleId} persists and retrieves panel label data via Supabase

### Labeling Dashboard

- [ ] **DASH-01**: Per-sample labeling route (`/labeling/[sampleId]`) with Konva canvas on hillshade
- [ ] **DASH-02**: Shared-node magnet (12px snap radius, shift-click override, visual indicator)
- [ ] **DASH-03**: Undo/redo via Zustand + zundo, Cmd+Z / Cmd+Shift+Z
- [ ] **DASH-04**: Snap preview mode with valence-colored feature dots
- [ ] **DASH-05**: Output mask.json compatible with `polygons_from_clicks`
- [ ] **DASH-06**: Auto-close polygon when cursor within 10px of first vertex (prevents duplicate corners)

### Dashboard Index

- [ ] **DIDX-01**: Sample table with address, click count, snap-status badge
- [ ] **DIDX-02**: Filter chips (needs review, v2-verified, failed validation)
- [ ] **DIDX-03**: Diff viewer for side-by-side PDF comparison
- [ ] **DIDX-04**: Run monitor via Supabase Realtime

### Testing

- [ ] **TESTING-01**: Playwright E2E tests for critical labeling flows — label-save-reload, undo-redo, magnet-snap-override (minimum 3 tests)

### Observability

- [ ] **OBSERVABILITY-01**: Structured JSON logging for FastAPI sidecar (trace_id, sample_id, endpoint, latency_ms, error_type) + browser-side error capture to backend endpoint or Sentry

## Out of Scope

| Feature | Reason |
|---------|--------|
| 3D mesh viewer | Future milestone |
| Vertex drag with live re-snap | Future milestone |
| Edge semantic classification (ridge/hip/valley/eave/rake) | Future milestone |
| Penetration labeling (chimneys, skylights, vents) | Future milestone |
| Face-segmentation NN training target | Way later |
| Multi-user concurrent editing | Complexity not justified |
| Removing matplotlib labeler | Kept as CLI fallback |
| shop_drawings.py subpackage extraction | 2089 lines but deferred |
| Performance optimization of O(N^2) | Topology fix improves scaling as side effect |

## Traceability

### Milestone 1 (Complete)

| Requirement | Phase | Status |
|-------------|-------|--------|
| TOPO-01 | Phase 1 | Complete (01-03) |
| TOPO-02 | Phase 1 | Complete (01-02) |
| TOPO-03 | Phase 1 | Complete (01-03) |
| TOPO-04 | Phase 1 | Complete (01-01) |
| TOPO-05 | Phase 2 | Complete (02-01) |
| TOPO-06 | Phase 2 | Complete (02-01) |
| TOPO-07 | Phase 2 | Complete (02-01) |
| TOPO-08 | Phase 2 | Complete (02-01) |
| TOPO-09 | Phase 2 | Complete (02-03) |
| TOPO-10 | Phase 2 | Complete (02-03) |
| TOPO-11 | Phase 1 | Complete (01-03, D-07 exception) |
| VALID-01 | Phase 2 | Complete (02-02) |
| VALID-02 | Phase 2 | Complete (02-02) |
| INTG-01 | Phase 2 | Complete (02-04) |
| INTG-02 | Phase 2 | Complete (02-04) |
| INTG-03 | Phase 2 | Complete (02-04) |
| TEST-01 | Phase 2 | Complete (02-04) |
| TEST-02 | Phase 2 | Complete (02-01) |
| TEST-03 | Phase 2 | Complete (02-01) |
| TEST-04 | Phase 1 | Complete (01-02) |
| TEST-05 | Phase 1 | Complete (01-03) |
| TEST-06 | Phase 2 | Complete (02-03) |
| TEST-07 | Phase 1 | Complete (01-01) |

### Milestone 2 (Active)

| Requirement | Phase | Status |
|-------------|-------|--------|
| FIX-01 | — | Not started |
| FIX-02 | — | Not started |
| LABEL-01 | — | Not started |
| API-01 | — | Not started |
| API-02 | — | Not started |
| API-03 | — | Not started |
| DASH-01 | — | Not started |
| DASH-02 | — | Not started |
| DASH-03 | — | Not started |
| DASH-04 | — | Not started |
| DASH-05 | — | Not started |
| DASH-06 | — | Not started |
| DIDX-01 | — | Not started |
| DIDX-02 | — | Not started |
| DIDX-03 | — | Not started |
| DIDX-04 | — | Not started |
| TESTING-01 | — | Not started |
| OBSERVABILITY-01 | — | Not started |

**Coverage:**
- v1 requirements: 22 total, 22 complete
- v2 requirements: 18 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 18

---
*Requirements defined: 2026-04-18*
*Last updated: 2026-04-19 — Milestone 2 requirements defined (18 requirements)*
