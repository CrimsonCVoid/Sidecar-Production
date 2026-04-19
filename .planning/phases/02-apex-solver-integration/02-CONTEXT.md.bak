# Phase 2: Apex Solver + Integration - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete the `panel_snap_v2` engine: valence-aware apex solving (valence-2 centroid, valence-3 closed-form, valence-4+ least-squares), edge-walking densification for shared edges, Shapely polygon validation with repair, Pydantic input schema at the `polygons_from_clicks` boundary, `--snap-v2` flag wired into `run_real.py`, `snap_v2_features.json` sidecar output, all 7 correctness tests green, and gable smoke test identity verified via a tiered golden-file comparison.

</domain>

<decisions>
## Implementation Decisions

### Solver fallback behavior
- **D-01:** When near-parallel planes trigger the condition-number guard (`cond(N) > 100`), fall back to XY centroid + per-plane Z reconstruction (same as valence-2). Log a warning with panel IDs and condition number. Pipeline continues — the result is slightly less precise but not broken.
- **D-02:** Valence-2 clusters use XY centroid of clustered points, with Z reconstructed independently from each panel's own plane. This matches current v1 pairwise snap behavior and preserves backward compatibility. Each panel gets its own Z at the shared XY centroid.
- **D-03:** Solver logs a one-line summary at INFO level after completion: e.g., `"snap_v2: solved 3 apices (1 ridge, 2 hip), 8 corner snaps, 0 fallbacks"`. Consistent with existing pipeline stage logging pattern (`log.info("=== stage N: description ===")`).

### Validation + repair strictness
- **D-04:** Shapely validation runs twice — once after the solver step and once after edge densification. Two passes catch problems early (solver output) before densify potentially masks them.
- **D-05:** Area change tolerance is 1%. If `abs(repaired_area - original_area) / original_area > 0.01` after `make_valid()`, raise with panel ID. Aligns with STATE.md pitfall #4.
- **D-06:** If `make_valid()` returns a MultiPolygon, keep the piece with the largest area and discard the rest. Log a warning with panel ID and discarded area percentage. Do not hard-fail.

### Input schema design
- **D-07:** Use Pydantic for input validation at the `polygons_from_clicks` boundary (VALID-01). Exception to TOPO-11 accepted — VALID-01 explicitly offers Pydantic, and FastAPI in Milestone 2 will need it natively. Add `pydantic>=2.0` to `requirements.txt`.
- **D-08:** Schema lives in `panel_snap_v2/schema.py`. `boundaries.py` imports from it. Single source of truth for both CLI and future HTTP API.

### Byte-identity test strategy
- **D-09:** Four-tier comparison for the gable smoke test (Tier 3 deferred to Milestone 2):
  - **Tier 0 (pre-flight):** Snapped polygon dict (`dict[int, ndarray]`) before mesh/PDF. `np.testing.assert_allclose` at `atol=1e-12`. If this fails, all downstream tiers will fail — diagnostic is clearest here.
  - **Tier 1 (strict byte):** `snap_v2_features.json`. Deterministic dict with sorted keys, no floats in metadata. Full byte diff.
  - **Tier 2 (structural):** OBJ and glTF parsed via trimesh. `np.testing.assert_allclose(vertices, atol=1e-9, rtol=1e-9)` and exact face match. Catches geometry regressions without fragility to file formatting.
  - **Tier 3 (semantic PDF):** DEFERRED to Milestone 2. Requires pdfplumber dependency. Tiers 0-2 cover geometry correctness end-to-end.
- **D-10:** Golden files stored in `roof_pipeline/panel_snap_v2/tests/golden/gable/`, committed to git (files are small, KB not MB).
- **D-11:** `pytest --regenerate-golden` flag writes fresh goldens. Requires manual `git diff` review before commit. Test fails on any tier mismatch with per-tier diff output showing which tier broke and the specific delta.

### Claude's Discretion
- Internal solver decomposition within `solver.py` (helper functions, matrix assembly)
- Edge-walking densify algorithm details in `densify.py` (how to identify shared edges from feature graph, parameter t sorting)
- Pydantic model field naming and nesting structure in `schema.py`
- Exact `--regenerate-golden` pytest fixture implementation
- How `--snap-v2` flag interacts with existing `--snap-tol` argument

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 code (foundation for Phase 2)
- `roof_pipeline/panel_snap_v2/__init__.py` -- Public API stub (`snap_polygons`). Phase 2 fills in solver/densify/validate calls.
- `roof_pipeline/panel_snap_v2/winding.py` -- CCW normalization with proper 2D plane projection. Consumed by solver.
- `roof_pipeline/panel_snap_v2/clustering.py` -- Three-pass union-find clustering. Produces cluster groups consumed by solver.
- `roof_pipeline/panel_snap_v2/graph.py` -- Feature graph construction + `--snap-v2-dryrun` output. Solver reads valence from graph nodes.

