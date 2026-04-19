# Phase 2: Apex Solver + Integration - Pattern Map

**Mapped:** 2026-04-18
**Files analyzed:** 13 (9 new, 4 modified)
**Analogs found:** 13 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `roof_pipeline/panel_snap_v2/solver.py` | service | transform | `roof_pipeline/panel_snap_v2/clustering.py` | exact |
| `roof_pipeline/panel_snap_v2/densify.py` | service | transform | `roof_pipeline/snapping.py` (densify_shared_edges_xy) | exact |
| `roof_pipeline/panel_snap_v2/validate.py` | service | transform | `roof_pipeline/panel_snap_v2/winding.py` | exact |
| `roof_pipeline/panel_snap_v2/schema.py` | model | transform | `roof_pipeline/planes.py` (Plane dataclass) | role-match |
| `roof_pipeline/panel_snap_v2/__init__.py` | service | transform | (self -- Phase 1 stub) | exact |
| `roof_pipeline/run_real.py` | controller | request-response | (self -- existing code) | exact |
| `roof_pipeline/boundaries.py` | service | transform | (self -- existing code) | exact |
| `requirements.txt` | config | N/A | (self -- existing file) | exact |
| `roof_pipeline/panel_snap_v2/tests/test_solver.py` | test | transform | `roof_pipeline/panel_snap_v2/tests/test_clustering.py` | exact |
| `roof_pipeline/panel_snap_v2/tests/test_densify.py` | test | transform | `roof_pipeline/panel_snap_v2/tests/test_clustering.py` | exact |
| `roof_pipeline/panel_snap_v2/tests/test_validate.py` | test | transform | `roof_pipeline/panel_snap_v2/tests/test_winding.py` | exact |
| `roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py` | test | batch | `roof_pipeline/panel_snap_v2/tests/test_graph.py` | role-match |
| `roof_pipeline/panel_snap_v2/tests/golden/gable/` | config | N/A | (no analog -- new artifact) | N/A |

## Pattern Assignments

### `roof_pipeline/panel_snap_v2/solver.py` (service, transform)

**Analog:** `roof_pipeline/panel_snap_v2/clustering.py`

This is the closest analog because it: (1) lives in the same subpackage, (2) consumes the same `(polygons, planes, tol)` signature, (3) iterates over cluster groups, and (4) the solver literally picks up where clustering leaves off -- it reads cluster groups and writes solved positions back.

**Imports pattern** (lines 1-22):
```python
"""Three-pass expanding-tolerance vertex clustering via union-find.
[module docstring]
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.cluster.hierarchy import DisjointSet

from ..planes import Plane

log = logging.getLogger(__name__)
```

Solver will replace `from scipy.cluster.hierarchy import DisjointSet` with `from scipy.linalg import lstsq` (or similar). It will also need `from .clustering import cluster_vertices` and `from .graph import build_feature_graph`.

**Constants pattern** (lines 24-28):
```python
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PASS_FRACTIONS = (0.3, 0.6, 1.0)
```

Solver should define condition-number thresholds here:
```python
_COND_WARN = 1e8
_COND_FAIL = 1e12
```

**Core transform pattern -- function signature** (lines 36-65):
```python
def cluster_vertices(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> tuple[dict[int, list[int]], list[tuple[int, int, np.ndarray]]]:
    """Cluster polygon vertices using three-pass expanding tolerance.
    [docstring]
    """
    if tol <= 0:
        raise ValueError(f"tol must be positive, got {tol!r}")
```

Solver function should follow the same signature convention (`polygons`, `planes`, `tol` args) and early-validation pattern.

**Section divider pattern** (throughout):
```python
# ------------------------------------------------------------------
# 1. Flatten all vertices into a list for indexed access.
# ------------------------------------------------------------------
```

**Logging pattern -- per-item progress** (lines 97-102):
```python
log.info(
    "clustering pass %.1ft (tol=%.3f m): %d items",
    fraction,
    pass_tol,
    n,
)
```

