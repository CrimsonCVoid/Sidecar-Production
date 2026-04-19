# Domain Pitfalls

**Domain:** Topology-aware roof polygon snapping + web labeling dashboard
**Researched:** 2026-04-18

---

## Critical Pitfalls

Mistakes that cause rewrites, corrupt geometry silently, or produce incorrect fabrication documents.

---

### Pitfall 1: Non-Convex (L-Shaped) Winding Normalization via Shoelace Sign

**What goes wrong:** The standard approach to enforcing CCW winding is: compute shoelace signed area, if negative flip the vertex order. This is mathematically correct for all simple (non-self-intersecting) polygons, including concave ones. The shoelace formula handles concave polygons correctly -- negative trapezoid contributions cancel the over-counted positive ones. So the *sign* of the shoelace area reliably indicates CW vs CCW for any simple polygon.

The real danger is not that the shoelace sign is wrong on an L-shape. It is that the polygon arriving at the winding check is **not simple** -- it has a self-intersection introduced upstream. Specifically:

1. **Click-order ambiguity on notched panels.** When a user clicks the 6+ corners of an L-shaped panel, nothing enforces that clicks trace the boundary in order. If the user clicks corners in a "zigzag" (e.g., jumping across the notch), the resulting polygon has a bowtie self-intersection. The shoelace formula on a self-intersecting polygon produces a signed area that reflects the *net winding number*, not the geometric area. A bowtie polygon can have net signed area near zero or even the "wrong" sign, so the flip decision is meaningless.

2. **Projection-induced crossing.** The pipeline projects 3D vertices onto a panel's fitted plane (`_project_onto_plane` in boundaries.py), then the snap engine will project to 2D for winding checks. If the 3D-to-2D projection basis vectors (computed in `_plane_basis` in mesh.py) happen to project two non-adjacent edges onto crossing positions (rare but possible on steep near-vertical panels), the 2D polygon becomes self-intersecting even though the 3D polygon was simple.

3. **Post-snap vertex displacement.** After union-find merging, corner vertices move to cluster centroids. On a concave panel, a vertex near the interior notch can be displaced *across* an adjacent edge, creating a self-intersection that did not exist pre-snap.

**Why it happens:** The PROJECT.md calls this the highest-risk item, and it is -- but the risk is not "shoelace gets the wrong sign on concave polygons" (it does not). The risk is that the polygon is **not simple** by the time the winding check runs, and nobody detects that.

**Consequences:** Feature graph encodes inverted face normals for affected panels. Earcut triangulation produces inside-out triangles or degenerate zero-area triangles. Mesh export succeeds silently. The error surfaces 3 phases later as slivers in the PDF or normals flipping in glTF viewers.

**Prevention:**
1. Before winding normalization, validate simplicity. Use `shapely.Polygon(coords).is_valid` -- it checks for ring self-intersections. If invalid, repair with `shapely.make_valid()` (prefer over `buffer(0)` -- see Pitfall 6).
2. Add a dedicated `test_l_shaped_winding` that constructs a 6-vertex L-shape, runs it through projection and snap, and asserts the output polygon is both valid and CCW.
3. In the labeler UI, enforce that click order traces the boundary sequentially (highlight the last edge drawn, warn on crossing).
4. After snap, re-check `is_valid` on every polygon. Log and repair any that became self-intersecting.

**Detection:** Assert `shapely.Polygon(verts_2d).is_valid` after every topology-modifying operation. The test suite must include the L-shape panel explicitly.

**Phase:** Phase 1 (snap engine core). This must be the first thing tested, not the last.

**Confidence:** HIGH -- the shoelace formula's correctness on simple concave polygons is mathematically proven (MIT OCW 18.900, Wolfram MathWorld). The real failure mode (non-simple input) is confirmed by the existing codebase having zero validation.

---

### Pitfall 2: Union-Find Floating-Point Tolerance Transitivity Violation

**What goes wrong:** The snap engine clusters vertices using union-find with a distance tolerance: if `dist(A, B) <= tol`, merge them. The current code (`snap_shared_corners`, line 226) does exactly this. The fundamental problem: **distance-based "equality" is not transitive.** If `dist(A,B) <= tol` and `dist(B,C) <= tol`, it does NOT follow that `dist(A,C) <= tol`. The Euclidean triangle inequality only guarantees `dist(A,C) <= 2*tol`.

