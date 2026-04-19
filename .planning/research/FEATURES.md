# Feature Landscape

**Domain:** Topology-aware polygon snap engine + web-based geometric labeling dashboard for roof panel reconstruction
**Researched:** 2026-04-18

## Table Stakes

Features users expect. Missing = product feels incomplete or broken.

### Snap Engine (Python -- `panel_snap_v2`)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Union-find vertex clustering** | Standard algorithm for transitive vertex merging. The existing `snap_shared_corners` already uses union-find but with single-pass tolerance. Without it, two vertices each 0.9m from a third but 1.5m apart never merge transitively. | Med | Already partially implemented in `snapping.py`. The v2 upgrade is multi-pass expanding tolerance (0.3t, 0.6t, t) for hip apex grouping. |
| **Multi-pass expanding tolerance** | Hip apices on real roofs have 3+ panels where no single pair of vertices is within the tight tolerance but the transitive chain closes at a wider pass. QGIS, ArcGIS Pro, and every serious GIS uses cluster tolerance as a fundamental topology primitive. Without this, hip roofs produce slivers. | Med | Three passes at 0.3t, 0.6t, t. Each pass must use the union-find from the prior pass as input (cumulative merging). |
| **Valence-3+ apex solving via least-squares plane intersection** | Where 3+ panels meet (hip apex, ridge junction), the snap target must lie on every panel's fitted plane simultaneously. Centroid averaging (current approach) produces a point not on any plane -- creating triangular gaps. Prior art: Kelly & Wonka straight skeleton, Ren et al. SGA21 planarity metric. | High | Closed-form 3x3 solve for exactly 3 planes; `numpy.linalg.lstsq` for 4+. Residual weighting by plane fit quality (RMS from `planes.py`) improves robustness. |
| **Consistent winding normalization** | Earcut and downstream mesh export require counter-clockwise winding. The existing pipeline does not enforce winding -- PROJECT.md identifies L-shaped (non-convex) panels as the highest-risk item because shoelace sign is unreliable for concave polygons. | Med | Signed-area test works for convex; for non-convex, compute signed area and flip if negative, then validate with Shapely `orient()`. Must happen before feature graph construction. |
| **Shapely `is_valid` + `make_valid` repair pass** | Self-intersecting polygons from noisy clicks or aggressive snapping cause silent mesh failures 3 stages later. Shapely 2.x provides `make_valid()` (preferred over `buffer(0)` which discards geometry in bow-tie cases). ArcGIS and QGIS both run validation passes as part of topology editing. | Low | Single pass after snapping: check `is_valid`, if false apply `make_valid(method="structure")`, log warning. Shapely already in project requirements.txt. |
| **Edge-walking densify for shared edges** | When two panels share an edge but one has an extra mid-edge vertex (user clicked ridge at 3 points, other panel at 2), the edge is not topologically shared. Must insert collinear vertices. Existing `densify_shared_edges` does this in 3D; v2 needs the 2D (XY) version integrated into the new pipeline. | Med | Existing implementation in `snapping.py` is solid. Port logic into v2 pipeline order: cluster corners -> densify edges -> solve apices -> validate. |
| **Feature graph (adjacency) output** | The snap engine must emit a machine-readable record of which vertices are shared and which edges are coincident. Without this, the dashboard cannot render snap preview, the diff viewer cannot compare runs, and edge classification in `shop_drawings.py` must redundantly recompute adjacency at O(P*E*N). | Med | JSON sidecar: `snap_v2_features.json` with nodes (vertex id, xyz, valence, panel membership) and edges (shared edge id, panel pair, length). |
| **`--snap-v2` CLI flag routing** | Must coexist with old snapping path. ArcGIS/QGIS both support multiple topology engines side-by-side with flag-based switching. Deletion of old code before validation is a rewrite risk. | Low | Boolean flag in `run_real.py`. Routes to `panel_snap_v2` module. Old `snapping.py` stays untouched. |