### Existing snap engine (being superseded)
- `roof_pipeline/snapping.py` -- Current pairwise edge snap. `snap_shared_edges(polygons, tol)` signature. `_z_on_plane()` helper may be reusable for valence-2 Z reconstruction.

### Pipeline integration points
- `roof_pipeline/run_real.py` -- Orchestrator where `--snap-v2` flag is wired. Currently has `--snap-v2-dryrun` from Phase 1.
- `roof_pipeline/boundaries.py` -- `polygons_from_clicks()` is the input boundary where Pydantic schema validation (D-07/D-08) is added.
- `roof_pipeline/planes.py` -- `Plane` dataclass (normal, centroid, rms_residual, d). Solver needs `normal` and `d` for plane intersection math, `rms_residual` for lstsq weighting.

### Downstream modules (must remain byte-identical on gable test)
- `roof_pipeline/mesh.py` -- Earcut triangulation, OBJ/glTF export
- `roof_pipeline/cutsheets.py` -- Multi-page dimensioned PDF
- `roof_pipeline/shop_drawings.py` -- 4-page fabrication PDF
- `roof_pipeline/ts_export.py` -- JSON export (coordinate convention: x -> -v_in, z -> u_in)
- `roof_pipeline/ts_render_pdf.py` -- PDF re-render from JSON

### Project requirements and concerns
- `.planning/REQUIREMENTS.md` -- Phase 2 requirements: TOPO-05 through TOPO-10, VALID-01, VALID-02, INTG-01 through INTG-03, TEST-01 through TEST-03, TEST-06
- `.planning/codebase/CONCERNS.md` -- Coordinate convention coupling (fragile area), untyped roof dict, input validation gaps
- `.planning/phases/01-feature-graph-clustering/01-CONTEXT.md` -- Phase 1 decisions (subpackage layout, winding algorithm, test structure)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `snapping._z_on_plane(x, y, plane)`: Z reconstruction from XY + Plane. Directly reusable for valence-2 solver (D-02).
- `panel_snap_v2.clustering.cluster_vertices()`: Returns cluster groups. Solver iterates these by valence.
- `panel_snap_v2.graph.build_feature_graph()`: Feature graph with valence classification. Solver reads node valence to dispatch to correct algorithm.
- `panel_snap_v2.winding.normalize_winding()`: Already handles non-convex panels. Runs before solver.

### Established Patterns
- Copy-on-write: `out = {pid: poly.copy() for pid, poly in polygons.items()}` — solver modifies the copy
- Module-level logger: `log = logging.getLogger(__name__)`
- `from __future__ import annotations` in every file
- Skip invalid items with `log.warning()` + `continue`
- Validate early with shape checks at function entry

### Integration Points
- `run_real.py` argparse: add `--snap-v2` flag alongside existing `--snap-v2-dryrun` and `--snap-tol`
- `snap_polygons()` signature takes `planes` (unlike `snap_shared_edges`). Integration must pass `planes` dict.
- `snap_v2_features.json` written by `run_real.py` alongside other output files (PDF, OBJ, glTF)
- Pydantic schema imported by `boundaries.py` from `panel_snap_v2.schema`

</code_context>

<specifics>
## Specific Ideas

- Tiered golden-file comparison is the user's explicit design: Tier 0 (polygon arrays at 1e-12) catches issues earliest; Tier 1 (JSON byte-identity) validates sidecar; Tier 2 (trimesh structural at 1e-9) validates mesh pipeline without formatting fragility. Tier 3 (PDF semantic via pdfplumber) deferred to Milestone 2.
- `--regenerate-golden` flag must require manual `git diff` review — goldens should never silently change
- Pydantic exception to TOPO-11 is explicitly accepted because VALID-01 offers it and Milestone 2 FastAPI needs it
- Two validation passes (after solver AND after densify) is the user's explicit choice — do not optimize down to one pass

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-apex-solver-integration*
*Context gathered: 2026-04-18*
