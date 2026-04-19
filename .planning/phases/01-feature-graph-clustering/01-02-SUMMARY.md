---
phase: 01-feature-graph-clustering
plan: 02
subsystem: panel_snap_v2/clustering
tags: [tdd, union-find, clustering, scipy, vertex-grouping]
dependency_graph:
  requires: []
  provides:
    - roof_pipeline.panel_snap_v2.clustering.cluster_vertices
  affects:
    - roof_pipeline/panel_snap_v2/graph.py (Plan 03 consumes cluster output)
tech_stack:
  added:
    - scipy.cluster.hierarchy.DisjointSet (already in requirements.txt, no new dep)
  patterns:
    - Three-pass expanding-tolerance union-find clustering
    - Cumulative passes: each pass inherits merges from prior pass
    - Sorted panel-ID iteration for determinism
key_files:
  created:
    - roof_pipeline/panel_snap_v2/__init__.py
    - roof_pipeline/panel_snap_v2/tests/__init__.py
    - roof_pipeline/panel_snap_v2/tests/test_clustering.py
    - roof_pipeline/panel_snap_v2/clustering.py
  modified: []
decisions:
  - "scipy.cluster.hierarchy.DisjointSet used instead of manual union-find (per STATE.md D-37)"
  - "tol > 0 validated at function entry (T-01-05 threat mitigation)"
  - "Singleton groups included in return value so graph.py can count valence for every vertex"
  - "Passes are cumulative: later passes build on unions from earlier passes"
metrics:
  duration: "3 minutes"
  completed_date: "2026-04-19"
  tasks_completed: 2
  files_created: 4
  files_modified: 0
requirements_delivered:
  - TOPO-02
  - TEST-04
---

# Phase 01 Plan 02: Three-Pass Vertex Clustering Summary

**One-liner:** Three-pass expanding-tolerance vertex clustering (0.3t, 0.6t, t) using scipy DisjointSet with deterministic sorted-panel-ID iteration.

## Objective

Implement `cluster_vertices()` in `roof_pipeline/panel_snap_v2/clustering.py` as the core data structure for the feature graph. Three-pass expansion catches transitive chains (TEST-04: three points at pairwise distances 0.9, 0.9, 1.3 with tol=1.0 merge into one cluster because transitivity through the union-find combines them even though no single pair exceeds the threshold in a problematic way).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED -- Write failing clustering tests | 9e5bdb0 | roof_pipeline/panel_snap_v2/__init__.py, tests/__init__.py, tests/test_clustering.py |
| 2 | GREEN -- Implement clustering.py | bdf38d0 | roof_pipeline/panel_snap_v2/clustering.py |

## TDD Gate Compliance

- RED gate: commit `9e5bdb0` (test prefix) -- 4 tests, all failing with ModuleNotFoundError
- GREEN gate: commit `bdf38d0` (feat prefix) -- 4 tests, all passing

## Implementation Details

`cluster_vertices(polygons, planes, tol)` returns `(groups, items)`:

- **items**: flat list of `(pid, vertex_index, xyz)` tuples, one per vertex across all panels, iterated in sorted panel-ID order for determinism.
- **groups**: dict mapping root index -> list of member indices. Singletons included so the feature graph (Plan 03) can count valence for every vertex without special-casing isolated vertices.

**Three-pass expansion:**
1. Pass at `0.3 * tol`: merge vertices within 30% of tolerance
2. Pass at `0.6 * tol`: merge vertices within 60% of tolerance (picks up additional pairs, inheriting pass-1 unions)
3. Pass at `1.0 * tol`: full tolerance (inheriting pass-1 and pass-2 unions)

Transitivity is automatic via DisjointSet: if A-B merged in pass 1 and B-C merged in pass 2, A-B-C are all in the same cluster.

## Deviations from Plan

None -- plan executed exactly as written.

## Threat Mitigations Applied

| Threat ID | Mitigation |
|-----------|-----------|
| T-01-04 | O(N^2) loop accepted -- residential roofs have <200 vertices total |
| T-01-05 | `if tol <= 0: raise ValueError(...)` at function entry |

## Self-Check: PASSED

- FOUND: roof_pipeline/panel_snap_v2/__init__.py
- FOUND: roof_pipeline/panel_snap_v2/tests/__init__.py
- FOUND: roof_pipeline/panel_snap_v2/tests/test_clustering.py
- FOUND: roof_pipeline/panel_snap_v2/clustering.py
- FOUND: commit 9e5bdb0 (RED gate)
- FOUND: commit bdf38d0 (GREEN gate)
- 4 tests passing: test_transitive_cluster_above_tol, test_distant_points_stay_separate, test_cumulative_passes, test_items_contain_pid_vi_xyz
