# Project Research Summary

**Project:** Topology-Aware Snap Engine + Web Labeling Dashboard (My Metal Roofer)
**Domain:** Computational geometry pipeline + interactive polygon annotation for roof panel reconstruction
**Researched:** 2026-04-18
**Confidence:** HIGH

## Executive Summary

This project adds two capabilities to an existing Python/Next.js roof-to-fabrication pipeline: a topology-aware polygon snap engine (`panel_snap_v2`) that eliminates hip-apex slivers on complex roofs, and a canvas-based web labeling dashboard that replaces the current matplotlib CLI labeler with shared-node magnet snapping and real-time pipeline feedback. Both components extend the existing stack with zero new Python core dependencies — the snap engine is built entirely on scipy, numpy, and shapely already present in `requirements.txt`. The frontend adds Konva + react-konva for canvas rendering, Zustand + zundo for undo/redo state, and routes pipeline monitoring through the existing Supabase Realtime connection. The FastAPI sidecar, a thin adapter serving both the snap preview and pipeline run endpoints, is the only new service.

The recommended approach sequences snap engine first, then dashboard. The engine must work and pass its 7 correctness tests via CLI before any web UI exists. The core algorithmic chain is non-negotiable in its ordering: winding normalization must precede union-find clustering (which assumes consistent vertex sequences), clustering must complete before the feature graph is built (the graph derives from cluster membership), apex solving must precede edge densification (which inserts vertices relative to final apex positions), and Shapely validation must run last. The feature graph JSON sidecar produced by the engine is the data contract that enables every downstream dashboard feature — snap preview overlay, valence-colored dots, diff viewer, and edge adjacency classification in `shop_drawings.py`.

The two highest-risk items are not algorithmic but sequential: (1) non-simple polygon input reaching the winding check before Shapely validation catches it, causing silent earcut failures 3 stages later; and (2) the feature graph being built before all union-find passes complete, leaving apex clusters with incorrect valence and bypassing the plane-intersection solver. Both are prevented by strict pipeline ordering and `shapely.is_valid` guards after every topology-modifying operation. Near-parallel plane instability in the apex solver (shallow gable roofs with nearly identical normals) is mitigated by a condition-number guard and centroid fallback before calling `numpy.linalg.lstsq`. These three mitigations, combined with the `--snap-v2` flag that leaves all downstream modules untouched, make the v2 snap engine safe to ship alongside the working v1 path.

## Key Findings

### Recommended Stack

The snap engine requires no new dependencies. `scipy.cluster.hierarchy.DisjointSet` (already in scipy >=1.11) handles union-find with path-halving and merge-by-size. `scipy.spatial.KDTree` provides O(N log N) spatial indexing for the 3-pass tolerance queries. `numpy.linalg.solve` handles exact 3-plane intersection; `numpy.linalg.lstsq` handles the overdetermined 4+-plane case. `shapely.validation.make_valid` (preferred over `buffer(0)`, which discards geometry in bowtie topologies) handles post-snap polygon repair. The FastAPI sidecar uses FastAPI >=0.115, Pydantic v2 >=2.10, and uvicorn >=0.30 — none are in the current `requirements.txt` but all are lightweight and standard.

For the frontend, Konva 10.x + react-konva 19.x is the clear choice over Fabric.js (flat object model, manual memory management, SVG-based rendering) and raw Canvas (no hit detection, no scene graph). Konva's Stage > Layer > Group > Shape hierarchy maps directly to the roof domain model. Zustand 5.x with the zundo 2.x temporal middleware provides undo/redo in under 1KB of library code, with `partialize` to exclude ephemeral UI state (hover, zoom, snap preview) from the history stack. Supabase Realtime's `postgres_changes` channel, already in the project, handles pipeline monitoring without a second WebSocket transport.

