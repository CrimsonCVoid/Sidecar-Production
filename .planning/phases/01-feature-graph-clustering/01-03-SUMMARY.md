---
phase: 01-feature-graph-clustering
plan: 03
subsystem: panel_snap_v2/graph
tags: [tdd, feature-graph, valence, INTG-02, snap-v2-dryrun, cli]
dependency_graph:
  requires:
    - roof_pipeline/panel_snap_v2/winding.py
    - roof_pipeline/panel_snap_v2/clustering.py
    - roof_pipeline/planes.py
  provides:
    - roof_pipeline/panel_snap_v2/graph.py
    - roof_pipeline/panel_snap_v2/tests/test_graph.py
    - snap_polygons public API (TOPO-01)
    - --snap-v2-dryrun CLI flag (D-01, D-02, D-03)
  affects:
    - roof_pipeline/run_real.py
    - roof_pipeline/panel_snap_v2/__init__.py
    - requirements.txt
tech_stack:
  added:
    - pytest>=7.0 (added to requirements.txt)
  patterns:
    - INTG-02 feature graph schema (features + edges)
    - Valence classification (unshared/corner/ridge_apex/hip_apex)
    - Copy-on-write polygon pass-through (Phase 1 solver stub)
    - JSON-to-stdout + summary-to-stderr dry-run output pattern
key_files:
  created:
    - roof_pipeline/panel_snap_v2/graph.py
    - roof_pipeline/panel_snap_v2/tests/test_graph.py
  modified:
    - roof_pipeline/panel_snap_v2/__init__.py
    - roof_pipeline/run_real.py
    - requirements.txt
decisions:
  - "Edge entry created only when a panel pair shares 2+ feature nodes (a single shared vertex is a corner, not a traversable edge)"
  - "shapely>=2.0 already present in requirements.txt from Plan 01 (no re-add needed); pytest>=7.0 added as new entry"
  - "snap_polygons accepts planes param (unlike snap_shared_edges) because Phase 2 solver needs plane normals -- I/O shape matches TOPO-01 but signature is extended"
  - "print_dryrun does not call sys.exit() internally -- exit(0) is called in run_real.py after print_dryrun returns, keeping graph.py testable without mocking sys.exit"
metrics:
  duration: "169s (~2 min)"
  completed: "2026-04-19"
  tasks_completed: 2
  files_changed: 5
requirements_delivered:
  - TOPO-01
  - TOPO-03
  - TOPO-11
  - TEST-05
---

# Phase 01 Plan 03: Feature Graph + CLI Integration Summary

**One-liner:** Feature graph construction (INTG-02 schema) with valence classification, snap_polygons public API, and --snap-v2-dryrun CLI flag wired into run_real.py, completing Phase 1 with all 12 tests passing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED -- Write failing graph tests | 97aa049 | tests/test_graph.py |
| 2 | GREEN -- Implement graph.py, update __init__.py, wire run_real.py, add pytest to requirements.txt | bb625c2 | graph.py, __init__.py, run_real.py, requirements.txt |

## What Was Built

### graph.py

`roof_pipeline/panel_snap_v2/graph.py` exposes two public functions:

```python
def build_feature_graph(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> dict:
```

Algorithm:
1. Calls `normalize_winding(polygons, planes)` -- ensures consistent CCW vertex order before clustering (handles TEST-05 mixed-winding case)
2. Calls `cluster_vertices(normed, planes, tol=tol)` -- three-pass expanding-tolerance union-find
3. Builds feature nodes: one per cluster, `panel_ids` = sorted unique panel IDs from cluster members, `valence` = `len(panel_ids)`, `position_xyz` = `None` (Phase 1)
4. Builds edges: for each panel pair (a, b) where a < b, collects all feature IDs where both panels appear; creates edge entry if 2+ shared features
5. Returns `{"features": [...], "edges": [...]}` conforming to INTG-02 schema

```python
def print_dryrun(graph: dict) -> None:
```

Outputs JSON to stdout (indented), human-readable summary to stderr (node/edge counts + valence distribution). The caller (`run_real.py`) calls `sys.exit(0)` after this returns.

### __init__.py

Full public API with re-exports:

```python
from .clustering import cluster_vertices
from .graph import build_feature_graph
from .winding import normalize_winding

def snap_polygons(polygons, planes, tol=1.0) -> dict:
    """Drop-in replacement for snapping.snap_shared_edges (TOPO-01)."""
```

`snap_polygons` returns a copy-on-write dict of the input polygons unchanged (Phase 1 stub -- solver is Phase 2).

### run_real.py

Changes:
- `import sys` added to standard imports
- `from .panel_snap_v2 import snap_polygons as snap_v2` added
- `from .panel_snap_v2.graph import build_feature_graph, print_dryrun` added
- `--snap-v2-dryrun` argparse flag added
- Dry-run branch inserted after plane fits: builds polygons (click or contour path), calls `build_feature_graph`, calls `print_dryrun`, then `sys.exit(0)`