**Logging pattern -- summary** (lines 122-128):
```python
log.info(
    "clustered %d vertices into %d groups (tol=%.3f m)",
    n,
    len(groups),
    tol,
)
```

For solver, D-03 requires: `log.info("snap_v2: solved %d apices (%d ridge, %d hip), %d corner snaps, %d fallbacks", ...)`.

**Error handling pattern -- D-01 fallback logging:**
```python
# D-01: WARNING for cond in (1e8, 1e12]
log.warning(
    "snap_v2 fallback cluster_id=%d panels=%s cond=%.2e rms=[%s]",
    cluster_id, panel_ids, cond_val,
    ",".join(f"{r:.4f}" for r in rms_values),
)
# D-01: Hard-fail for cond > 1e12
raise RuntimeError(
    f"snap_v2 singular cluster_id={cluster_id} panels={panel_ids} "
    f"cond={cond_val:.2e} rms=[...] -- check upstream plane fits"
)
```

**Z-reconstruction helper from snapping.py** (lines 34-43):
```python
def _z_on_plane(x: float, y: float, plane: Plane) -> float:
    """Z-coordinate on ``plane`` at world (x, y). Uses n . p = d."""
    nx, ny, nz = plane.normal
    if abs(nz) < 1e-9:
        return float(plane.centroid[2])  # fallback: centroid Z
    return (plane.d - nx * x - ny * y) / nz
```

Solver must reuse this for valence-2 (D-02) Z reconstruction. Either import from `snapping` or copy into solver (preferred -- snapping.py is being superseded).

---

### `roof_pipeline/panel_snap_v2/densify.py` (service, transform)

**Analog:** `roof_pipeline/snapping.py` -- `densify_shared_edges_xy()` (lines 322-401)

This is the closest analog because: (1) it does the exact same operation (insert mid-edge vertices so two panels share the same edge), (2) uses the same data structures, (3) uses XY projection + plane Z reconstruction -- which is what the v2 densifier needs.

**Imports pattern** (from snapping.py lines 1-27):
```python
from __future__ import annotations

import logging

import numpy as np

from ..planes import Plane

log = logging.getLogger(__name__)
```

The v2 densifier will additionally need: `from .graph import build_feature_graph` (to identify shared edges from the feature graph rather than brute-force pairwise search).

**Copy-on-write pattern** (snapping.py line 109):
```python
out = {pid: poly.copy() for pid, poly in polygons.items()}
```

**Edge-walking with insert pattern** (snapping.py lines 353-397):
```python
poly_a = out[pid_a]
n = poly_a.shape[0]
new_verts: list[np.ndarray] = []

for i in range(n):
    p0 = poly_a[i]
    p1 = poly_a[(i + 1) % n]
    new_verts.append(p0)

    edge_xy = (p1 - p0)[:2]
    edge_len2 = float(edge_xy @ edge_xy)
    if edge_len2 < 1e-12:
        continue

    insertions: list[tuple[float, np.ndarray]] = []
    for q in candidates:
        d_xy, t = _point_to_segment_dist_xy(q, p0, p1)
        if not (0.05 < t < 0.95):
            continue
        if d_xy > tol:
            continue
        # Skip near endpoints
        if float(np.linalg.norm((q - p0)[:2])) <= tol:
            continue
        if float(np.linalg.norm((q - p1)[:2])) <= tol:
            continue
        proj_xy = p0[:2] + t * edge_xy
        if plane_a is not None:
            z = _z_on_plane(float(proj_xy[0]), float(proj_xy[1]), plane_a)
        else:
            z = float(0.5 * (p0[2] + p1[2]))
        insertions.append((t, np.array([proj_xy[0], proj_xy[1], z])))

    if not insertions:
        continue

    insertions.sort(key=lambda x: x[0])
    # Dedupe near-coincident projections
    kept: list[tuple[float, np.ndarray]] = []
    for t, p in insertions:
        if kept and abs(t - kept[-1][0]) * (edge_len2 ** 0.5) < tol:
            continue
        kept.append((t, p))
    for _, p in kept:
        new_verts.append(p)
        insert_count += 1

out[pid_a] = np.array(new_verts)
```

