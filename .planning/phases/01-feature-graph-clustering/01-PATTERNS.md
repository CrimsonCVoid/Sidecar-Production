# Phase 1: Feature Graph + Clustering - Pattern Map

**Mapped:** 2026-04-18
**Files analyzed:** 8 new/modified files
**Analogs found:** 7 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `roof_pipeline/panel_snap_v2/__init__.py` | config (package init) | N/A | `roof_pipeline/__init__.py` | exact |
| `roof_pipeline/panel_snap_v2/winding.py` | utility (transform) | transform | `roof_pipeline/mesh.py` (lines 17-32, `_plane_basis`) + `roof_pipeline/boundaries.py` (lines 38-48, `_project_onto_plane`) | role-match |
| `roof_pipeline/panel_snap_v2/clustering.py` | service (algorithm) | transform | `roof_pipeline/snapping.py` (lines 178-248, `snap_shared_corners`) | exact |
| `roof_pipeline/panel_snap_v2/graph.py` | service (data structure) | transform | `roof_pipeline/snapping.py` (lines 404-465, `snap_shared_edges`) | role-match |
| `roof_pipeline/panel_snap_v2/tests/__init__.py` | config (test package) | N/A | none (no test infrastructure exists) | N/A |
| `roof_pipeline/panel_snap_v2/tests/test_winding.py` | test | N/A | none (no existing tests) | no-analog |
| `roof_pipeline/panel_snap_v2/tests/test_clustering.py` | test | N/A | none (no existing tests) | no-analog |
| `roof_pipeline/panel_snap_v2/tests/test_graph.py` | test | N/A | none (no existing tests) | no-analog |
| `roof_pipeline/run_real.py` (modified) | controller (CLI) | request-response | itself (lines 49-64, argparse block) | exact |

## Pattern Assignments

### `roof_pipeline/panel_snap_v2/__init__.py` (config, package init)

**Analog:** `roof_pipeline/__init__.py` (lines 1-3)

**Init pattern:**
```python
"""Roof pipeline: segmented DSM -> 3D mesh + dimensioned cut sheets."""

__version__ = "0.1.0"
```

**Adaptation for panel_snap_v2:** The subpackage `__init__.py` must re-export the public API function `snap_polygons` so that `run_real.py` can do `from .panel_snap_v2 import snap_polygons`. Per D-04, this is the sole public API surface. Include a module-level docstring describing the subpackage purpose. No `__version__` needed (version lives at package root).

---

### `roof_pipeline/panel_snap_v2/winding.py` (utility, transform)

**Analog 1:** `roof_pipeline/mesh.py` -- orthonormal basis construction (lines 17-32)

**Orthonormal 2D basis from plane normal** (lines 17-32):
```python
def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two orthonormal in-plane vectors (u, v) given a unit normal.

    Pick an arbitrary world axis least aligned with the normal, project it
    into the plane to get u, then v = n x u. This avoids the degenerate case
    where the seed vector is parallel to the normal.
    """
    # Choose world axis least aligned with normal
    if abs(normal[0]) < 0.9:
        seed = np.array([1.0, 0.0, 0.0])
    else:
        seed = np.array([0.0, 1.0, 0.0])
    u = seed - (seed @ normal) * normal
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    return u, v
```

**Analog 2:** `roof_pipeline/boundaries.py` -- plane projection (lines 38-48)

**Project 3D points onto plane** (lines 38-48):
```python
def _project_onto_plane(points_3d: np.ndarray, plane: Plane) -> np.ndarray:
    """Orthogonally project (N, 3) points onto the plane."""
    delta = points_3d - plane.centroid
    signed_dist = delta @ plane.normal
    return points_3d - signed_dist[:, None] * plane.normal
```

**Adaptation for winding.py:** Per D-09, the winding module must project 3D vertices to 2D using `_plane_basis` (from mesh.py pattern). Per D-08, the 2D polygon is then passed to `shapely.geometry.polygon.orient(poly, sign=1.0)` for CCW enforcement. Per D-10, the resulting permutation is applied to the original 3D array -- do NOT regenerate 3D from 2D. Per D-11, `TopologicalError` on self-intersecting input propagates with panel ID.

**Imports pattern** (follow module convention from `planes.py` lines 1-10):
```python
"""Per-panel winding normalization to consistent CCW order."""

from __future__ import annotations

import logging

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from ..planes import Plane

log = logging.getLogger(__name__)
```

**Error handling pattern** (from `planes.py` lines 29-30):
```python
if points_xyz.ndim != 2 or points_xyz.shape[1] != 3 or points_xyz.shape[0] < 3:
    raise ValueError(f"need (N>=3, 3) points, got {points_xyz.shape}")
```

---