### Web Labeling Dashboard (Next.js -- `/labeling/[sampleId]`)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Click-to-add polygon vertices on DSM overlay** | Core interaction. The existing matplotlib labeler does exactly this. Every polygon annotation tool (CVAT, LabelMe, VIA) treats vertex-click as the atomic operation. Without it the dashboard is non-functional. | Med | Konva `Stage` + `Layer` with `Image` (DSM hillshade), `Line` (polygon edges, `closed: true`), `Circle` (vertex handles). React-Konva provides declarative bindings. |
| **Shared-node magnet snap (12px radius)** | Table stakes for this specific domain. The whole point of the dashboard is eliminating the 3-8px ridge pair drift that causes snap engine failures. QGIS uses 10-12px snap radius as default. ArcGIS Pro uses cluster tolerance + visual snap indicators. Without magnet snap, the dashboard is no better than matplotlib. | High | When cursor is within 12px of an existing vertex from any panel, snap to that vertex and display visual indicator ("-> P3.C1"). Shift-click overrides snap. This is the single most important UX feature. |
| **Undo/redo** | Expected in any editor. Konva official docs provide the pattern: keep history array of state snapshots, index pointer, Ctrl+Z / Ctrl+Shift+Z keybinds. Every annotation tool (CVAT, LabelMe) has this. | Med | Zustand store with `past[]` and `future[]` arrays. Snapshot on every vertex add/move/delete and panel finalize. Konva docs explicitly recommend keeping undo/redo independent of Konva internals -- store state snapshots, not Konva serialization. |
| **Panel list sidebar with color-coded IDs** | Users need to see which panels exist, select them, and know which color maps to which panel. CVAT, LabelMe, and the existing matplotlib labeler all show panel IDs. Without this, editing a specific panel on a complex roof is impossible. | Low | Sidebar component listing panels with colored chips, click-to-select, vertex count, area estimate. Zustand `selectedPanelId` state. |
| **Keyboard shortcuts** | The existing matplotlib labeler has Enter, Backspace, F, S, Q. Web annotation tools universally support keyboard shortcuts. Without them, labeling a 10-panel roof is tediously slow. | Low | Enter = finalize panel, Backspace = undo last vertex, Delete = delete selected panel, Ctrl+Z = undo, Ctrl+Shift+Z = redo, Escape = cancel current polygon. |
| **Zoom and pan** | The existing labeler has scroll-zoom and right-drag-pan. Every canvas-based editor supports this. DSM tiles are large (200x200+ pixels at 0.1m resolution); without zoom, corner placement is imprecise. | Low | Konva `Stage` `draggable: true` for pan, `onWheel` handler for zoom with scale clamping. Standard pattern in Konva docs. |
| **Save to mask.json contract** | The dashboard must write the same JSON schema that `polygons_from_clicks()` reads. This is the API boundary between frontend and pipeline. Without schema-validated output, the pipeline breaks silently. | Med | Pydantic (server) / Zod (client) schema for `{ panels: [{ id, corners_pix: [[x,y]] }], res_m, shape }`. POST to FastAPI endpoint. |
| **Load existing labels for re-editing** | Users will iterate: label -> run pipeline -> see errors -> re-label. Without load, they start from scratch every time. | Med | GET endpoint returns existing mask.json. Dashboard hydrates Zustand store from loaded data. Panels render as editable polygons. |

### Dashboard Index (`/labeling`)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Sample table with status indicators** | Users manage multiple roof samples. Need to see which are labeled, which ran successfully, which have errors. Standard CRUD table pattern. | Low | Supabase query on samples table. Columns: sample ID, address, status (unlabeled/labeled/running/done/error), last modified. |
| **Filter/sort by status** | With 10+ samples, finding the one that needs attention requires filtering. Basic list management. | Low | Filter chips for each status value. Sort by date or status. |

## Differentiators

Features that set the product apart. Not expected in a generic tool, but valuable for this specific domain.