The PROJECT.md specifies a multi-pass expanding tolerance (0.3t, 0.6t, t) for transitive hip apex grouping. This is explicitly designed to handle the case where no single pair is within tolerance but the chain should merge. However, this makes the transitivity problem *worse*, not better:

1. **Cluster drift.** With expanding tolerance, a chain A-B-C-D can form where `dist(A,D) >> t`. The centroid of {A,B,C,D} may be far from all original positions. On a hip apex where 3 panels meet, dragging the apex to a centroid that lies on none of the planes produces a vertex that violates every panel's planarity.

2. **Order dependence.** Union-find merging is not commutative when centroids are recomputed. If pass 1 merges {A,B} to centroid M1, then pass 2 checks `dist(M1, C)` -- the result depends on which pairs were merged first. Different vertex ordering produces different final geometry.

3. **Runaway merging.** On a complex roof with closely-spaced panels, expanding tolerance can chain-merge vertices that belong to geometrically distinct features (e.g., two parallel ridge lines 0.8t apart). Once merged, the two ridges collapse into one, destroying the roof topology.

**Why it happens:** The real-world problem is that user clicks at hip apices are imprecise (3-8px drift per CONCERNS.md), and three panels' corners near the same apex may not all be pairwise within a single tolerance. The multi-pass approach tries to fix this but introduces the transitivity chain problem.

**Consequences:** Vertices snap to positions that lie on no panel's plane. Downstream plane projection pushes them back, but the shared-vertex property is lost. Slivers return. Or worse: topology-distinct features merge, producing wrong panel adjacency.

**Prevention:**
1. After union-find clustering, do NOT use the centroid as the merge target. Use the **least-squares plane intersection point** for valence-3+ clusters (the apex solver). The centroid is only acceptable for valence-2 (simple edge endpoint) where both panels' planes intersect at a well-defined point.
2. Impose a **maximum cluster diameter** check: after merging, if `max(dist(v_i, v_j))` for any pair in the cluster exceeds `2*tol`, flag the cluster as suspicious and log a warning. Do not silently accept it.
3. Use a **spatial index** (scipy KDTree) instead of O(N^2) pairwise comparison. KDTree.query_ball_point gives neighbors within tolerance without requiring N^2 distance evaluations and naturally bounds the search radius.
4. The multi-pass expanding tolerance should have a hard ceiling on cluster size: if a cluster already has 4+ members after pass 1, do not expand it further in pass 2.

**Detection:** Unit test: create 4 vertices in a line spaced 0.4t apart. With tolerance t, A-B, B-C, C-D each merge, but dist(A,D) = 1.2t. Assert the cluster centroid is flagged or the merge is rejected.

**Phase:** Phase 1 (snap engine core).

**Confidence:** HIGH -- the transitivity violation is a fundamental property of metric spaces (well-documented in computational geometry literature, Bruce Dawson's floating-point comparison analysis, and Christer Ericson's real-time collision detection blog).

---

### Pitfall 3: Near-Parallel Plane Intersection Numerical Instability (Apex Solver)

**What goes wrong:** The valence-3+ apex solver intersects 3 or more fitted planes to find the apex point. For 3 planes, this is a 3x3 linear system `N * p = d` where N is the matrix of plane normals and d is the vector of plane offsets. For 4+ planes, it is an overdetermined system solved by least squares (`np.linalg.lstsq` or `scipy.linalg.lstsq`).

When two of the meeting planes are nearly parallel (e.g., two sides of a shallow gable with ~5-degree pitch difference), the normal matrix N becomes ill-conditioned. The condition number `cond(N) = sigma_max / sigma_min` explodes. The solved apex point can be meters away from the actual roof geometry, or `lstsq` can return a point at infinity along the near-parallel direction.

On real residential roofs, near-parallel planes arise from:
- Low-slope sections (2:12 to 4:12 pitch) meeting a flat soffit or porch roof
- Two sides of a very shallow gable (normals differ by only a few degrees)
- Noisy DSM data causing fitted plane normals to be closer than the true geometry

**Why it happens:** The PROJECT.md specifies "closed-form 3x3 for 3 planes, lstsq for 4+" following Kelly & Wonka 2011 and Ren et al. SGA21. The Ren et al. SGA21 approach (`llorz/SGA21_roofOptimization`) optimizes vertex positions to enforce planarity, using a planarity metric that inherently penalizes deviations. But their formulation includes regularization terms ("different regularizers or aesthetic constraints" per their README) -- without those regularization terms, the raw plane intersection is numerically unstable.