### `roof_pipeline/panel_snap_v2/clustering.py` (service, transform)

**Analog:** `roof_pipeline/snapping.py` -- union-find vertex clustering (lines 178-248)

**Copy-on-write pattern** (line 200):
```python
out = {pid: poly.copy() for pid, poly in polygons.items()}
```

**Flatten all vertices to (pid, vertex_index, xyz) items** (lines 201-204):
```python
items: list[tuple[int, int, np.ndarray]] = []
for pid, poly in out.items():
    for vi, v in enumerate(poly):
        items.append((pid, vi, v))
```

**Manual union-find implementation** (lines 206-218):
```python
n = len(items)
parent = list(range(n))

def find(i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i

def union(i: int, j: int) -> None:
    ri, rj = find(i), find(j)
    if ri != rj:
        parent[rj] = ri
```

**Tolerance-squared distance check** (lines 220-227):
```python
tol2 = tol * tol
for i in range(n):
    vi = items[i][2]
    for j in range(i + 1, n):
        vj = items[j][2]
        d = vi - vj
        if float(d @ d) <= tol2:
            union(i, j)
```

**Group items by root, compute centroid, write back** (lines 229-244):
```python
groups: dict[int, list[int]] = {}
for i in range(n):
    r = find(i)
    groups.setdefault(r, []).append(i)

snap_count = 0
for members in groups.values():
    if len(members) <= 1:
        continue
    verts = np.stack([items[m][2] for m in members])
    centroid = verts.mean(axis=0)
    for m in members:
        pid, vi, _ = items[m]
        out[pid][vi] = centroid
    snap_count += len(members) - 1
```

**Logging summary** (lines 246-248):
```python
log.info("snapped %d corners into shared positions (tol=%.3f m)",
         snap_count, tol)
return out
```

**Adaptation for clustering.py:** Per D-05 and TOPO-02, replace the single-pass tolerance loop with three-pass expanding tolerance (0.3t, 0.6t, t). Per CONTEXT D-37, use `scipy.cluster.hierarchy.DisjointSet` instead of the manual find/union implementation. The three passes are cumulative -- each pass uses the union-find state from the prior pass. The function signature must accept `planes: dict[int, Plane]` (per TOPO-01 signature) even though Phase 1 only builds clusters without solving.

**Imports pattern** (adapted from snapping.py lines 19-27):
```python
"""Three-pass expanding-tolerance vertex clustering via union-find."""

from __future__ import annotations

import logging

import numpy as np
from scipy.cluster.hierarchy import DisjointSet

from ..planes import Plane

log = logging.getLogger(__name__)
```

---

### `roof_pipeline/panel_snap_v2/graph.py` (service, data structure)

**Analog:** `roof_pipeline/snapping.py` -- edge iteration and panel-pair adjacency (lines 404-465)

**Panel-pair iteration pattern** (lines 430-432):
```python
panel_ids = sorted(out.keys())

for i, pid_a in enumerate(panel_ids):
    for pid_b in panel_ids[i + 1:]:
```

**Edge walking within a polygon** (lines 437-439):
```python
for ea in range(n_a):
    a0 = poly_a[ea]
    a1 = poly_a[(ea + 1) % n_a]
```

**Function signature pattern** (from snapping.py lines 404-408):
```python
def snap_shared_edges(
    polygons: dict[int, np.ndarray],
    tol: float = 0.15,
) -> dict[int, np.ndarray]:
```

**Adaptation for graph.py:** The feature graph is built from cluster groups (output of `clustering.py`). For each cluster, record which panels contribute vertices to it -- this determines valence. Nodes represent clusters (vertex groups), edges represent "panel P touches cluster C". Per D-02, output the full INTG-02 schema with `position_xyz: null` for unsolved nodes. Per TOPO-03, classify clusters by valence: corner=2, ridge_apex=3, hip_apex=4+.

**Imports pattern:**
```python
"""Feature graph construction from clustered vertex groups."""

from __future__ import annotations

import json
import logging
import sys

import numpy as np

from ..planes import Plane

log = logging.getLogger(__name__)
```

**Data structure -- use dataclass** (following `planes.py` Plane dataclass pattern, lines 13-18):
```python
@dataclass
class Plane:
    normal: np.ndarray       # (3,) unit normal, oriented n_z >= 0
    centroid: np.ndarray     # (3,) point on the plane (mean of input points)
    rms_residual: float      # RMS of orthogonal distances from points to plane
    d: float                 # plane offset so n . x = d for any x on the plane
```

The feature graph can use a dataclass or namedtuple per CONTEXT "Claude's Discretion". Follow the Plane dataclass style if using a dataclass.

---

### `roof_pipeline/run_real.py` (modified -- add `--snap-v2-dryrun` flag)