### Snap Engine

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Valence-colored snap preview** | Visualizes the feature graph on the DSM: dots colored by how many panels meet at each vertex (valence-2 = blue/edge, valence-3 = orange/hip, valence-4+ = red/complex junction). No existing roof tool does this. Immediate visual verification that topology is correct before running the full pipeline. | Med | Render feature graph from `snap_v2_features.json` as Konva overlay. Color map: `{2: "#3b82f6", 3: "#f59e0b", 4: "#ef4444"}`. Lines between shared vertices show shared edges. |
| **Snap residual feedback per vertex** | Show the distance each vertex moved during snapping and the plane-fit residual. Lets users identify which corners are suspicious (large snap distance = imprecise click, high residual = noisy DSM patch). No existing labeling tool provides geometric quality metrics inline. | Med | Tooltip or sidebar panel showing snap delta (mm), plane RMS (mm), and valence for selected vertex. Data comes from feature graph JSON. |
| **Non-convex panel support with explicit test** | Most polygon snap tools assume convex panels. L-shaped panels (dormers, T-shaped roof sections) are common on real residential roofs. Explicit winding normalization + test for L-shapes prevents the invisible feature graph corruption identified as highest-risk in PROJECT.md. | High | Dedicated test case with a known-concave polygon. Shoelace area check + Shapely `orient()` + validation that earcut produces correct triangulation. |
| **Edge adjacency map as snap sidecar** | Pre-computing which edges are shared between which panels during snapping eliminates the O(P*E*N) redundant recomputation in `shop_drawings.py` `_classify_panel_edges()`. Downstream consumers get adjacency for free. | Med | Extend `snap_v2_features.json` to include `shared_edges: [{ edge_id, panels: [pid_a, pid_b], vertices: [vid_start, vid_end] }]`. |

### Web Labeling Dashboard

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Snap preview mode toggle** | After labeling, user clicks "Preview Snap" and sees the feature graph overlaid on their polygons without leaving the labeler. Immediate feedback loop instead of: save -> run CLI -> open PDF -> check for slivers -> re-label. Cuts iteration time from minutes to seconds. | High | FastAPI endpoint `/api/snap-preview` accepts polygon JSON, runs snap_v2 in-process, returns feature graph JSON. Dashboard renders overlay. Needs WebSocket or SSE for progress on large roofs. |
| **Diff viewer for comparing runs** | Side-by-side or overlay comparison of two pipeline runs on the same sample. Shows which edges changed, which vertices moved, which panels got added/removed. Prior art: QGIS Polygon Compare plugin, Datafold data diffing. Invaluable for validating snap engine changes. | High | Compare two `snap_v2_features.json` files. Compute vertex-level deltas (moved > threshold = highlighted). Render as overlay with added=green, removed=red, moved=yellow. |
| **Run monitor via Supabase Realtime** | Watch pipeline execution in real-time: stage progress, timing, errors. Uses Supabase Realtime's `postgres_changes` channel. Standard pattern for Next.js + Supabase (documented in Supabase docs). Better than polling or manual refresh. | Med | Pipeline writes progress to a `pipeline_runs` table. Dashboard subscribes via `supabase.channel('run-progress').on('postgres_changes', ...)`. Show progress bar with stage names and elapsed time. |
| **PDF preview embed** | View generated cut sheets and shop drawings directly in the dashboard without downloading files. Reduces context-switching. | Low | `<iframe>` or PDF.js embed of the generated PDF from Supabase Storage. Tab alongside the canvas view. |
| **Feature graph expand/collapse in sample table** | On the `/labeling` index page, clicking a sample row expands to show the feature graph summary: number of panels, shared vertices, valence distribution. Quick triage without opening the full editor. | Low | Accordion row in the table. Pulls summary stats from `snap_v2_features.json` metadata. |
| **Vertex drag with live re-snap preview** | Dragging a vertex shows ghost lines to other panels' vertices that would snap to it. Real-time preview of topology changes. Similar to ArcGIS Pro's topological editing where moving a shared vertex updates all connected features. | High | Requires client-side snap calculation (KD-tree in JS or WASM). On drag, find vertices within snap radius, draw dashed lines. On drop, commit snap and update affected panels. |

## Anti-Features

