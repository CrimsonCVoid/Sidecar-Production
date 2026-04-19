# Roadmap: My Metal Roofer

## Milestones

- v1.0 Topology-Aware Snap Engine (Phases 1-2) -- shipped 2026-04-19
- v2.0 FastAPI Sidecar + Labeling Dashboard (Phases 3-6) -- in progress

## Phases

<details>
<summary>v1.0 Topology-Aware Snap Engine (Phases 1-2) -- SHIPPED 2026-04-19</summary>

- [x] **Phase 1: Feature Graph + Clustering** - Pure Python subpackage skeleton with winding normalization, union-find clustering, and feature graph construction; `--snap-v2-dryrun` flag prints graph and exits without touching downstream modules (completed 2026-04-18)
- [x] **Phase 2: Apex Solver + Integration** - Valence-aware apex solving, edge densification, Shapely validation, Pydantic input schema, `--snap-v2` integration in `run_real.py`, `snap_v2_features.json` sidecar output, all 41 tests green, gable smoke test structurally equivalent (completed 2026-04-19)

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
**Plans**: 3 plans
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
**Plans**: 4 plans
Plans:
- [x] 02-01-PLAN.md -- Apex solver module with valence-2/3/4+ dispatch + TDD tests (TEST-02, TEST-03)
- [x] 02-02-PLAN.md -- Pydantic input validation schema + boundaries.py integration (VALID-01, VALID-02)
- [x] 02-03-PLAN.md -- Edge densification + Shapely validation with repair + TDD tests (TEST-06)
- [x] 02-04-PLAN.md -- Pipeline orchestration, --snap-v2 CLI flag, JSON sidecar, tiered golden-file smoke test (TEST-01)

</details>

### v2.0 FastAPI Sidecar + Labeling Dashboard (In Progress)

**Milestone Goal:** Fix real-data bugs blocking production use, expose snap engine via FastAPI, and build the Next.js labeling dashboard with shared-node magnet, undo/redo, snap preview, plus a dashboard index with sample table, diff viewer, and run monitor.

- [x] **Phase 3: Bug Fixes** - Fix densify area-loss bug and labeler duplicate-corner dedup so the engine is production-safe before API exposure (completed 2026-04-19)
- [ ] **Phase 4: FastAPI Sidecar** - Snap-preview endpoint, pipeline-run trigger, label persistence, and structured server-side logging on existing DigitalOcean droplet
- [ ] **Phase 5: Labeling Dashboard** - Next.js Konva canvas with shared-node magnet, undo/redo, snap preview overlay, auto-close, mask.json output, browser-side error capture, and Playwright E2E tests for labeler flows
- [ ] **Phase 6: Dashboard Index + Monitoring** - Sample table, filter chips, diff viewer, Supabase Realtime run monitor, and Playwright E2E tests for dashboard flows

---

## Phase Details