**Point-to-segment helper** (snapping.py lines 46-59):
```python
def _point_to_segment_dist_xy(
    p: np.ndarray, a: np.ndarray, b: np.ndarray,
) -> tuple[float, float]:
    """Shortest XY distance from ``p`` to segment ``ab``. Returns (distance, t)."""
    p2, a2, b2 = p[:2], a[:2], b[:2]
    ab = b2 - a2
    denom = float(ab @ ab)
    if denom == 0.0:
        return float(np.linalg.norm(p2 - a2)), 0.0
    t = float((p2 - a2) @ ab) / denom
    t_clamped = max(0.0, min(1.0, t))
    closest = a2 + t_clamped * ab
    return float(np.linalg.norm(p2 - closest)), t_clamped
```

**Summary logging** (snapping.py lines 399-401):
```python
log.info("densified %d new vertices in plan view (tol=%.3f m, XY-adjacency)",
         insert_count, tol)
```

---

### `roof_pipeline/panel_snap_v2/validate.py` (service, transform)

**Analog:** `roof_pipeline/panel_snap_v2/winding.py`

This is the closest analog because: (1) it already uses Shapely for polygon operations, (2) it iterates per-panel with the same `dict[int, np.ndarray]` pattern, (3) it uses plane-aware 2D projection, (4) it has the same copy-on-write pattern.

**Imports pattern** (winding.py lines 1-25):
```python
from __future__ import annotations

import logging

import numpy as np
from shapely.errors import TopologicalError
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from ..planes import Plane

log = logging.getLogger(__name__)
```

Validate will add:
```python
from shapely.validation import make_valid
```

**2D projection helper** (winding.py lines 52-62):
```python
def _project_to_2d(verts_3d: np.ndarray, plane: Plane) -> np.ndarray:
    """Project (K, 3) 3D vertices onto the plane's local 2D coordinate frame."""
    u, v = _plane_basis(plane.normal)
    delta = verts_3d - plane.centroid
    return np.column_stack([delta @ u, delta @ v])
```

This helper (and `_plane_basis`) should be reused by `validate.py` for building Shapely polygons from 3D vertices. Either import from winding.py or factor into a shared private module.

**Per-panel iteration with validation** (winding.py lines 86-95):
```python
out: dict[int, np.ndarray] = {pid: poly.copy() for pid, poly in polygons.items()}

for pid, poly in out.items():
    # --- Input validation ---
    if poly.ndim != 2 or poly.shape[1] != 3 or poly.shape[0] < 3:
        raise ValueError(
            f"panel {pid}: need (K>=3, 3) vertices, got shape {poly.shape}"
        )
    plane = planes[pid]
```

**Shapely polygon construction** (winding.py lines 99-108):
```python
verts_2d = _project_to_2d(poly, plane)
shp = Polygon(verts_2d)

if not shp.is_simple:
    raise TopologicalError(
        f"panel {pid}: self-intersecting polygon cannot be oriented"
    )
```

For validate.py, the two-pass pattern (D-04) should follow:
```python
# Pass 1 (post-solver): read-only diagnostic
shp = Polygon(verts_2d)
if not (shp.is_valid and shp.is_simple):
    log.debug("panel %d invalid after solver: %s", pid, explain_validity(shp))

# Pass 2 (post-densify): repair gate
shp = Polygon(verts_2d)
if not shp.is_valid:
    log.warning("panel %d invalid after densify, repairing: %s", pid, explain_validity(shp))
    repaired = make_valid(shp)
    # D-06: keep largest piece if MultiPolygon
    # D-05: area change check
```

---

### `roof_pipeline/panel_snap_v2/schema.py` (model, transform)

**Analog:** `roof_pipeline/planes.py` -- `Plane` dataclass (lines 13-18)