Features to explicitly NOT build. Each one has been considered and rejected for documented reasons.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Multi-user concurrent editing** | PROJECT.md explicitly excludes this. Complexity of operational transform or CRDT for geometric data is enormous. Single user per sample is fine for v1 (one estimator labels one roof at a time). | Single-user locking via Supabase row-level `locked_by` field. Show "in use by X" if someone else has it open. |
| **Edge semantic classification in snap engine** | PROJECT.md defers this to next milestone. Classifying edges as ridge/hip/valley/eave/rake requires the feature graph to be correct first. Building both simultaneously creates circular dependencies. | Build the feature graph now. Add edge type as an attribute in the next milestone when the graph is validated. |
| **Penetration labeling (chimneys, skylights, vents)** | Out of scope per PROJECT.md. Penetrations require hole support in earcut triangulation, polygon-with-holes in the data model, and cut-sheet updates. Each is a significant scope expansion. | Ignore penetrations in v1. Polygons are simple (no holes). |
| **AI-assisted auto-labeling (SAM/segmentation)** | Tempting because CVAT and modern annotation tools offer SAM integration. But this project's input is a DSM (elevation raster), not an RGB image. SAM does not work on elevation data. Building a custom segmentation model is a separate research effort. | Keep manual click-based labeling. The magnet snap feature addresses the main accuracy pain point without ML. |
| **Arbitrary polygon editing (freehand, bezier curves)** | Roof panels are planar polygons with straight edges. Bezier curves and freehand tools add complexity without value. Clicks at corners with straight edges between them is the correct primitive. | Click-to-add-vertex with optional shift-click to override snap. That is the complete input vocabulary. |
| **3D mesh viewer in dashboard** | Rendering the OBJ/glTF in-browser requires Three.js or model-viewer, adds significant bundle weight, and duplicates what the PDF cut sheets already show. The 2D feature graph overlay provides more actionable information. | Show feature graph overlay on 2D DSM. Link to downloadable OBJ/glTF for users who want 3D in external tools. |
| **Removing the matplotlib labeler** | PROJECT.md explicitly keeps it as CLI fallback. Useful for dev/debug, works offline, no server dependency. Ripping it out creates risk with no benefit. | Keep `label_panels.py` untouched. Production usage moves to dashboard; CLI stays for developers. |
| **shop_drawings.py refactoring** | CONCERNS.md flags the 2089-line monolith. Mapper flagged it too. But it works, has no bugs related to this milestone, and refactoring it is pure tech debt with zero user value for the snap engine or dashboard. | Do not plan refactor work this milestone. If a change is forced by snap_v2 output format changes, make the minimal surgical edit. |
| **Custom snap tolerance UI control** | Exposing tolerance sliders to end users invites confusion and invalid configurations. The 3-pass expanding tolerance (0.3t, 0.6t, t) with a sensible default t=1.0m handles 95% of residential roofs. | Hardcode default tolerance. Expose `--snap-tol` only on CLI for power users/debugging. Dashboard uses the default. |

## Feature Dependencies

```
Winding normalization --> Union-find vertex clustering --> Multi-pass expanding tolerance
                                                              |
                                                              v
                                           Valence-3+ apex solving (needs clusters)
                                                              |
                                                              v
                                           Edge-walking densify (after corners solved)
                                                              |
                                                              v
                                           Shapely validation pass (after all geometry changes)
                                                              |
                                                              v
                                           Feature graph JSON output (after validation)
                                                              |
                                                              v
                                           --snap-v2 flag routing (wraps entire chain)

Click-to-add vertices --> Panel list sidebar --> Save to mask.json
                    |                                  |
                    v                                  v
        Shared-node magnet snap               Load existing labels
                    |                                  |
                    v                                  v
              Undo/redo                    Snap preview mode (needs save + snap engine)
                                                       |
                                                       v
                                              Diff viewer (needs 2 saved runs)
                                                       |
                                              Run monitor (needs pipeline_runs table)

Sample table --> Filter/sort --> Feature graph expand (needs feature JSON)
```

## MVP Recommendation

Prioritize in this order:

