# Roadmap: Topology-Aware Snap Engine (Milestone 1)

**Milestone:** Topology-Aware Snap Engine
**Granularity:** Standard
**Coverage:** 22/22 v1 requirements mapped

> Note: Dashboard/FastAPI work (Milestone 2) is explicitly out of scope for this roadmap.
> A follow-up milestone covers the FastAPI snap-preview endpoint, Next.js labeling dashboard
> (shared-node magnet, undo/redo, snap preview overlay), and the Supabase run monitor.

---

## Phases

- [x] **Phase 1: Feature Graph + Clustering** - Pure Python subpackage skeleton with winding normalization, union-find clustering, and feature graph construction; `--snap-v2-dryrun` flag prints graph and exits without touching downstream modules (completed 2026-04-18)
- [x] **Phase 2: Apex Solver + Integration** - Valence-aware apex solving, edge densification, Shapely validation, Pydantic input schema, `--snap-v2` integration in `run_real.py`, `snap_v2_features.json` sidecar output, all 41 tests green, gable smoke test structurally equivalent (completed 2026-04-19)

---

## Phase Details

### Phase 1: Feature Graph + Clustering
**Goal**: The `panel_snap_v2` subpackage exists as importable Python, correctly normalizes panel winding (including non-convex L-shaped panels), clusters vertices with three-pass expanding tolerance, and exposes the feature graph via `--snap-v2-dryrun` without invoking the solver or modifying any downstream module
**Depends on**: Nothing (first phase)
**Requirements**: TOPO-01, TOPO-02, TOPO-03, TOPO-04, TOPO-11, TEST-04, TEST-05, TEST-07
**Success Criteria** (what must be TRUE):
  1. Running `python run_real.py --snap-v2-dryrun <sample>` prints a feature graph (nodes with valence, edges with panel memberships) and exits with code 0 without writing any output files or invoking the solver
  2. A non-convex L-shaped panel (6-vertex concave polygon) is assigned correct CCW winding -- the normalization does not flip the polygon due to an interior notch -- confirmed by TEST-07 passing
  3. Three points at pairwise distances (0.9, 0.9, 1.3) with tol=1.0 are placed into a single cluster by the three-pass expanding tolerance -- confirmed by TEST-04 passing
  4. Two panels sharing an edge traversed in opposite winding order produce a correct feature graph (shared edge is identified, each panel appears in the edge's panel list) -- confirmed by TEST-05 passing
  5. `from roof_pipeline.panel_snap_v2 import snap_polygons` imports without error and the public signature matches `snap_shared_edges` (same argument and return types)
**Plans:** 3 plans
Plans:
- [x] 01-01-PLAN.md -- Winding normalization module + TDD test suite (TEST-07)
- [x] 01-02-PLAN.md -- Three-pass clustering module + TDD test suite (TEST-04)
- [x] 01-03-PLAN.md -- Feature graph, public API, --snap-v2-dryrun integration (TEST-05)

### Phase 2: Apex Solver + Integration
**Goal**: The complete `panel_snap_v2` engine is wired into `run_real.py` behind `--snap-v2`, solves valence-3+ apices via least-squares plane intersection, densifies shared edges, validates polygons with Shapely, emits `snap_v2_features.json`, passes all 7 correctness tests, and produces bit-for-bit identical output on the gable smoke test
**Depends on**: Phase 1
**Requirements**: TOPO-05, TOPO-06, TOPO-07, TOPO-08, TOPO-09, TOPO-10, VALID-01, VALID-02, INTG-01, INTG-02, INTG-03, TEST-01, TEST-02, TEST-03, TEST-06
**Success Criteria** (what must be TRUE):
  1. `pytest roof_pipeline/panel_snap_v2_test.py` exits green -- all 7 tests pass including gable-unchanged, hip-apex-weld, ridge-weld, transitive-cluster, mixed-winding, self-intersecting-repair, and L-shaped-winding
  2. `run_real.py --snap-v2 <hip_roof_sample>` completes without error and produces a PDF with no visible triangular white gaps at the hip apex
  3. `output/snap_v2_features.json` is written alongside the PDF and contains a valid feature graph with `features` (id, valence, position_xyz, panel_ids) and `edges` (panel_a, panel_b, feature_ids) conforming to the documented schema
  4. Running `run_real.py --snap-v2 <gable_sample>` produces output files that are byte-for-byte identical to the same run with `--snap-v1` (the current pairwise snap path)
  5. Passing malformed polygon JSON to `polygons_from_clicks` (missing vertex array, wrong type) raises a Pydantic validation error with an actionable message -- the pipeline does not silently produce corrupt geometry
**Plans:** 4 plans
Plans:
- [x] 02-01-PLAN.md -- Apex solver module with valence-2/3/4+ dispatch + TDD tests (TEST-02, TEST-03)
- [x] 02-02-PLAN.md -- Pydantic input validation schema + boundaries.py integration (VALID-01, VALID-02)
- [x] 02-03-PLAN.md -- Edge densification + Shapely validation with repair + TDD tests (TEST-06)
- [x] 02-04-PLAN.md -- Pipeline orchestration, --snap-v2 CLI flag, JSON sidecar, tiered golden-file smoke test (TEST-01)

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Feature Graph + Clustering | 3/3 | Complete | 2026-04-18 |
| 2. Apex Solver + Integration | 4/4 | Complete | 2026-04-19 |

---

*Roadmap created: 2026-04-18*
*Last updated: 2026-04-19 after 02-04 execution complete -- Milestone 1 done*