This is the closest analog for a data model definition in this codebase. The schema.py file defines Pydantic models rather than dataclasses, but the structural role is the same.

**Dataclass pattern** (planes.py lines 13-18):
```python
@dataclass
class Plane:
    normal: np.ndarray       # (3,) unit normal, oriented n_z >= 0
    centroid: np.ndarray     # (3,) point on the plane (mean of input points)
    rms_residual: float      # RMS of orthogonal distances from points to plane
    d: float                 # plane offset so n . x = d for any x on the plane
```

For Pydantic, schema.py will follow:
```python
from __future__ import annotations

from pydantic import BaseModel, field_validator

class PanelCorners(BaseModel):
    id: int
    corners_pix: list[list[float]]

    @field_validator("corners_pix")
    @classmethod
    def at_least_three_corners(cls, v):
        if len(v) < 3:
            raise ValueError(f"need >= 3 corners, got {len(v)}")
        return v

class PanelsInput(BaseModel):
    panels: list[PanelCorners]
```

**Module header pattern** (planes.py lines 1-10):
```python
"""Per-panel plane fitting via SVD (no RANSAC -- mask already constrains region)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)
```

---

### `roof_pipeline/panel_snap_v2/__init__.py` (service, transform -- MODIFY)

**Analog:** Self (current Phase 1 stub, lines 1-48)

**Current stub to modify** (lines 17-48):
```python
def snap_polygons(
    polygons: dict,
    planes: dict,
    tol: float = 1.0,
) -> dict:
    """Drop-in replacement for snapping.snap_shared_edges (TOPO-01)."""
    import numpy as np

    # Copy-on-write per established pipeline convention
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    # Phase 1: graph is built but positions are not solved.
    # Phase 2 will add: solve apices, densify edges, validate.
    return out
```

Phase 2 transforms this into:
```python
def snap_polygons(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> dict[int, np.ndarray]:
    """Topology-aware snap: cluster, solve apices, densify edges, validate."""
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    # 1. Normalize winding
    out = normalize_winding(out, planes)
    # 2. Build feature graph (clustering inside)
    graph = build_feature_graph(out, planes, tol=tol)
    # 3. Solve apex positions
    out = solve_apices(out, planes, graph, tol=tol)
    # 4. Validate pass 1 (read-only diagnostic)
    validate_polygons(out, planes, stage="solver")
    # 5. Densify shared edges
    out = densify_edges(out, planes, graph, tol=tol)
    # 6. Validate pass 2 (repair gate)
    out = validate_polygons(out, planes, stage="densify", repair=True)
    return out
```

---

### `roof_pipeline/run_real.py` (controller, request-response -- MODIFY)

**Analog:** Self (existing code, lines 46-69 argparse, lines 91-119 snap dispatch)

**Argparse pattern -- adding a flag** (lines 56-68):
```python
ap.add_argument("--snap-tol", type=float, default=1.0,
                help="corner snap tolerance in meters (clicks within this merge)")
ap.add_argument("--no-clicks", action="store_true",
                help="ignore panels.json and re-trace contours from the mask")
ap.add_argument("--snap-v2-dryrun", action="store_true",
                help="print snap-v2 feature graph as JSON and exit")
```

Add `--snap-v2` alongside (same style):
```python
ap.add_argument("--snap-v2", action="store_true",
                help="use topology-aware snap engine v2 instead of pairwise snap")
```

**Snap dispatch pattern** (lines 91-119):
```python
if args.snap_v2_dryrun:
    log.info("=== snap-v2 dry-run ===")
    # ...
    sys.exit(0)

panels_json = args.mask.with_suffix(".json")
if panels_json.exists() and not args.no_clicks:
    log.info("=== boundaries from clicks (%s) ===", panels_json.name)
    polygons = polygons_from_clicks(panels_json, dsm, res_m, planes)
    log.info("=== corner snapping (XY, tol=%.3f m) ===", args.snap_tol)
    polygons = snap_shared_corners_xy(polygons, planes, tol=args.snap_tol)
    # ...
```