### Phase 1: Snap Engine Core (Python)
1. **Winding normalization** -- highest-risk item per PROJECT.md, must be first
2. **Union-find vertex clustering with multi-pass tolerance** -- table stakes for hip roof correctness
3. **Valence-3+ apex solving** -- the core correctness feature that eliminates slivers
4. **Edge-walking densify** -- existing code needs minimal adaptation
5. **Shapely validation pass** -- safety net, low effort
6. **Feature graph JSON output** -- enables all dashboard features
7. **`--snap-v2` flag** -- integration point, low effort

### Phase 2: Dashboard Labeler Core (Next.js)
1. **Click-to-add vertices on DSM** -- basic functionality
2. **Shared-node magnet snap** -- the key UX differentiator
3. **Panel list sidebar** -- navigation
4. **Undo/redo** -- expected editor behavior
5. **Keyboard shortcuts** -- productivity
6. **Zoom/pan** -- usability
7. **Save to mask.json** -- completes the label-to-pipeline loop
8. **Load existing labels** -- enables iteration

### Phase 3: Dashboard Monitoring + Differentiators
1. **Sample table with status** -- management view
2. **Filter/sort** -- list management
3. **Snap preview mode** -- fast feedback loop
4. **Run monitor** -- visibility into pipeline execution
5. **PDF preview** -- reduces context switching

### Defer to later:
- **Diff viewer**: Needs at least 2 pipeline runs per sample to be useful. Build after users have real data flowing.
- **Vertex drag with live re-snap**: High complexity, nice-to-have. Only valuable after the core snap + label loop works.
- **Feature graph expand in sample table**: Low value until there are many samples to triage.

## Sources

- [ArcGIS Pro -- About Snapping](https://desktop.arcgis.com/en/arcmap/latest/manage-data/editing-fundamentals/about-snapping.htm) -- HIGH confidence, authoritative reference for topology-aware snapping patterns
- [ArcGIS Pro -- Topology in ArcGIS](https://pro.arcgis.com/en/pro-app/latest/help/data/topologies/topology-in-arcgis.htm) -- HIGH confidence, cluster tolerance and shared vertex editing
- [QGIS Documentation -- Topology](https://docs.qgis.org/3.44/en/docs/gentle_gis_introduction/topology.html) -- HIGH confidence, snap radius defaults (10-12px)
- [QGIS Documentation -- Editing](https://docs.qgis.org/3.44/en/docs/user_manual/working_with_vector/editing_geometry_attributes.html) -- HIGH confidence, visual snap indicators
- [Konva.js -- Objects Snapping](https://konvajs.org/docs/sandbox/Objects_Snapping.html) -- HIGH confidence (Context7 verified), snapping implementation pattern
- [Konva.js -- Undo/Redo](https://konvajs.org/docs/react/Undo-Redo.html) -- HIGH confidence (Context7 verified), history array pattern
- [Shapely -- make_valid](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html) -- HIGH confidence (Context7 verified), `make_valid(method="structure")` preferred over `buffer(0)`
- [Shapely -- Polygon validation](https://shapely.readthedocs.io/en/stable/reference/shapely.is_valid.html) -- HIGH confidence (Context7 verified)
- [Ren et al. SGA21 -- Roof Optimization](https://github.com/llorz/SGA21_roofOptimization) -- MEDIUM confidence, graph-based roof topology encoding, planarity metric
- [Supabase -- Realtime with Next.js](https://supabase.com/docs/guides/realtime/realtime-with-nextjs) -- HIGH confidence, `postgres_changes` subscription pattern
- [CVAT -- Annotation Tools](https://www.cvat.ai/) -- MEDIUM confidence, feature landscape reference for annotation tools
- [LabelMe/VIA annotation tools](https://labelyourdata.com/articles/data-annotation/polygon-annotation) -- MEDIUM confidence, table-stakes feature survey
- [CGAL -- Polygon Mesh Processing](https://doc.cgal.org/latest/Polygon_mesh_processing/index.html) -- MEDIUM confidence, mesh repair and vertex welding patterns
- [InstaLOD -- Vertex Welding](https://instalod.zendesk.com/hc/en-us/articles/360022026374-Vertex-Welding) -- MEDIUM confidence, threshold-controlled welding