**Analog:** itself -- argparse block (lines 49-64)

**Existing argparse pattern** (lines 49-64):
```python
ap = argparse.ArgumentParser()
ap.add_argument("dsm", type=Path)
ap.add_argument("mask", type=Path)
ap.add_argument("--out-dir", type=Path, default=Path("output_real"))
ap.add_argument("--snap-tol", type=float, default=1.0,
                help="corner snap tolerance in meters (clicks within this merge)")
ap.add_argument("--no-clicks", action="store_true",
                help="ignore panels.json and re-trace contours from the mask")
ap.add_argument("--project-name", default="ROOF PROTOTYPE")
ap.add_argument("--project-address", default="ADDRESS UNKNOWN")
ap.add_argument("--estimate-number", default=None,
                help="defaults to the DSM filename stem")
ap.add_argument("--coverage-in", type=float, default=24.0)
ap.add_argument("--profile", default="SV")
ap.add_argument("--waste-pct", type=float, default=11.0)
args = ap.parse_args()
```

**Existing import block** (lines 17-28):
```python
from .boundaries import extract_panel_polygons, polygons_from_clicks
from .cutsheets import write_cutsheets_pdf
from .mesh import build_roof_mesh, export_mesh
from .planes import fit_all_panels
from .snapping import (
    densify_shared_edges_xy,
    snap_shared_corners_xy,
    snap_shared_edges,
)
from .ts_export import write_ts_json
from .ts_render_pdf import render_pdf_from_json
from .shop_drawings import generate_shop_drawings, roof_dict_from_pipeline
```

**Pipeline stage logging pattern** (lines 83-102):
```python
log.info("=== plane fits ===")
planes = fit_all_panels(dsm, mask, res_m)

# ... conditional branch based on flag ...
log.info("=== corner snapping (XY, tol=%.3f m) ===", args.snap_tol)
```

**Adaptation:** Add `--snap-v2-dryrun` as `action="store_true"`. Add conditional import of `panel_snap_v2`. When the flag is set, run winding + clustering + graph build, print JSON to stdout, print summary to stderr, and `sys.exit(0)` before reaching mesh/export stages. Per D-01 and D-03.

---

### `roof_pipeline/panel_snap_v2/tests/test_winding.py` (test)

No existing test files in the project. Tests must be created from scratch.

**Test requirements from CONTEXT (D-12):**
1. TEST-07: L-shape both windings normalize to same CCW
2. `test_steep_plane_winding`: 60-degree pitch panel where naive XY-drop would flip
3. `test_self_intersecting_raises`: bowtie polygon raises TopologicalError with panel ID

**Recommended structure** (based on pytest conventions, since REQUIREMENTS.md calls for `pytest roof_pipeline/panel_snap_v2/tests/`):
```python
"""Tests for winding normalization."""

from __future__ import annotations

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.winding import normalize_winding


class TestLShapedWinding:
    """TEST-07: Non-convex L-shaped panel normalizes correctly."""

    def test_ccw_and_cw_l_shape_produce_same_result(self):
        ...

    def test_steep_plane_winding(self):
        ...

    def test_self_intersecting_raises(self):
        ...
```

---

### `roof_pipeline/panel_snap_v2/tests/test_clustering.py` (test)

**Test requirements from CONTEXT and REQUIREMENTS:**
- TEST-04: Three points at pairwise distances (0.9, 0.9, 1.3) with tol=1.0 must cluster via multi-pass expansion
- TEST-05: Two panels traversing shared edge in opposite order; winding normalization produces correct feature graph

**Recommended structure:**
```python
"""Tests for three-pass expanding-tolerance vertex clustering."""

from __future__ import annotations

import numpy as np
import pytest

from roof_pipeline.panel_snap_v2.clustering import cluster_vertices


class TestTransitiveCluster:
    """TEST-04: Multi-pass expansion clusters transitively."""

    def test_transitive_cluster_above_tol(self):
        ...


class TestMixedWindingClustering:
    """TEST-05: Opposite winding still clusters correctly."""

    def test_mixed_winding_hip(self):
        ...
```

---

### `roof_pipeline/panel_snap_v2/tests/test_graph.py` (test)

**Test requirements:** Feature graph construction correctness, valence counting, JSON schema conformance.

**Recommended structure:**
```python
"""Tests for feature graph construction."""

from __future__ import annotations

import json

import numpy as np
import pytest

from roof_pipeline.panel_snap_v2.graph import build_feature_graph


class TestFeatureGraph:
    """Feature graph node/edge construction from clusters."""

    def test_valence_distribution(self):
        ...

    def test_json_schema_conformance(self):
        ...
```

---

## Shared Patterns