Phase 2 adds a new branch after dryrun:
```python
if args.snap_v2:
    log.info("=== snap-v2 engine ===")
    polygons = snap_v2(polygons, planes, tol=args.snap_tol)
    # Write snap_v2_features.json sidecar
    # ...
else:
    # existing v1 path unchanged
```

**Sidecar JSON output pattern** (lines 130-133):
```python
log.info("=== TS exporter JSON ===")
json_path = write_ts_json(
    polygons, planes, mesh, args.out_dir / "cutsheets.ts.json",
)
```

`snap_v2_features.json` follows the same pattern:
```python
features_path = args.out_dir / "snap_v2_features.json"
with open(features_path, "w") as f:
    json.dump(graph, f, indent=2, sort_keys=True)
log.info("wrote snap_v2_features.json: %s", features_path)
```

---

### `roof_pipeline/boundaries.py` (service, transform -- MODIFY)

**Analog:** Self (existing `polygons_from_clicks`, lines 51-98)

**Current function entry** (lines 51-73):
```python
def polygons_from_clicks(
    panels_json_path: str | Path,
    dsm: np.ndarray,
    res_m: float,
    planes: dict[int, Plane],
) -> dict[int, np.ndarray]:
    """Build per-panel polygons from the labeler's saved click coordinates."""
    path = Path(panels_json_path)
    with open(path) as f:
        meta = json.load(f)
```

Phase 2 adds Pydantic validation (D-07/D-08) between JSON load and processing:
```python
from .panel_snap_v2.schema import PanelsInput

def polygons_from_clicks(...):
    path = Path(panels_json_path)
    with open(path) as f:
        raw = json.load(f)
    # Pydantic validation at the input boundary (VALID-01, D-07)
    validated = PanelsInput.model_validate(raw)
    for entry in validated.panels:
        # ... use entry.id, entry.corners_pix ...
```

---

### `roof_pipeline/panel_snap_v2/tests/test_solver.py` (test, transform)

**Analog:** `roof_pipeline/panel_snap_v2/tests/test_clustering.py`

**Test file structure** (test_clustering.py lines 1-19):
```python
"""Tests for three-pass expanding-tolerance vertex clustering."""

from __future__ import annotations

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.clustering import cluster_vertices


def _make_plane(normal=(0, 0, 1), centroid=(0, 0, 5)):
    """Helper: build a horizontal Plane."""
    n = np.array(normal, dtype=float)
    n /= np.linalg.norm(n)
    if n[2] < 0:
        n = -n
    c = np.array(centroid, dtype=float)
    return Plane(normal=n, centroid=c, rms_residual=0.01, d=float(n @ c))
```

**Test class pattern** (test_clustering.py lines 22-53):
```python
class TestTransitiveCluster:
    """TEST-04: Multi-pass expansion clusters transitively."""

    def test_transitive_cluster_above_tol(self):
        """Three points at pairwise distances (0.9, 0.9, 1.3) with tol=1.0 cluster."""
        A = np.array([[0.0, 0.0, 5.0]])
        # ... setup ...
        groups, items = cluster_vertices(polygons, planes, tol=1.0)
        cluster_sizes = [len(members) for members in groups.values()]
        assert max(cluster_sizes) == 3, f"Expected one cluster of size 3, got sizes {cluster_sizes}"
```

**Assertion patterns:**
```python
# Exact match
assert len(shared_features) == 2

# Numpy allclose
np.testing.assert_allclose(result[1], expected, atol=1e-10)

# Error message with diagnostics
assert max(cluster_sizes) == 3, f"Expected ..., got sizes {cluster_sizes}"
```

Solver tests should create geometric fixtures (2-panel ridge, 3-panel hip, 4-panel apex, near-singular case) following the same `_make_plane` + `np.array` pattern.

---

### `roof_pipeline/panel_snap_v2/tests/test_densify.py` (test, transform)

**Analog:** `roof_pipeline/panel_snap_v2/tests/test_clustering.py` (same structure)