The Kelly & Wonka 2011 approach uses a sweep-plane algorithm for procedural extrusions, which avoids the explicit plane intersection problem by construction. It is not directly applicable to the data-driven case where plane normals come from noisy DSM fits.

**Consequences:** Apex point placed meters away from the roof. Mesh triangulation succeeds but produces a spike or inverted triangle. PDF rendering shows a panel extending far outside the building footprint. In fabrication, this translates to a wrong cut dimension on a panel.

**Prevention:**
1. **Condition number guard.** Before solving, compute `cond(N)` via SVD. If `cond(N) > 100` (empirical threshold for roof geometry where planes typically differ by 10+ degrees), fall back to the centroid of the input vertices instead of the plane intersection. Log a warning.
2. **Residual check.** After solving, compute the residual distance from the solved point to each plane. If any residual exceeds `2 * max(plane.rms_residual)`, reject the solution and fall back to centroid.
3. **Regularized least squares.** For 4+ planes, use Tikhonov regularization (add `lambda * I` to `N^T N`). Use `scipy.linalg.lstsq` with `cond` parameter set to `1e-6` to zero out near-singular components. The `cond` parameter in scipy.linalg.lstsq controls the cutoff for small singular values -- singular values below `cond * sigma_max` are treated as zero.
4. **Weight by plane fit quality.** Weight each plane equation by `1.0 / plane.rms_residual` so well-fit planes have more influence than noisy ones. This is the key insight from the Ren et al. SGA21 approach: their optimization implicitly weights by planarity quality.

**Detection:** Unit test: create two planes with normals differing by 2 degrees, and a third perpendicular. Assert the solver either returns a point within 0.1m of the expected apex or falls back gracefully. Test with `cond(N) > 1000`.

**Phase:** Phase 1 (apex solver implementation).

**Confidence:** HIGH -- condition number behavior for plane intersection is textbook linear algebra. The specific threshold (100) is MEDIUM confidence and should be validated empirically on real roof data.

---

### Pitfall 4: Earcut Triangulation Failure on Repaired / Complex Polygons

**What goes wrong:** The pipeline uses mapbox-earcut for triangulation (mesh.py). Earcut handles concave polygons but does NOT guarantee correct triangulation for self-intersecting or degenerate polygons. The earcut documentation explicitly states: "doesn't guarantee correctness of triangulation, but attempts to always produce acceptable results for practical data."

After the snap engine modifies vertex positions, densifies edges, and normalizes winding, the resulting polygon may have:
- Near-degenerate edges (two vertices within machine epsilon after snapping)
- Edges that are nearly collinear (3 consecutive vertices on almost-a-line)
- Slight self-intersection from snap displacement (Pitfall 1 crossover)

These cause earcut to produce zero-area triangles, missing triangles (holes in the mesh), or triangles with inverted winding relative to the polygon's intended orientation.

