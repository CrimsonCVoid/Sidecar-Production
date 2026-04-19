# Requirements: Topology-Aware Snap Engine (Milestone 1)

**Defined:** 2026-04-18
**Core Value:** Hip and ridge apex convergences (3+ panels) must weld to a single geometrically-correct point with zero slivers in the output mesh.

## v1 Requirements

Requirements for Milestone 1. Each maps to roadmap phases.

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

- [x] **VALID-01**: JSON schema validation at `polygons_from_clicks` boundary using Pydantic or dataclass + manual checks — this is now a security surface since the dashboard will write to this contract over HTTP
- [x] **VALID-02**: Schema rejects malformed polygon data (missing fields, wrong types, empty vertex arrays) with actionable error messages

### Integration

- [x] **INTG-01**: `run_real.py` accepts `--snap-v2` flag, default off; when on, routes through `panel_snap_v2.snap_polygons` instead of `snap_shared_edges`
- [x] **INTG-02**: When `--snap-v2` is active, emit JSON sidecar `output/snap_v2_features.json` with schema `{features: [{id, valence, position_xyz, panel_ids}], edges: [{panel_a, panel_b, feature_ids}]}`
- [x] **INTG-03**: All downstream modules (`mesh.py`, `shop_drawings.py`, `cutsheets.py`, `ts_export.py`, `ts_render_pdf.py`) produce structurally equivalent output on the synthetic gable smoke test when `--snap-v2` is used (structural match, not byte-identical, due to D-02 per-plane Z)

### Test Suite

- [x] **TEST-01**: `test_gable_two_panels_unchanged` — deterministic v2 output verified via tiered golden-file comparison; structural equivalence with v1 confirmed
- [x] **TEST-02**: `test_hip_apex_four_panels_welds` — four panels at one point, all four output polygons contain exact same (x, y, z) at that apex
- [x] **TEST-03**: `test_ridge_three_panels_welds` — three panels, ridge apex, same exact-point requirement
- [x] **TEST-04**: `test_transitive_cluster_above_tol` — three points at pairwise distances (0.9, 0.9, 1.3) with tol=1.0 must cluster via multi-pass expansion
- [x] **TEST-05**: `test_mixed_winding_hip` — two panels traversing shared edge in opposite order; winding normalization produces correct feature graph
- [x] **TEST-06**: `test_self_intersecting_input_repaired` — crossed-edge input, output must be `is_valid`
- [x] **TEST-07**: `test_l_shaped_panel_winding` — non-convex L-shaped panel, winding normalization must not flip polygon due to interior notch

## v2 Requirements (Milestone 2)

Deferred to follow-up milestone. Tracked but not in current roadmap.

### FastAPI Sidecar

- **API-01**: Snap-preview endpoint wrapping `panel_snap_v2` on existing DigitalOcean droplet
- **API-02**: Accepts mask.json, returns feature graph + snapped polygons

### Next.js Labeling Dashboard

- **DASH-01**: Per-sample labeling route (`/labeling/[sampleId]`) with Konva canvas
- **DASH-02**: Shared-node magnet (12px snap radius, shift-click override, visual label)
- **DASH-03**: Undo/redo via Zustand + zundo, Cmd+Z / Cmd+Shift+Z
- **DASH-04**: Snap preview mode with valence-colored feature dots
- **DASH-05**: Output mask.json compatible with `polygons_from_clicks`

### Dashboard Index

- **DIDX-01**: Sample table with address, click count, snap-status badge
- **DIDX-02**: Filter chips (needs review, v2-verified, failed validation)
- **DIDX-03**: Diff viewer for side-by-side PDF comparison
- **DIDX-04**: Run monitor via Supabase Realtime

## Out of Scope

| Feature | Reason |
|---------|--------|
| Edge semantic classification (ridge/hip/valley/eave/rake) | Next milestone after dashboard |
| Penetration labeling (chimneys, skylights, vents) | Future milestone |
| Face-segmentation NN training target | Way later |
| Multi-user concurrent editing | Complexity not justified |
| Removing matplotlib labeler | Kept as CLI fallback |
| shop_drawings.py subpackage extraction | 2089 lines but deferred; do not refactor this milestone |
| Performance optimization of O(N^2) | Topology fix improves scaling as side effect; do not reframe as perf work |

## Traceability

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

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 22
- Complete: 22
- Unmapped: 0

---
*Requirements defined: 2026-04-18*
*Last updated: 2026-04-19 after 02-04 execution -- all 22 requirements complete*