Same pattern as test_solver.py above. Test class names follow requirement IDs (e.g., `TestSharedEdgeDensification`).

---

### `roof_pipeline/panel_snap_v2/tests/test_validate.py` (test, transform)

**Analog:** `roof_pipeline/panel_snap_v2/tests/test_winding.py`

**Test class for Shapely validation** (follow test_winding.py lines 23-58):
```python
class TestLShapedWinding:
    """TEST-07: Non-convex L-shaped panel winding normalization."""

    L_CCW_2D = np.array([...], dtype=float)
    L_CW_2D = L_CCW_2D[::-1].copy()

    @staticmethod
    def _to_3d(verts_2d, z=5.0):
        return np.column_stack([verts_2d, np.full(len(verts_2d), z)])

    def test_ccw_and_cw_l_shape_produce_same_result(self):
        ...
        np.testing.assert_allclose(result_from_ccw[1], result_from_cw[1], atol=1e-10)
```

Validate tests will follow the same class fixture pattern with geometric edge cases (valid polygon, invalid polygon, MultiPolygon repair, area-change thresholds).

---

### `roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py` (test, batch)

**Analog:** `roof_pipeline/panel_snap_v2/tests/test_graph.py` (partial match -- same subpackage test structure, but this test is a multi-tier integration test not a unit test)

**Integration test pattern from test_graph.py** (lines 87-125):
```python
class TestJsonSchema:
    """Feature graph output matches INTG-02 schema."""

    def test_schema_conformance(self):
        poly1 = np.array([[0, 0, 5], [2, 0, 5], [1, 2, 5]], dtype=float)
        poly2 = np.array([[2, 0, 5], [4, 0, 5], [3, 2, 5]], dtype=float)
        plane = _make_plane()
        graph = build_feature_graph(
            {1: poly1, 2: poly2}, {1: plane, 2: plane}, tol=0.1,
        )
        # ... assertions ...
        json.dumps(graph)  # Must be JSON-serializable
```

For the gable smoke test, the tiered comparison (D-09) requires:
```python
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

GOLDEN_DIR = Path(__file__).parent / "golden" / "gable"


def pytest_addoption(parser):
    parser.addoption("--regenerate-golden", action="store_true", default=False)


class TestGableSmokeIdentity:
    """D-09: Tiered golden-file comparison for gable roof."""

    def _run_gable_pipeline(self):
        """Run snap_v2 on synthetic gable, return (polygons, features_json, mesh)."""
        # Build synthetic gable via main.py's synthetic path
        ...

    def test_tier0_polygon_allclose(self, request):
        """Tier 0: Snapped polygon dict at atol=1e-12."""
        polygons = self._run_gable_pipeline()
        golden_path = GOLDEN_DIR / "polygons.npz"
        if request.config.getoption("--regenerate-golden"):
            np.savez(golden_path, **{str(k): v for k, v in polygons.items()})
            pytest.skip("regenerated golden")
        golden = np.load(golden_path)
        for pid_str, expected in golden.items():
            np.testing.assert_allclose(
                polygons[int(pid_str)], expected, atol=1e-12,
            )

    def test_tier1_json_byte_identity(self):
        """Tier 1: snap_v2_features.json byte identity."""
        ...
        assert actual_bytes == golden_bytes

    def test_tier2_mesh_structural(self):
        """Tier 2: OBJ/glTF parsed via trimesh, vertices at atol=1e-9."""
        ...
        np.testing.assert_allclose(actual.vertices, golden.vertices, atol=1e-9, rtol=1e-9)
        np.testing.assert_array_equal(actual.faces, golden.faces)
```

---

## Shared Patterns

### Module Header
**Source:** Every module in `roof_pipeline/panel_snap_v2/`
**Apply to:** All new .py files (solver.py, densify.py, validate.py, schema.py)
```python
"""Module-level docstring in imperative mood."""

from __future__ import annotations

import logging

import numpy as np

from ..planes import Plane

log = logging.getLogger(__name__)
```