### Module boilerplate
**Source:** Every module in `roof_pipeline/`
**Apply to:** All new `.py` files in `panel_snap_v2/`

```python
"""Module-level docstring describing purpose."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)
```

Every file starts with `from __future__ import annotations`. Every file creates `log = logging.getLogger(__name__)`. Imports are organized: stdlib, then third-party, then relative package imports.

### Data container convention
**Source:** `roof_pipeline/planes.py` (lines 13-18) + `roof_pipeline/boundaries.py` (return types)
**Apply to:** `winding.py`, `clustering.py`, `graph.py`

The core interchange types are:
- `polygons: dict[int, np.ndarray]` -- panel ID to (K, 3) vertex array
- `planes: dict[int, Plane]` -- panel ID to fitted Plane dataclass

All functions in the subpackage must accept and return these types. Per TOPO-01, `snap_polygons` must return `dict[int, np.ndarray]` matching the existing `snap_shared_edges` signature.

### Copy-on-write mutation
**Source:** `roof_pipeline/snapping.py` (line 109, 200, 267, 336, 426)
**Apply to:** Any function that transforms `polygons`

```python
out = {pid: poly.copy() for pid, poly in polygons.items()}
```

Never mutate input arrays. Copy first, then modify the copies.

### Error handling
**Source:** `roof_pipeline/planes.py` (lines 29-30, 70-78)
**Apply to:** All new modules

- `ValueError` for invalid input shapes: `raise ValueError(f"need (N>=3, 3) points, got {points_xyz.shape}")`
- `log.warning()` + `continue` for skippable items: `log.warning("panel %d has %d pixels, skipping", pid, rows.size)`
- Per D-11, `TopologicalError` from Shapely must NOT be caught in winding.py -- let it propagate with panel ID context.

### Logging
**Source:** `roof_pipeline/snapping.py` (lines 173-174, 246-247, 317-318, 399-400, 464)
**Apply to:** All new modules

Summary log at function exit with counts and tolerance:
```python
log.info("snapped %d corners into shared positions (tol=%.3f m)",
         snap_count, tol)
```

Per-item progress where useful:
```python
log.info("panel %d: %d boundary vertices after RDP", pid, verts_proj.shape[0])
```

### Plane import
**Source:** `roof_pipeline/snapping.py` (line 25), `roof_pipeline/boundaries.py` (line 12), `roof_pipeline/mesh.py` (line 12)
**Apply to:** `winding.py`, `clustering.py`, `graph.py`

```python
from ..planes import Plane
```

All modules that need the `Plane` dataclass import it from `roof_pipeline.planes` using relative import.

---

## No Analog Found

Files with no close match in the codebase (planner should follow pytest conventions and project style):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `roof_pipeline/panel_snap_v2/tests/__init__.py` | config | N/A | No test infrastructure exists in the project; empty file |
| `roof_pipeline/panel_snap_v2/tests/test_winding.py` | test | N/A | No existing test files in the project |
| `roof_pipeline/panel_snap_v2/tests/test_clustering.py` | test | N/A | No existing test files in the project |
| `roof_pipeline/panel_snap_v2/tests/test_graph.py` | test | N/A | No existing test files in the project |

For all test files, follow standard pytest conventions: `test_` prefixed functions or methods inside `Test` prefixed classes. Import the module under test directly. Use `numpy.testing.assert_allclose` for floating-point comparisons. Use `pytest.raises` for expected exceptions.

## Notable Observations

1. **Shapely is NOT in requirements.txt** despite CLAUDE.md and CONTEXT.md claiming it is. The planner must add `shapely>=2.0` to `requirements.txt` as part of this phase. TOPO-11 says "no new dependencies" but lists shapely as "already present" -- it is not. This discrepancy should be noted in the plan.

2. **The existing union-find in `snapping.py` (lines 206-218) is a manual implementation.** Decision D-37 says to use `scipy.cluster.hierarchy.DisjointSet` instead. The manual implementation is a useful reference for understanding the pattern, but the new code should use scipy's class.

3. **`mesh.py` `_plane_basis` (lines 17-32) is the exact orthonormal basis algorithm needed by `winding.py`.** Per D-09, this must NOT be a naive XY-drop. The existing implementation in `mesh.py` handles degenerate cases (normal nearly parallel to seed axis). Consider extracting to a shared utility or duplicating with attribution.

4. **No test infrastructure exists at all.** No `conftest.py`, no `pytest.ini`, no test directories. The planner must create the test package init files and potentially a project-level pytest configuration.

## Metadata

**Analog search scope:** `roof_pipeline/` (14 modules)
**Files scanned:** 14 source modules + 1 requirements.txt
**Pattern extraction date:** 2026-04-18