### Phase 3: Bug Fixes
**Goal**: The snap engine handles complex hip-and-valley roofs without area-loss rejection, and legacy mask.json files with duplicate corners are silently cleaned during ingestion
**Depends on**: Phase 2 (Milestone 1 complete)
**Requirements**: FIX-01, FIX-02, LABEL-01
**Success Criteria** (what must be TRUE):
  1. Running `run_real.py --snap-v2` on the 12-panel hip-and-valley roof (fb7e705c) completes without error -- panel 8 passes through densify and Shapely validation without area-change rejection
  2. A golden-file regression test for the 12-panel hip-and-valley roof exists and passes in the test suite, confirming the densify fix does not regress
  3. A mask.json file containing duplicate last corners (as produced by the matplotlib labeler's double-click behavior) is loaded via `polygons_from_clicks` and produces the same polygon as the deduplicated version -- no error, no extra zero-length edges
**Plans**: 2 plans
Plans:
- [x] 03-01-PLAN.md -- Silent duplicate-corner dedup in Pydantic schema + tests (LABEL-01)
- [x] 03-02-PLAN.md -- Densify area-loss investigation, fix, diagnostic logging, fb7e705c regression test (FIX-01, FIX-02)

**Deferred from Phase 3:** `make_synthetic_multi_hip()` in synthetic.py -- a 4-panel synthetic hip doesn't reproduce the multi-neighbor topology (3+ shared edges) that caused panel 8's failure. Revisit broader synthetic coverage in a later milestone.

### Phase 4: FastAPI Sidecar
**Goal**: The snap engine and pipeline are accessible over HTTP from the Next.js frontend, with structured server-side logging for production observability
**Depends on**: Phase 3
**Requirements**: API-01, API-02, API-03, OBSERVABILITY-01a
**Success Criteria** (what must be TRUE):
  1. POST `/snap-preview` with a valid mask.json body returns a JSON response containing the feature graph (nodes with valence and position) and snapped polygon coordinates within 500ms on a representative 12-panel roof
  2. POST `/run-pipeline` triggers a full pipeline run and writes status updates (queued, running, complete, failed) to a Supabase `pipeline_runs` table that the dashboard can query
  3. POST `/labels/{sampleId}` persists panel label data to Supabase and GET `/labels/{sampleId}` retrieves it -- round-trip preserves all vertex coordinates without loss
  4. Every request logs a structured JSON line containing trace_id, sample_id, endpoint, latency_ms, and error_type (if any)
**Plans**: 4 plans
Plans:
- [x] 04-01-PLAN.md -- API skeleton: config, deps, middleware, schemas, app factory, stub routers (OBSERVABILITY-01a)
- [x] 04-02-PLAN.md -- run_real.py refactor: extract run_pipeline() callable (API-02 prerequisite)
- [ ] 04-03-PLAN.md -- Snap preview endpoint + test infrastructure (API-01, OBSERVABILITY-01a)
- [ ] 04-04-PLAN.md -- Pipeline run + labels endpoints + tests (API-02, API-03)

### Phase 5: Labeling Dashboard
**Goal**: Users can draw, edit, and preview panel polygons on a hillshade canvas with shared-node snapping that eliminates ridge drift at the source, with browser-side error capture and Playwright E2E tests for labeler flows
**Depends on**: Phase 4
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06, OBSERVABILITY-01b, TESTING-01a
**Success Criteria** (what must be TRUE):
  1. Navigating to `/labeling/[sampleId]` loads the sample's hillshade DSM image on a Konva canvas and displays any previously-saved panel polygons from Supabase
  2. When drawing a polygon vertex within 12px of an existing vertex from another panel, the cursor snaps to the existing vertex (visual indicator shown) and the placed vertex shares the exact coordinates -- holding Shift overrides the magnet and places at cursor position
  3. Pressing Cmd+Z undoes the last action (vertex placement, polygon completion, polygon deletion) and Cmd+Shift+Z redoes it -- undo history survives polygon boundary crossings but clears on page navigation
  4. Clicking "Snap Preview" calls the API and overlays valence-colored dots on the canvas at each feature point (green for valence-2, yellow for valence-3, red for valence-4+) with a panel-count tooltip
  5. When the cursor is within 10px of the first vertex while drawing, the polygon auto-closes on click -- the saved mask.json is compatible with `polygons_from_clicks` and contains no duplicate corners
  6. Browser-side errors are captured and forwarded to a backend logging endpoint or Sentry
  7. Playwright E2E tests pass for label-save-reload (draw polygons, save, reload, verify persist), undo-redo (draw, undo, redo, verify state), and magnet-snap-override (snap near existing vertex, Shift override)
**Plans**: TBD
**UI hint**: yes

### Phase 6: Dashboard Index + Monitoring
**Goal**: Users can browse all roof samples, filter by processing status, compare output PDFs side by side, watch pipeline runs complete in real time, with Playwright E2E tests for dashboard flows
**Depends on**: Phase 4, Phase 5
**Requirements**: DIDX-01, DIDX-02, DIDX-03, DIDX-04, TESTING-01b
**Success Criteria** (what must be TRUE):
  1. The dashboard index page displays a table of roof samples with address, panel click count, and a snap-status badge (needs review / v2-verified / failed validation) sourced from Supabase
  2. Clicking filter chips (needs review, v2-verified, failed validation) filters the sample table to show only matching samples -- filters are composable and the active filter state is visible
  3. Selecting two pipeline runs opens a side-by-side diff viewer showing the before/after PDFs for visual comparison of snap quality changes
  4. After triggering a pipeline run, the run monitor shows real-time status updates (queued, running, complete, failed) via Supabase Realtime without requiring page refresh
  5. Playwright E2E tests pass for sample list navigation, run monitor status updates, and diff viewer rendering
**Plans**: TBD
**UI hint**: yes

---

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Feature Graph + Clustering | v1.0 | 3/3 | Complete | 2026-04-18 |
| 2. Apex Solver + Integration | v1.0 | 4/4 | Complete | 2026-04-19 |
| 3. Bug Fixes | v2.0 | 2/2 | Complete | 2026-04-19 |
| 4. FastAPI Sidecar | v2.0 | 2/4 | In Progress | - |
| 5. Labeling Dashboard | v2.0 | 0/? | Not started | - |
| 6. Dashboard Index + Monitoring | v2.0 | 0/? | Not started | - |

---

*Roadmap created: 2026-04-18 (Milestone 1)*
*Last updated: 2026-04-19 -- Phase 4 planned (4 plans in 2 waves)*