### Copy-on-Write
**Source:** `roof_pipeline/snapping.py` line 109, `roof_pipeline/panel_snap_v2/clustering.py` line 45, `roof_pipeline/panel_snap_v2/winding.py` line 88
**Apply to:** solver.py, densify.py, validate.py (all transform functions)
```python
out = {pid: poly.copy() for pid, poly in polygons.items()}
```

### Early Validation
**Source:** `roof_pipeline/panel_snap_v2/clustering.py` lines 66-67, `roof_pipeline/panel_snap_v2/winding.py` lines 92-95
**Apply to:** solver.py, densify.py, validate.py
```python
if tol <= 0:
    raise ValueError(f"tol must be positive, got {tol!r}")

# Per-panel shape check:
if poly.ndim != 2 or poly.shape[1] != 3 or poly.shape[0] < 3:
    raise ValueError(
        f"panel {pid}: need (K>=3, 3) vertices, got shape {poly.shape}"
    )
```

### Section Dividers
**Source:** `roof_pipeline/panel_snap_v2/clustering.py` lines 24-26, 69-72, 86-89
**Apply to:** All new .py files with multi-step logic
```python
# ---------------------------------------------------------------------------
# 1. Step description
# ---------------------------------------------------------------------------
```

(Also the shorter variant used in graph.py:)
```python
# -------------------------------------------------------------------
# 1. Step description
# -------------------------------------------------------------------
```

### Test Helper: _make_plane
**Source:** `roof_pipeline/panel_snap_v2/tests/test_clustering.py` lines 12-19, identical in test_graph.py and test_winding.py
**Apply to:** test_solver.py, test_densify.py, test_validate.py, test_smoke_gable.py
```python
def _make_plane(normal=(0, 0, 1), centroid=(0, 0, 5)):
    """Helper: build a horizontal Plane."""
    n = np.array(normal, dtype=float)
    n /= np.linalg.norm(n)
    if n[2] < 0:
        n = -n
    c = np.array(centroid, dtype=float)
    return Plane(normal=n, centroid=c, rms_residual=0.01, d=float(n @ c))
```

Consider extracting this into a shared `conftest.py` or `tests/_fixtures.py` to avoid duplication across 4+ test files.

### Test Assertions
**Source:** `roof_pipeline/panel_snap_v2/tests/test_winding.py` line 49, test_clustering.py line 53
**Apply to:** All test files
```python
# Numeric closeness
np.testing.assert_allclose(result, expected, atol=1e-10)

# Structural equality with diagnostic message
assert len(shared) == 2, f"Expected 2 shared features, got {len(shared)}"

# Exception matching
with pytest.raises(Exception, match="42"):
    function_that_should_fail(42)
```

### Z Reconstruction from Plane
**Source:** `roof_pipeline/snapping.py` lines 34-43
**Apply to:** solver.py (valence-2 D-02), densify.py (edge insertions)
```python
def _z_on_plane(x: float, y: float, plane: Plane) -> float:
    """Z-coordinate on ``plane`` at world (x, y). Uses n . p = d."""
    nx, ny, nz = plane.normal
    if abs(nz) < 1e-9:
        return float(plane.centroid[2])
    return (plane.d - nx * x - ny * y) / nz
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `roof_pipeline/panel_snap_v2/tests/golden/gable/` | config | N/A | New artifact directory -- golden files are generated by `--regenerate-golden` |
| `roof_pipeline/panel_snap_v2/schema.py` (Pydantic models) | model | N/A | No Pydantic models exist in the codebase yet. Dataclass pattern from `planes.py` provides structural guidance, but Pydantic-specific patterns (validators, `model_validate()`) have no local analog. Use Pydantic v2 documentation conventions. |

---

## Metadata

**Analog search scope:** `roof_pipeline/`, `roof_pipeline/panel_snap_v2/`, `roof_pipeline/panel_snap_v2/tests/`
**Files scanned:** 15 source files read
**Pattern extraction date:** 2026-04-18