**Core technologies:**
- `scipy.cluster.hierarchy.DisjointSet`: union-find clustering — zero new dependency, path-halving + merge-by-size built in
- `numpy.linalg.solve` / `lstsq`: apex solver — direct 3x3 for valence-3, overdetermined LS for valence-4+
- `shapely.make_valid`: polygon repair — preserves area unlike `buffer(0)`, handles bowtie topologies
- `scipy.spatial.KDTree`: spatial indexing for 3-pass tolerance expansion — O(N log N) vs O(N^2) pairwise
- Konva + react-konva: canvas rendering — scene graph, official React bindings, dirty-region repainting
- Zustand + zundo: labeling state + undo/redo — minimal boilerplate, selective state partitioning
- FastAPI + Pydantic v2: API sidecar — async, auto-OpenAPI, native Pydantic validation
- Supabase Realtime (existing): pipeline monitoring — Postgres Changes on `pipeline_runs`, no extra WebSocket server

### Expected Features

**Must have (table stakes) — Snap Engine:**
- Union-find vertex clustering with 3-pass expanding tolerance (0.3t, 0.6t, t)
- Valence-3+ apex solving via least-squares plane intersection (eliminates centroid-averaging slivers)
- Consistent CCW winding normalization (handles non-convex L-shaped panels)
- Edge-walking shared-edge densification (existing code, minimal adaptation)
- Shapely `is_valid` + `make_valid` validation pass after all geometry modifications
- Feature graph JSON output (`snap_v2_features.json` with nodes, edges, valence, warnings)
- `--snap-v2` flag routing in `run_real.py` (v1 path untouched)

**Must have (table stakes) — Labeling Dashboard:**
- Click-to-add polygon vertices on DSM overlay (Konva canvas)
- Shared-node magnet snap at 12px radius with visual indicator
- Undo/redo (Zustand + zundo, command-pattern granularity)
- Panel list sidebar with color-coded IDs
- Keyboard shortcuts (Enter, Backspace, Delete, Ctrl+Z, Ctrl+Shift+Z, Escape)
- Zoom and pan on the canvas
- Save to `mask.json` (Zod-validated schema matching Pydantic contract)
- Load existing labels for re-editing

**Should have (differentiators):**
- Valence-colored snap preview overlay (dots: blue=valence-2, orange=valence-3, red=valence-4+)
- Snap residual feedback per vertex (snap delta, plane RMS, valence in tooltip/sidebar)
- Run monitor via Supabase Realtime (stage progress, elapsed time, error display)
- Snap preview mode toggle (calls FastAPI, renders feature graph without leaving the labeler)
- Sample table with filter/sort by status on `/labeling` index

**Defer to later:**
- Diff viewer for comparing two pipeline runs — needs real data flowing before it is useful
- Vertex drag with live re-snap preview — high complexity, only valuable after core loop works
- Feature graph expand in sample table — low value until many samples exist
- PDF preview embed — reduces context switching but is not blocking

**Explicit anti-features (do not build):**
- Multi-user concurrent editing, AI/SAM auto-labeling, 3D mesh viewer in dashboard, shop_drawings.py refactoring, bezier/freehand drawing, removal of matplotlib fallback labeler

### Architecture Approach

The system has a clean three-tier separation: the `panel_snap_v2` Python subpackage contains all geometry and algorithm logic (no FastAPI imports); the FastAPI sidecar is a thin adapter that calls `panel_snap_v2` functions directly (no subprocess shelling, no business logic in routes); and the Next.js dashboard consumes FastAPI via HTTP and Supabase via the existing client. Supabase acts as the pub-sub bridge for pipeline monitoring, eliminating the need for the FastAPI sidecar to manage WebSocket sessions. The `--snap-v2` flag in `run_real.py` is a two-line change that routes to `panel_snap_v2` while leaving every downstream module (`mesh.py`, `shop_drawings.py`, `cutsheets.py`, `ts_export.py`, `ts_render_pdf.py`) completely unchanged. The Konva labeling canvas is architecturally isolated from the dashboard components — they share no state except through the Supabase data layer.