Additionally, earcut always produces CW-wound triangles regardless of input winding (GitHub issue #44, #133). If downstream code (glTF viewer, trimesh normals) expects CCW triangles matching the polygon's CCW winding, normals will be flipped.

**Why it happens:** The current mesh.py (line 48-49) checks for empty output (`tris.size == 0`) but does not check for degenerate triangles, area mismatch, or winding consistency. There is no validation between earcut output and expected polygon area.

**Consequences:** Holes in the 3D mesh at specific panels. Flipped normals causing panels to render as transparent in glTF viewers. Incorrect area computation in cut sheets (cutsheets.py uses trimesh face areas).

**Prevention:**
1. After earcut, compute the total triangle area and compare to the polygon's shoelace area. If they differ by more than 1%, log a warning and attempt re-triangulation with vertices slightly perturbed (jitter by 1e-8).
2. Remove degenerate edges (length < 1e-10) before passing to earcut. Merge near-coincident consecutive vertices.
3. Check triangle winding consistency: all triangle normals (via cross product) should point in the same direction as the panel's fitted plane normal. If any are flipped, reverse that triangle's vertex order.
4. Consider using `shapely.ops.triangulate` (Delaunay) as a fallback if earcut fails, then clip to the polygon boundary. More expensive but more robust for difficult polygons.

**Detection:** Post-triangulation assertion: `abs(sum(tri_areas) - polygon_area) / polygon_area < 0.01`.

**Phase:** Phase 1 (mesh build validation), but the fix applies to the existing mesh.py and should be wired in when panel_snap_v2 outputs are first fed to it.

**Confidence:** HIGH -- earcut's limitations are documented in its own README and issue tracker. The winding issue is confirmed in earcut GitHub issues #44 and #133.

---

### Pitfall 5: Feature Graph Corruption from Snap Order Dependencies

**What goes wrong:** The snap engine will build a feature graph (adjacency structure encoding which panels share edges/vertices). If the feature graph is built *before* all snap passes complete, or if snap passes modify vertices that the feature graph references, the graph becomes stale.

Concrete failure mode: Pass 1 (corner snap at 0.3t) merges vertices A and B. The feature graph records edge(Panel1, Panel2) through vertex A. Pass 2 (corner snap at 0.6t) merges vertex A with vertex C from Panel3. The feature graph still records only the Panel1-Panel2 edge, missing the Panel1-Panel3 and Panel2-Panel3 adjacencies introduced by the transitive merge. The valence of vertex A is now 3, but the feature graph says 2.

**Why it happens:** Building the feature graph incrementally (after each pass) rather than once at the end. Or building it from vertex identity (pointer equality) rather than geometric proximity (which changes after each pass).

**Consequences:** Valence-3+ apex solver is never invoked for apices that need it. Hip apex stays as a centroid merge (Pitfall 2) instead of a plane intersection (correct). The whole point of the topology-aware engine is defeated.

**Prevention:**
1. Build the feature graph ONCE, AFTER all snap passes complete. Never incrementally.
2. Feature graph adjacency should be computed from geometric proximity (KDTree query) on the final snapped vertex positions, not from tracking which vertices were merged during union-find.
3. The feature graph should store vertex *indices* into a deduplicated vertex array, not copies of coordinates. After snapping, rebuild the deduplicated array and update indices.

**Detection:** Assert that the feature graph's vertex valence matches the number of unique panels sharing each vertex position (within epsilon). For every valence-3+ vertex, assert the apex solver was invoked.

**Phase:** Phase 1 (feature graph construction must come after all snap passes).

**Confidence:** HIGH -- this is a sequencing/architecture decision, not a research question. The failure mode is deterministic.

---

## Moderate Pitfalls

---

### Pitfall 6: Shapely `buffer(0)` Silently Discarding Geometry

**What goes wrong:** The PROJECT.md specifies `buffer(0)` for repairing self-intersecting polygons. The `buffer(0)` approach can discard large portions of the polygon when the geometry has a "bowtie" topology (two lobes connected at a self-intersection point). Instead of producing a valid polygon covering both lobes, it may return only one lobe, or return an empty geometry entirely.

This is documented in Shapely issue #277 (empty polygon from buffer(0)) and in a detailed analysis by Martin Davis (JTS/GEOS maintainer) titled "Fixing Buffer for fixing Polygons."

**Why it happens:** The buffer algorithm computes ring orientation using `Orientation.isCCW`, which determines orientation from the uppermost vertex. In bowtie topologies, this heuristic can misinterpret which region is "inside," causing one lobe to be treated as a hole and subtracted.

**Prevention:**
1. Use `shapely.make_valid()` instead of `buffer(0)`. Available since Shapely 1.8 (via GEOS 3.8 MakeValid). It handles bowtie topologies correctly by splitting into a MultiPolygon.
2. If `make_valid()` returns a MultiPolygon or GeometryCollection, take the largest polygon by area (consistent with the existing `max(contours, key=cv2.contourArea)` logic in boundaries.py).
3. After repair, assert `result.is_valid and not result.is_empty and result.area > min_area_threshold`.

**Detection:** Test with a known bowtie polygon. Assert repair produces a valid polygon covering both lobes.

**Phase:** Phase 1 (polygon validation pass).

**Confidence:** HIGH -- Shapely issue #277 and Martin Davis's analysis are authoritative. `make_valid()` is available in the project's Shapely version (requirement is `shapely>=2.0`).

---

### Pitfall 7: Coordinate Convention Coupling Across Pipeline Stages

**What goes wrong:** CONCERNS.md documents that `ts_export.py` uses `x -> -v_in, z -> u_in` and `ts_render_pdf.py` uses `pageX = z * scale + 300, pageY = -x * scale + 400`. These conventions are documented in comments but not enforced programmatically. The snap engine introduces a new coordinate space (feature graph coordinates, 2D projection for winding checks) that must be consistent with both the mesh builder and the downstream export/render pipeline.

If panel_snap_v2 uses a different projection basis than mesh.py's `_plane_basis()`, the winding direction can flip between snap and triangulation even though both individually produce correct results in their own coordinate frame.

**Why it happens:** The current codebase has no shared coordinate convention module. Each module independently computes its own basis vectors. The snap engine will add a third basis computation.

**Prevention:**
1. Extract `_plane_basis()` from mesh.py into a shared `geometry.py` module. The snap engine and mesh builder must use the identical basis.
2. Add a round-trip test: project vertices to 2D using the shared basis, normalize winding, project back to 3D, and assert the 3D polygon has the expected normal direction.
3. Per CONCERNS.md, any change to ts_export or ts_render requires round-trip coordinate tests. Add these tests BEFORE modifying any coordinate code.

**Detection:** Round-trip test failure.

**Phase:** Phase 1 (before any coordinate manipulation code is written).

**Confidence:** HIGH -- CONCERNS.md explicitly flags this fragility.

---

### Pitfall 8: Undo/Redo State Explosion in Labeling Dashboard

**What goes wrong:** The PROJECT.md specifies undo/redo in the labeling dashboard using Zustand. The natural approach is to store the entire polygon state on every change (snapshot-based undo). For a roof with 10 panels, each with 4-8 vertices (3 coordinates each), the state is small (~1KB). But:

1. **Drag operations** generate a state change on every mouse move (60+ changes per second during a drag). Without throttling, the undo stack grows to thousands of entries in seconds.
2. **Snap preview mode** continuously recalculates the feature graph on mouse hover. If these intermediate states are recorded, undo becomes unusable (hundreds of "undo" presses to reverse one logical action).
3. **Zundo** (the standard Zustand undo middleware, <700B) stores full state snapshots by default. For this use case, that is acceptable in size but problematic in granularity.

**Why it happens:** Failing to distinguish between "logical actions" (place vertex, move vertex, delete vertex) and "intermediate states" (mouse move during drag, hover preview).

**Prevention:**
1. Use zundo with `handleSet` to disable tracking during drag operations. Only record the state at drag-start and drag-end.
2. Implement a `beginTransaction` / `commitTransaction` pattern: wrap multi-step operations (drag, snap preview) in a transaction that records only the before/after state.
3. Cap the undo stack at 50-100 entries. Beyond that, old entries are dropped.
4. Snap preview calculations should be ephemeral (derived state in Zustand, computed via a selector, never stored in the undo-tracked portion of the store).

**Detection:** Manual test: drag a vertex for 3 seconds, then press undo. It should undo the entire drag, not one pixel of movement.

**Phase:** Phase 3 (dashboard implementation).

**Confidence:** MEDIUM -- zundo's `handleSet` API is confirmed in its documentation and README. The transaction pattern is a common practice but not built into zundo; it requires custom implementation.

---

### Pitfall 9: Konva Canvas Performance Degradation on Snap Preview

**What goes wrong:** The snap preview mode renders the feature graph with valence-colored dots and edge overlays on top of the DSM raster image. For a complex roof:
- 10-20 panels with 4-8 vertices each = 40-160 vertices
- Feature graph edges connecting adjacent panels = 30-100 edges
- Each vertex rendered as a colored circle with label
- Each edge rendered as a line with optional midpoint marker
- The DSM raster as a background image

This is within Konva's comfortable range (hundreds of shapes). The performance problem arises from:

1. **Hit detection on all shapes.** Konva maintains a "hit graph" (a hidden canvas) for every shape with event listeners. With 200+ interactive shapes, every mouse move triggers hit detection across all of them. This is the primary bottleneck, not rendering.
2. **Full-layer redraw on state change.** Moving one vertex triggers a Zustand state update, which React re-renders, which redraws the entire Konva layer. With React Konva, every shape is a React component; re-rendering 200 components on every mouse move causes React reconciliation overhead on top of Canvas redraw.
3. **Retina displays doubling pixel count.** On a 2x retina display, the canvas has 4x the pixels. Konva's default `pixelRatio` matches the device, which is correct for quality but expensive for performance.

**Why it happens:** React Konva wraps every shape in a React component, so React's reconciliation runs even though Canvas doesn't need a full DOM diff. Combined with Konva's hit graph maintenance, this creates a per-frame cost that is disproportionate to the visual change.

**Prevention:**
1. **Separate layers:** Static elements (DSM image, panel fills) on one layer with `listening={false}`. Interactive elements (vertex handles, edge overlays) on a second layer. Only the interactive layer redraws on mouse events.
2. **Disable listening on non-interactive shapes:** Panel fill polygons, edge lines, and labels should have `listening={false}`. Only vertex handle circles need hit detection.
3. **Batch updates:** Use `React.unstable_batchedUpdates` or Zustand's `transient` updates for mouse-move handlers to avoid multiple React re-renders per frame.
4. **Cache static shapes:** Use Konva's `cache()` on the background layer and panel fills. Cached shapes render from an internal bitmap instead of re-executing draw commands.
5. **Consider `pixelRatio={1}`** on the interactive layer during drag operations, restoring full resolution on mouse-up.

**Detection:** Profile with Chrome DevTools Performance tab. If frame time exceeds 16ms (60fps) during drag/hover, optimization is needed. Watch for "Recalculate Style" and "Layout" entries indicating React overhead.

**Phase:** Phase 3 (dashboard implementation). Design the layer architecture before writing any Konva code.

**Confidence:** MEDIUM -- Konva's official performance docs confirm these strategies. Specific thresholds (200 shapes, 16ms) are reasonable estimates but depend on hardware.

---

### Pitfall 10: Supabase Realtime Silent Disconnection During Pipeline Monitoring

**What goes wrong:** The dashboard uses Supabase Realtime for run monitoring (pipeline progress, status updates). Supabase Realtime WebSocket connections silently disconnect when:

1. **Browser tab is backgrounded.** JavaScript timers are throttled, preventing heartbeat messages. The server assumes the client disconnected after missing heartbeats. This is documented in Supabase's own troubleshooting docs.
2. **Network instability.** Brief network interruptions cause the WebSocket to close without triggering an error event. The client shows stale data without any indication that it is disconnected.
3. **Channel/connection limits.** Free tier: 200 concurrent connections, 100 messages/second. Pro tier: 500 connections, 500 messages/second. Exceeding these limits disconnects existing connections with `too_many_connections` error.

**Why it happens:** WebSocket connections are stateful and fragile. The Supabase Realtime client library handles reconnection, but there is a window between disconnection and reconnection where events are lost. For pipeline monitoring, a lost "run completed" event means the dashboard shows "running" indefinitely.

**Prevention:**
1. **Use the `worker: true` option** in the Supabase Realtime client config. This offloads heartbeat logic to a Web Worker, which is not throttled when the tab is backgrounded.
2. **Implement a `heartbeatCallback`** that actively monitors connection status and triggers reconnection if a heartbeat fails.
3. **Poll as fallback.** After establishing Realtime subscription, also poll the pipeline_runs table every 30 seconds. If the poll shows a different status than the Realtime state, update. This makes Realtime an optimization (instant updates) rather than a correctness requirement.
4. **Idempotent status updates.** Store pipeline status as a database column (polled via normal Supabase query), not as a transient Realtime broadcast. Realtime notifies of the change; the poll confirms it.

**Detection:** Automated test: subscribe to a channel, background the tab for 60 seconds, resume, and verify the client reconnected and received any events that occurred during the background period.

**Phase:** Phase 4 (run monitoring integration).

**Confidence:** HIGH -- Supabase's own documentation describes these failure modes and mitigations (troubleshooting docs on silent disconnections and heartbeat messages).

---

## Minor Pitfalls

---

### Pitfall 11: Edge Densification Vertex Duplication at Snap Boundaries

**What goes wrong:** The existing `densify_shared_edges` (snapping.py) inserts vertices along edges where another panel's vertex projects onto the edge interior. After snap_v2 modifies vertex positions, the densification pass may insert a vertex at a position that coincides (within tolerance) with an existing vertex, creating a zero-length edge. Zero-length edges cause earcut to produce degenerate triangles and confuse edge classification in shop_drawings.py.

**Prevention:** After densification, deduplicate consecutive vertices that are within `1e-10` of each other. The existing code (snapping.py line 151-154) checks distance to endpoints but not to previously-inserted vertices on the same edge.

**Phase:** Phase 1 (snap engine).

**Confidence:** HIGH -- the failure mode is visible in the existing code (line 162-164 dedupes by `t` parameter, not by absolute position).

---

### Pitfall 12: JSON Schema Drift Between Dashboard and Pipeline

**What goes wrong:** The dashboard writes mask.json via HTTP to a contract consumed by `polygons_from_clicks`. The PROJECT.md specifies Pydantic/dataclass schema validation at this boundary. If the schema is defined in the Python pipeline and a TypeScript type in the dashboard, they can drift. A field rename in one is not caught until runtime.

**Prevention:**
1. Define the schema once in a JSON Schema file. Generate the Pydantic model and the Zod schema from it. Tools like `datamodel-code-generator` (Python) and `json-schema-to-zod` (TypeScript) can automate this.
2. Alternatively, define the Zod schema as the source of truth, export to JSON Schema, and validate in Python. Either direction works; the point is single-source.
3. Add a CI test that validates a sample mask.json against both the Pydantic model and the Zod schema.

**Phase:** Phase 2 (API boundary definition).

**Confidence:** MEDIUM -- the tools exist but the workflow requires manual setup. No automated single-source schema generator covers Pydantic + Zod natively.

---

### Pitfall 13: Snap Tolerance Parameter Sensitivity

**What goes wrong:** The existing code uses `tol=1.0m` for corner snap and `tol=0.15m` for edge snap. The multi-pass expanding tolerance (0.3t, 0.6t, t) means the effective search radius varies from 0.3m to 1.0m for corners. On a small residential roof where panels are 2-3m wide, a 1.0m corner tolerance can merge vertices that belong to different features (e.g., a dormer corner and a main roof corner 0.8m apart).

On larger commercial roofs, the same 1.0m tolerance may be too small to capture user click drift at distant corners.

**Prevention:**
1. Make tolerance a function of panel size: `tol = min(0.15 * median_edge_length, 1.0)`. This scales the tolerance to the geometry.
2. Expose tolerance as a `--snap-tol` CLI parameter and as a slider in the dashboard, with a default computed from the geometry.
3. Log the number of clusters formed at each tolerance level. If pass 3 (full tolerance) merges significantly more vertices than passes 1+2, the tolerance may be too aggressive.

**Phase:** Phase 1 (snap engine parameters).

**Confidence:** MEDIUM -- the tolerance values in the existing code (1.0m, 0.15m) were chosen empirically for specific test roofs. Whether they generalize is unknown without testing on diverse samples.

---

### Pitfall 14: Downstream Regression in shop_drawings.py Edge Classification

**What goes wrong:** The snap engine changes vertex positions, which changes edge geometry, which changes the heuristic edge classification in shop_drawings.py (lines 1895-1951). The classification uses geometric tests (edge angle, neighbor count) to label edges as ridge/hip/valley/eave/rake. After snap_v2, edge angles may change slightly, causing classification to flip (e.g., a hip edge reclassified as a ridge edge). This changes the trim type assigned to the edge, which changes the fabrication PDF output.

Per PROJECT.md constraints: "mesh.py, shop_drawings.py, cutsheets.py, ts_export.py, ts_render_pdf.py must keep working bit-for-bit on the gable-roof smoke test."

**Prevention:**
1. The `--snap-v2` flag must route ONLY the snap step to the new engine. All downstream modules receive polygons in the same format as before.
2. Add a regression test: run the gable-roof smoke test with `--snap-v2` and diff the output PDF against the baseline. No pixel changes allowed on the gable case (where snap_v2 should produce identical results to snap_v1, since gable roofs have no 3+ vertex convergences).
3. For hip roof cases, manually verify edge classifications are correct before establishing new baselines.

**Phase:** Phase 2 (integration testing, after snap engine is complete).

**Confidence:** HIGH -- the constraint is explicit in PROJECT.md. The failure mode is deterministic and testable.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Snap engine core | Pitfall 1 (winding on non-simple polygons) | Validate simplicity before winding check; L-shape test |
| Phase 1: Snap engine core | Pitfall 2 (union-find transitivity) | Max cluster diameter check; apex solver for valence 3+ |
| Phase 1: Snap engine core | Pitfall 3 (near-parallel apex solver) | Condition number guard; weighted lstsq; centroid fallback |
| Phase 1: Snap engine core | Pitfall 5 (feature graph timing) | Build feature graph ONCE after all snap passes |
| Phase 1: Snap engine core | Pitfall 11 (densification duplicates) | Deduplicate consecutive vertices post-densification |
| Phase 1: Polygon validation | Pitfall 6 (buffer(0) discards geometry) | Use make_valid() instead |
| Phase 1: Mesh integration | Pitfall 4 (earcut failures) | Area check post-triangulation; degenerate edge removal |
| Phase 1: Mesh integration | Pitfall 7 (coordinate coupling) | Shared _plane_basis; round-trip test |
| Phase 2: API boundary | Pitfall 12 (schema drift) | Single-source JSON Schema |
| Phase 2: Integration testing | Pitfall 14 (edge classification regression) | Gable smoke test diff |
| Phase 3: Dashboard UX | Pitfall 8 (undo state explosion) | Transaction pattern; throttle drags |
| Phase 3: Dashboard rendering | Pitfall 9 (Konva performance) | Layer separation; listening={false} on static shapes |
| Phase 4: Run monitoring | Pitfall 10 (Realtime disconnection) | worker:true; poll fallback |
| All phases | Pitfall 13 (tolerance sensitivity) | Adaptive tolerance; log cluster stats |

---

## Sources

### Computational Geometry and Numerical Stability
- [Shoelace Formula - Wikipedia](https://en.wikipedia.org/wiki/Shoelace_formula) -- confirms correctness on simple concave polygons
- [MIT OCW 18.900 - Shoelace Formula and Winding Number](https://ocw.mit.edu/courses/18-900-geometry-and-topology-in-the-plane-spring-2023/mit18_900s23_lec3.pdf) -- mathematical foundations
- [Bruce Dawson - Comparing Floating Point Numbers (2012)](https://randomascii.wordpress.com/2012/02/25/comparing-floating-point-numbers-2012-edition/) -- transitivity violation
- [Christer Ericson - Floating-point tolerances revisited](https://realtimecollisiondetection.net/blog/?p=89) -- tolerance design in geometric algorithms
- [scipy.linalg.lstsq documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.lstsq.html) -- cond parameter for singular value cutoff

### Prior Art (Roof Reconstruction)
- [Ren et al. SGA21 - Intuitive and Efficient Roof Modeling](https://arxiv.org/abs/2109.07683) -- planarity metric optimization, regularization approach
- [llorz/SGA21_roofOptimization GitHub](https://github.com/llorz/SGA21_roofOptimization) -- reference implementation
- [Kelly & Wonka 2011 - Interactive Architectural Modeling](http://peterwonka.net/Publications/pdfs/2011.TOG.Kelly.ProceduralExtrusions.TechreportVersion.final.pdf) -- sweep-plane approach
- [CGAL Polygonal Surface Reconstruction (PolyFit)](https://doc.cgal.org/latest/Polygonal_surface_reconstruction/index.html) -- scalability limits, solver requirements
- [ignfab/building-roof-pipeline](https://github.com/ignfab/building-roof-pipeline) -- CGAL + PolyFit for DSM-based roof reconstruction

### Polygon Repair
- [Shapely make_valid documentation](https://shapely.readthedocs.io/en/latest/reference/shapely.make_valid.html) -- preferred over buffer(0)
- [Shapely issue #277 - buffer(0) returns empty polygon](https://github.com/Toblerity/Shapely/issues/277) -- buffer(0) failure case
- [Martin Davis - Fixing Buffer for fixing Polygons](http://lin-ear-th-inking.blogspot.com/2020/12/fixing-buffer-for-fixing-polygons.html) -- authoritative analysis of buffer(0) failures

### Earcut Triangulation
- [mapbox/earcut README](https://github.com/mapbox/earcut) -- documented limitations with self-intersecting polygons
- [earcut issue #133 - winding order, PointInTriangle, signed area](https://github.com/mapbox/earcut/issues/133) -- CW polygon failures
- [earcut issue #44 - triangle winding order](https://github.com/mapbox/earcut/issues/44) -- output always CW regardless of input

### Konva / Canvas Performance
- [Konva Performance Tips](https://konvajs.org/docs/performance/All_Performance_Tips.html) -- official optimization guide
- [Konva Layer Management](https://konvajs.org/docs/performance/Layer_Management.html) -- layer separation strategy
- [Konva Shape Caching](https://konvajs.org/docs/performance/Shape_Caching.html) -- cache vs direct render tradeoff

### Supabase Realtime
- [Supabase Realtime Limits](https://supabase.com/docs/guides/realtime/limits) -- connection/channel/message limits by tier
- [Supabase - Handling Silent Disconnections](https://supabase.com/docs/guides/troubleshooting/realtime-handling-silent-disconnections-in-backgrounded-applications-592794) -- worker:true and heartbeatCallback mitigations
- [Supabase - Understanding Heartbeats](https://supabase.com/docs/guides/troubleshooting/realtime-heartbeat-messages) -- heartbeat monitoring

### Zustand / Undo-Redo
- [zundo - Zustand undo/redo middleware](https://github.com/charkour/zundo) -- handleSet API for selective tracking

---

*Pitfalls audit: 2026-04-18*