### requirements.txt

- `shapely>=2.0` moved to after `scipy>=1.11` (was at end of file, already present from Plan 01)
- `pytest>=7.0` added at end

## TDD Gate Compliance

RED gate: commit `97aa049` -- `test(01-03): add failing graph tests (RED gate)` -- 4 tests, all failing with `ModuleNotFoundError: No module named 'roof_pipeline.panel_snap_v2.graph'`.

GREEN gate: commit `bb625c2` -- `feat(01-03): implement feature graph, public API, and dry-run CLI flag (GREEN)` -- all 12 tests pass.

REFACTOR gate: not needed -- code is clean as written.

## Tests Passing

```
roof_pipeline/panel_snap_v2/tests/test_clustering.py::TestTransitiveCluster::test_transitive_cluster_above_tol PASSED
roof_pipeline/panel_snap_v2/tests/test_clustering.py::TestTransitiveCluster::test_distant_points_stay_separate PASSED
roof_pipeline/panel_snap_v2/tests/test_clustering.py::TestMultiPassBenefit::test_cumulative_passes PASSED
roof_pipeline/panel_snap_v2/tests/test_clustering.py::TestItemsStructure::test_items_contain_pid_vi_xyz PASSED
roof_pipeline/panel_snap_v2/tests/test_graph.py::TestMixedWindingHip::test_mixed_winding_hip PASSED
roof_pipeline/panel_snap_v2/tests/test_graph.py::TestValenceDistribution::test_four_panel_hip_apex PASSED
roof_pipeline/panel_snap_v2/tests/test_graph.py::TestJsonSchema::test_schema_conformance PASSED
roof_pipeline/panel_snap_v2/tests/test_graph.py::TestCornerValence::test_shared_single_vertex_is_valence_2 PASSED
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestLShapedWinding::test_ccw_and_cw_l_shape_produce_same_result PASSED
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestLShapedWinding::test_ccw_input_unchanged PASSED
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestSteepPlaneWinding::test_steep_plane_normalizes_correctly PASSED
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestSelfIntersectingRaises::test_bowtie_raises_with_panel_id PASSED
12 passed in 0.60s
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] print_dryrun does not call sys.exit(0) internally**
- **Found during:** Task 2 implementation
- **Issue:** Plan specified `print_dryrun` should call `sys.exit(0)`. But `graph.py` is a pure geometry module and calling `sys.exit()` inside it would make it untestable (tests would need to mock sys.exit). The `sys.exit(0)` is placed in `run_real.py` after the `print_dryrun()` call, which is the correct pattern for testability.
- **Fix:** `sys.exit(0)` placed in `run_real.py` immediately after `print_dryrun(graph)` call. `graph.py` remains a pure transform module.
- **Files modified:** roof_pipeline/run_real.py, roof_pipeline/panel_snap_v2/graph.py
- **Commit:** bb625c2

## Known Stubs

`snap_polygons()` in `__init__.py` is an intentional Phase 1 stub -- it normalizes winding and clusters but returns the input polygons unchanged (no apex positions solved). The solver is Phase 2 (TOPO-06, TOPO-07). This is documented in the function docstring and plan CONTEXT.md (D-06).

## Threat Surface Scan

No new network endpoints or auth paths. The `--snap-v2-dryrun` flag is a read-only operation per T-01-07 (accepted). The `snap_polygons` input validation flows through `normalize_winding` shape checks and `cluster_vertices` tol validation per T-01-08 (mitigated -- ValueError raised on malformed input, not silent corruption).

## Self-Check

Files exist:
- FOUND: /Users/carterbrady/Mymetalrooferbackupmvp-firstcommit/.claude/worktrees/agent-af5df160/roof_pipeline/panel_snap_v2/graph.py
- FOUND: /Users/carterbrady/Mymetalrooferbackupmvp-firstcommit/.claude/worktrees/agent-af5df160/roof_pipeline/panel_snap_v2/tests/test_graph.py
- FOUND: /Users/carterbrady/Mymetalrooferbackupmvp-firstcommit/.claude/worktrees/agent-af5df160/roof_pipeline/panel_snap_v2/__init__.py
- FOUND: /Users/carterbrady/Mymetalrooferbackupmvp-firstcommit/.claude/worktrees/agent-af5df160/roof_pipeline/run_real.py
- FOUND: /Users/carterbrady/Mymetalrooferbackupmvp-firstcommit/.claude/worktrees/agent-af5df160/requirements.txt

Commits exist:
- FOUND: 97aa049 (RED gate -- failing graph tests)
- FOUND: bb625c2 (GREEN gate -- feature graph implementation)

## Self-Check: PASSED