**Major components:**
1. `panel_snap_v2/` (Python subpackage) — winding normalization, union-find clustering, feature graph construction, apex solving, edge densification, Shapely validation, JSON export. Public API: `snap_topology_aware(polygons, planes, tol) -> SnapResult`.
2. `api/` (FastAPI sidecar) — `/snap-preview` (sync, <500ms), `/run-pipeline` (background task with Supabase status writes), `/diff`. Imports pipeline functions directly.
3. `schemas/` (Pydantic models) — `mask_contract.py` (dashboard writes this), `snap_features.py` (pipeline writes this). Shared between API and pipeline; no Pydantic in `panel_snap_v2/`.
4. Konva labeling canvas (`canvas/`) — `LabelingCanvas`, `PanelPolygon`, `SharedNodeMagnet`, `SnapPreviewOverlay`. Uses Zustand store as single source of truth.
5. Zustand store (`store/`) — panels, vertices, tool mode tracked by zundo; UI ephemeral state (hover, zoom, snap preview) excluded via `partialize`.
6. Dashboard pages (`labeling/`) — sample table, filter chips, run monitor, diff viewer. Standard Next.js server/client components consuming Supabase.
7. Supabase — `pipeline_runs`, `samples`, `snap_features` tables; `dsm_tiles/`, `masks/`, `outputs/` storage buckets; Realtime publication on `pipeline_runs`.

### Critical Pitfalls

1. **Non-simple polygon reaching winding check** — a self-intersecting polygon (from user zigzag clicks or post-snap vertex displacement) produces a meaningless shoelace sign. Run `shapely.Polygon(coords).is_valid` before winding normalization; repair with `make_valid()` not `buffer(0)`. Add an explicit `test_l_shaped_winding` test with a 6-vertex concave polygon.

2. **Feature graph built before all union-find passes complete** — incremental graph construction mid-pass leaves apex clusters with wrong valence, bypassing the plane-intersection solver entirely. Build the feature graph exactly once, after all 3 tolerance passes finish. Graph adjacency must derive from final snapped vertex positions, not union-find bookkeeping.

3. **Near-parallel planes in apex solver** — two planes with normals differing by a few degrees produce an ill-conditioned 3x3 system; `lstsq` returns a point meters away from the roof. Guard with `np.linalg.cond(N) > 100` before solving; fall back to cluster centroid and log a warning. After solving, verify each residual is within `2 * max(plane.rms_residual)`.

