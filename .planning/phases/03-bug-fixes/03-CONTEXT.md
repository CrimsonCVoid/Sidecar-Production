# Phase 3: Bug Fixes - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix two bugs blocking production use of the snap engine on complex roofs: (1) densify area-loss on 12-panel hip-and-valley roof fb7e705c panel 8, and (2) labeler duplicate-corner ingestion for legacy mask.json files. Add regression tests for both fixes. No new features, no threshold changes, no broader refactoring.

</domain>

<decisions>
## Implementation Decisions

### Duplicate-corner dedup
- **D-01:** Dedup lives in `panel_snap_v2/schema.py` as a Pydantic `field_validator` on `PanelCorners.corners_pix`. Single source of truth per D-08 — protects both CLI (`polygons_from_clicks`) and future HTTP API (Milestone 2 FastAPI).
- **D-02:** Close-polygon dedup only — strip the last corner if it matches the first within a small tolerance. Do NOT strip all consecutive duplicates. This is the specific matplotlib double-click bug, not a general dedup.
- **D-03:** Dedup is silent — no warning, no error. Legacy mask.json files just work. Log at DEBUG level for traceability.

### Densify fix strategy
- **D-04:** Investigate root cause first with diagnostic logging before coding a fix. The planner builds an investigate-then-fix plan structure.
- **D-05:** Diagnostic logging at DEBUG level: per-shared-edge lines with `(panel_a, panel_b, candidate_vertices_considered, vertices_inserted, insertion_positions_xy)`. Enabled with `LOG_LEVEL=DEBUG`, does not pollute normal runs.
- **D-06:** Narrow fix only — fix the panel 8 failure mode. Regression test locks in the bug. No broader densify refactoring (scope creep).
- **D-07:** Fix the algorithm if needed (redesign edge walk for multi-neighbor panels), but keep the same `densify_edges()` API. No changes to `validate.py` thresholds.
- **D-08:** Keep D-06 strict — no fallback path. If densify still produces invalid geometry after the fix, hard-fail. User re-labels the mask.json. No retry with smaller tol, no skip-and-warn.
- **D-09:** No CLI flag for densify tolerance. `--repair-strict` (if it exists) is validate-layer only. Densify has no user-tunable tolerance at the CLI.

### Test data
- **D-10:** Real data regression test (FIX-02): inline Python constants in `test_densify_regression.py`. 12 panels' clicked corners extracted from `~/Downloads/fb7e705c.mask.json` + 12 plane normals from a one-time `fit_all_panels` run. No binary blobs, no external file paths, no DSM commits.
- **D-11:** Synthetic multi-hip test (broader coverage): new `make_synthetic_multi_hip()` function in `synthetic.py`. Programmatic geometry, no real data involved.
- **D-12:** Source DSM/mask data stays at `~/Downloads/` on dev machine only. Needed only to regenerate plane fits if clicked corners change — its output (Python constants) is what gets committed.

### Claude's Discretion
- Exact tolerance value for close-polygon dedup matching in schema.py (pixel-space comparison)
- Diagnostic log line format details beyond the required fields
- Internal decomposition of the densify fix within `densify.py`
- `make_synthetic_multi_hip()` exact geometry (number of hips, valley count, panel sizes)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Densify and validation (bug location)
- `roof_pipeline/panel_snap_v2/densify.py` — Edge-walking densification. The area-loss bug lives here. Read the full algorithm to understand vertex insertion logic.
- `roof_pipeline/panel_snap_v2/validate.py` — Two-pass validation with D-04/D-05/D-06 thresholds. The 65.9% area loss triggers the D-06 hard-fail here.
- `roof_pipeline/panel_snap_v2/__init__.py` — `snap_polygons()` orchestration: winding -> clustering -> graph -> solver -> validate(solver) -> densify -> validate(densify).

### Input validation (dedup location)
- `roof_pipeline/panel_snap_v2/schema.py` — Pydantic schema. Dedup validator goes here per D-01.
- `roof_pipeline/boundaries.py` — `polygons_from_clicks()` consumes `PanelsInput` from schema.py.

### Prior phase decisions
- `.planning/phases/02-apex-solver-integration/02-CONTEXT.md` — D-04 (two-pass validation), D-05 (area thresholds), D-06 (MultiPolygon handling), D-09 (golden-file strategy). These are locked and unchanged by Phase 3.

### Test infrastructure
- `roof_pipeline/panel_snap_v2/tests/` — Existing test directory. New regression test file goes here.
- `roof_pipeline/synthetic.py` — Existing synthetic roof generator. `make_synthetic_multi_hip()` extends this.

### Requirements
- `.planning/REQUIREMENTS.md` — Phase 3 requirements: FIX-01, FIX-02, LABEL-01

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `densify._point_to_segment_dist_xy()`: XY distance + t-parameter calculation — may need modification in the fix
- `densify._z_on_plane()`: Z reconstruction — reusable as-is
- `validate.validate_polygons()`: Two-pass validation — unchanged, but the diagnostic pass (stage="solver") provides baseline data
- `schema.PanelCorners`: Pydantic model with existing `at_least_three_corners` validator — dedup validator chains after it
- `synthetic.make_synthetic_gable()`: Pattern for `make_synthetic_multi_hip()` — returns `SyntheticRoof` dataclass

### Established Patterns
- Copy-on-write: `out = {pid: poly.copy() ...}` — all mutation on copies
- Module-level logger: `log = logging.getLogger(__name__)`
- `from __future__ import annotations` in every file
- Tests in `panel_snap_v2/tests/` with per-module files
- Golden files in `panel_snap_v2/tests/golden/` (Phase 2 pattern)

### Integration Points
- `schema.py` field_validator: chains after existing `at_least_three_corners` validator
- `densify.py`: internal algorithm fix, public API unchanged
- `synthetic.py`: new public function alongside existing `make_synthetic_gable()`
- Test runner: `pytest roof_pipeline/panel_snap_v2/tests/`

</code_context>

<specifics>
## Specific Ideas

- Densify diagnostic logging must use the exact field set: `(panel_a, panel_b, candidate_vertices_considered, vertices_inserted, insertion_positions_xy)` — the user specified this format for reproducing the bug
- Regression test uses inline Python constants, not file I/O — the user explicitly rejected DSM/mask commits and external file references
- The densify bug is an investigate-then-fix: don't jump to a solution without first understanding what vertex insertions cause the self-intersection on panel 8
- "Narrow fix only" is a hard constraint — the user called broader refactoring "scope creep into Phase 3"

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-bug-fixes*
*Context gathered: 2026-04-19*