4. **Earcut triangulation failure on post-snap polygons** — earcut always produces CW triangles regardless of input winding (confirmed in earcut issue #44), and does not detect near-degenerate edges. After triangulation assert `|sum(tri_areas) - polygon_area| / polygon_area < 0.01`. Remove zero-length edges before passing to earcut.

5. **Union-find cluster drift via transitivity chaining** — expanding tolerance can chain A-B-C-D where `dist(A,D) >> t`. After clustering, check max intra-cluster diameter; if it exceeds `2*tol`, flag as suspicious. Use apex solver (not centroid) for valence-3+ so the snap target lies on the actual planes regardless of cluster drift.

## Implications for Roadmap

Based on the feature dependency graph and architectural ordering established across all research files, a 4-phase structure is strongly indicated. The snap engine is a prerequisite for every dashboard feature that displays topology feedback, so it must ship and be validated before the dashboard moves beyond basic labeling.

### Phase 1: Snap Engine Core (Python)

**Rationale:** The engine is the project's core value and has zero dependency on any new infrastructure. It can be built and tested entirely via CLI against existing roof samples. Every dashboard feature that matters (snap preview, valence overlay, run monitoring) depends on `snap_v2_features.json` being correct. Building it first means the dashboard always has real data to render.

**Delivers:** A working `panel_snap_v2` module that passes 7 correctness tests, produces `snap_v2_features.json`, and is gated by `--snap-v2` in `run_real.py` with no regressions on the gable smoke test.

**Addresses (from FEATURES.md):** Winding normalization, union-find multi-pass clustering, valence-3+ apex solving, edge densification, Shapely validation pass, feature graph JSON output, `--snap-v2` flag routing.

**Avoids (from PITFALLS.md):** Pitfall 1 (non-simple polygon input), Pitfall 2 (union-find transitivity), Pitfall 3 (near-parallel apex instability), Pitfall 4 (earcut post-snap), Pitfall 5 (feature graph timing), Pitfall 6 (buffer(0) geometry loss), Pitfall 7 (coordinate convention coupling), Pitfall 11 (densification vertex duplication).

**Uses (from STACK.md):** `scipy.cluster.hierarchy.DisjointSet`, `scipy.spatial.KDTree`, `numpy.linalg.solve` / `lstsq`, `shapely.make_valid`, pytest + pytest-cov.

**Research flag:** SKIP — all algorithms are well-documented, all library APIs verified via Context7. Standard patterns apply.

### Phase 2: API Boundary + Integration (FastAPI + Schemas)

**Rationale:** Pydantic schemas must be defined before any dashboard code writes or reads JSON — they are the contract boundary. FastAPI wires the schema-validated snap engine to the dashboard. The gable smoke test regression must pass before this phase closes.

**Delivers:** `schemas/mask_contract.py` and `schemas/snap_features.py` (single source of truth for JSON contracts); FastAPI sidecar with `/snap-preview` (sync, <500ms) and `/run-pipeline` (background task); Supabase `pipeline_runs` table with status writes; passing regression diff on gable smoke test.

**Addresses (from FEATURES.md):** Save to `mask.json` contract, snap preview mode (backend half), run monitor (backend half).

**Avoids (from PITFALLS.md):** Pitfall 12 (JSON schema drift — schemas defined once), Pitfall 14 (shop_drawings regression — gable diff test).

**Uses (from STACK.md):** FastAPI >=0.115, Pydantic v2 >=2.10, uvicorn >=0.30.

**Research flag:** SKIP — FastAPI + Pydantic patterns are well-established and verified. Schema generation tooling (json-schema-to-zod) may need a quick lookup during planning.

### Phase 3: Labeling Canvas Core (Next.js)

**Rationale:** The canvas is the primary user interaction surface and the component that eliminates the 3-8px click-drift problem that motivates the whole project. Shared-node magnet snap is the single most important UX feature; it must be built and validated before the monitoring/diff layer is added. This phase closes when a user can label a hip roof, save `mask.json`, and re-open it for editing.

**Delivers:** `/labeling/[sampleId]` page with Konva canvas, DSM image overlay, polygon drawing with vertex handles, shared-node magnet snap at 12px radius, undo/redo (Zustand + zundo with transaction boundaries), panel sidebar, keyboard shortcuts, zoom/pan, save and load `mask.json`.

**Addresses (from FEATURES.md):** All Phase 2 Dashboard Labeler Core features from FEATURES.md MVP recommendation.

**Avoids (from PITFALLS.md):** Pitfall 8 (undo state explosion — `handleSet` + drag-start/end boundaries), Pitfall 9 (Konva performance — layer separation with `listening={false}` on static shapes, designed upfront before any Konva code is written).

**Uses (from STACK.md):** Konva 10.x, react-konva 19.x, Zustand 5.x, zundo 2.x, Zod >=3.22 (existing), @supabase/supabase-js 2.x (existing).

**Research flag:** RESEARCH RECOMMENDED — the shared-node magnet snap implementation (client-side proximity detection during drag, visual indicator rendering, Shift-click override) and the zundo transaction pattern for drag boundaries involve enough Konva-specific API surface that a targeted research phase during planning would reduce implementation risk.

### Phase 4: Dashboard Monitoring + Differentiators (Next.js)

**Rationale:** Run monitoring, snap preview overlay, and the sample table index are secondary chrome that make the core loop faster to iterate on. They have hard dependencies on both Phase 1 (feature graph JSON exists) and Phase 3 (canvas exists to display the overlay). This phase delivers the complete iteration loop: label → preview snap → run pipeline → watch progress → see result.

**Delivers:** `/labeling` index with sample table, status filter chips; snap preview mode toggle (calls FastAPI `/snap-preview`, renders valence-colored overlay on Konva canvas); run monitor via Supabase Realtime (`pipeline_runs` subscription with `worker: true` and poll fallback); PDF preview embed.

**Addresses (from FEATURES.md):** Phase 3 Dashboard Monitoring + Differentiators from FEATURES.md MVP recommendation.

**Avoids (from PITFALLS.md):** Pitfall 10 (Supabase Realtime silent disconnection — `worker: true`, `heartbeatCallback`, 30-second poll fallback as correctness guarantee).

**Uses (from STACK.md):** @supabase/supabase-js Realtime Postgres Changes (existing).

**Research flag:** SKIP for run monitor and sample table. SKIP for snap preview overlay (feature graph JSON schema is defined in Phase 2; rendering it is standard Konva). Pitfall 10 mitigations are fully documented in Supabase's own troubleshooting docs.

### Phase Ordering Rationale

- **Snap engine before dashboard:** The engine has no infrastructure dependency and can be validated with known roof samples immediately. Every non-trivial dashboard feature depends on `snap_v2_features.json` being correct. Building the engine first means the dashboard always exercises real topology data, not mocked JSON.
- **Schemas before canvas:** The `mask.json` and `snap_v2_features.json` contracts must be locked before the canvas writes or reads them. Drifted schemas (Pitfall 12) are far more expensive to fix after both sides are implemented.
- **Canvas before monitoring:** The labeling canvas is the primary user interaction surface. Monitoring and snap preview are feedback layers on top of it. The canvas must exist and work standalone before those layers are added.
- **Deferred features (diff viewer, live re-snap on drag):** Both require real data (two pipeline runs per sample for diff viewer) or significant client-side geometry computation (KD-tree in JS/WASM for live re-snap). Deferring them avoids over-engineering before the core loop is validated with real users.

### Research Flags

Phases needing `/gsd-research-phase` during planning:
- **Phase 3 (labeling canvas):** The shared-node magnet snap interaction pattern (proximity detection during mousemove, visual indicator timing, Shift-click override coordination with Zustand), and zundo's `handleSet` API for drag-boundary transactions, have enough API-specific surface area that targeted research would meaningfully reduce implementation risk. The SnapPreviewOverlay rendering pipeline (debounced FastAPI call -> Zod parsing -> Konva overlay update without full re-render) is also worth verifying against current react-konva patterns.

Phases with standard patterns (skip research-phase):
- **Phase 1 (snap engine):** All library APIs verified via Context7 against current stable versions. Algorithm design follows published prior art (Ren et al. SGA21, Kelly & Wonka 2011).
- **Phase 2 (API + schemas):** FastAPI + Pydantic v2 patterns are industry-standard and fully documented.
- **Phase 4 (monitoring + differentiators):** Supabase Realtime subscription patterns and mitigation strategies are documented in Supabase's own troubleshooting guides.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library APIs verified via Context7 against current stable versions. Zero-new-dependency claim for Python snap engine is verified against existing `requirements.txt`. Frontend library choices are well-justified with documented alternatives considered and rejected. |
| Features | HIGH | Feature landscape grounded in authoritative GIS references (ArcGIS Pro topology, QGIS documentation) and annotation tool prior art (CVAT, LabelMe). Anti-features list is explicit and well-reasoned. Feature dependency graph is internally consistent. |
| Architecture | HIGH | Architecture grounded in existing codebase examination (not hypothetical), published prior art (Ren et al., Kelly & Wonka), and verified library documentation. The `--snap-v2` flag integration point and FastAPI direct-import pattern are low-risk, minimal-change designs. |
| Pitfalls | HIGH | 5 of 14 pitfalls are confirmed by authoritative external sources (earcut GitHub issues, Shapely issue #277, Supabase troubleshooting docs, mathematical proofs). Remaining pitfalls are confirmed by direct codebase inspection (CONCERNS.md cross-references, existing code line citations). |

**Overall confidence:** HIGH

### Gaps to Address

- **Snap tolerance empirical validation:** The 3-pass tolerance values (0.3t, 0.6t, t with default t=1.0m) and the condition-number guard threshold (cond > 100 for near-parallel planes) were chosen from prior art and empirical reasoning, not tested against the project's own diverse sample set. During Phase 1, run the engine against all available real roof samples and measure cluster statistics at each pass to validate or adjust these thresholds before they are hardcoded.

- **JSON Schema single-source tooling:** PITFALLS.md flags that no tool natively generates both Pydantic models and Zod schemas from a single source. The recommended approach (`datamodel-code-generator` for Python, `json-schema-to-zod` for TypeScript) requires manual integration setup. This workflow needs a quick spike during Phase 2 planning to confirm the toolchain is workable before committing the schema boundary design.

- **Snap preview latency budget:** The <500ms target for `/snap-preview` depends on DSM files being cached in-memory (LRU via `functools.lru_cache`). The actual latency split between `polygons_from_clicks` + `fit_all_panels` preprocessing vs. the snap engine stages itself is estimated but not measured. A timing benchmark on a representative roof during Phase 1 will confirm whether the LRU cache assumption is sufficient or whether plane-fit caching at the API layer is also needed.

## Sources

### Primary (HIGH confidence)
- SciPy DisjointSet docs (Context7 verified, v1.17.0) — union-find API: merge, connected, subsets, path-halving
- NumPy linalg.lstsq / linalg.solve docs (Context7 verified, v2.4) — return signature, rcond parameter
- Shapely 2.1.2 docs (Context7 verified) — make_valid, is_valid, snap, unary_union
- Pydantic v2 docs (Context7 verified, v2.13.2) — BaseModel, field_validator, model_validator
- react-konva 19.x docs (Context7 verified) — Stage, Layer, event handling, undo/redo pattern
- Zustand 5.x docs (Context7 verified) — temporal middleware, partialize, limit options
- Supabase Realtime docs (official) — postgres_changes subscription, filter syntax, worker:true mitigation
- FastAPI 0.135.x (PyPI verified) — Python 3.10+ requirement after 0.130.0
- ArcGIS Pro Snapping / Topology docs (official) — cluster tolerance, shared vertex editing patterns
- QGIS Topology / Editing docs (official) — snap radius defaults (10-12px), visual snap indicators

### Secondary (MEDIUM confidence)
- Ren et al. SGA21 "Intuitive and Efficient Roof Modeling" (arXiv 2109.07683) — planarity metric, residual weighting for plane intersection
- Kelly & Wonka 2011 "Interactive Architectural Modeling" — plane intersection formulation for roof apices
- Konva vs Fabric.js comparison (dev.to) — scene graph vs flat model, memory management
- zundo GitHub (charkour/zundo) — handleSet API for selective tracking, transaction pattern
- Earcut issue #44 / #133 (GitHub) — CW output regardless of input winding, limitations with self-intersecting polygons
- Shapely issue #277 / Martin Davis analysis — buffer(0) failure modes in bowtie topologies
- Supabase troubleshooting docs — silent disconnection causes (tab backgrounded, heartbeat), mitigations

### Tertiary (LOW confidence / needs empirical validation)
- Snap tolerance threshold (t=1.0m, 3-pass at 0.3/0.6/1.0) — empirically chosen for existing test roofs, generalizability unvalidated
- Condition number guard threshold (cond > 100) — reasonable estimate for roof geometry, needs validation on real shallow-gable samples

---
*Research completed: 2026-04-18*
*Ready for roadmap: yes*
