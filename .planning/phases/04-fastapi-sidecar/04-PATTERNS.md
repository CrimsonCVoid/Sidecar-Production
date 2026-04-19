# Phase 4: FastAPI Sidecar - Pattern Map

**Mapped:** 2026-04-19
**Files analyzed:** 15 new/modified files
**Analogs found:** 12 / 15

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `roof_pipeline/api/__init__.py` | config | -- | `roof_pipeline/panel_snap_v2/tests/__init__.py` | exact |
| `roof_pipeline/api/main.py` | controller | request-response | `roof_pipeline/run_real.py` | role-match |
| `roof_pipeline/api/config.py` | config | -- | `roof_pipeline/panel_snap_v2/schema.py` | role-match |
| `roof_pipeline/api/deps.py` | provider | request-response | `roof_pipeline/panel_snap_v2/schema.py` | partial |
| `roof_pipeline/api/middleware.py` | middleware | request-response | -- | no-analog |
| `roof_pipeline/api/snap.py` | controller | request-response | `roof_pipeline/panel_snap_v2/__init__.py` | role-match |
| `roof_pipeline/api/pipeline.py` | controller | request-response + event-driven | `roof_pipeline/run_real.py` | exact |
| `roof_pipeline/api/labels.py` | controller | CRUD | -- | no-analog |
| `roof_pipeline/api/schemas.py` | model | -- | `roof_pipeline/panel_snap_v2/schema.py` | exact |
| `roof_pipeline/run_real.py` (modify) | service | transform | `roof_pipeline/run_real.py` | self |
| `roof_pipeline/api/tests/__init__.py` | test | -- | `roof_pipeline/panel_snap_v2/tests/__init__.py` | exact |
| `roof_pipeline/api/tests/conftest.py` | test | -- | `roof_pipeline/panel_snap_v2/tests/conftest.py` | role-match |
| `roof_pipeline/api/tests/test_snap.py` | test | request-response | `roof_pipeline/panel_snap_v2/tests/test_schema.py` | role-match |
| `roof_pipeline/api/tests/test_pipeline.py` | test | request-response | `roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py` | role-match |
| `roof_pipeline/api/tests/test_middleware.py` | test | request-response | `roof_pipeline/panel_snap_v2/tests/test_graph.py` | partial |

## Pattern Assignments

### `roof_pipeline/api/__init__.py` (config, package marker)

**Analog:** `roof_pipeline/panel_snap_v2/tests/__init__.py`

**Full file pattern** (line 1):
```python
"""Tests for the panel_snap_v2 topology-aware snap engine subpackage."""
```

**Application:** Single-line module docstring. For `api/__init__.py`, use:
```python
"""FastAPI HTTP sidecar for the roof pipeline."""
```

---

### `roof_pipeline/api/main.py` (controller, request-response)

**Analog:** `roof_pipeline/run_real.py`

**Imports pattern** (lines 1-33):
```python
"""Run the full pipeline on a real GeoTIFF DSM + a labeled .npy panel mask."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import rasterio

from .boundaries import extract_panel_polygons, polygons_from_clicks
from .cutsheets import write_cutsheets_pdf
from .mesh import build_roof_mesh, export_mesh
from .planes import fit_all_panels
# ... more imports

log = logging.getLogger("roof_pipeline.real")
```

**Key conventions to follow:**
- `from __future__ import annotations` first import in every file
- Module-level docstring explaining purpose
- Module-level logger: `log = logging.getLogger(__name__)`
- Relative imports within the `roof_pipeline` package

**Application to `api/main.py`:** This file creates the FastAPI app, mounts routers, and configures middleware. It replaces `run_real.py`'s argparse/CLI setup with FastAPI app factory. The logging config in `run_real.py` (lines 48-52) shows the project's logging setup pattern:
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
```

---

### `roof_pipeline/api/config.py` (config, pydantic-settings)

**Analog:** `roof_pipeline/panel_snap_v2/schema.py`

**Pydantic model pattern** (lines 1-13, 16-19):
```python
"""Pydantic input validation schema for panel click data (VALID-01, D-07).

Single source of truth for both CLI (polygons_from_clicks) and future
HTTP API (Milestone 2 FastAPI). Lives in panel_snap_v2 per D-08.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, field_validator

log = logging.getLogger(__name__)


class PanelCorners(BaseModel):
    """One panel's click data: integer ID and list of [col_px, row_px] corners."""

    model_config = ConfigDict(strict=True, extra="forbid")
```

**Key conventions to follow:**
- `ConfigDict(strict=True, extra="forbid")` on input models (for the Settings model, use `extra="ignore"` per pydantic-settings convention since environment may have extra vars)
- Module docstring explaining purpose and cross-references to decisions
- Type annotations on all fields
- Validators use `@field_validator` + `@classmethod` pattern

---

### `roof_pipeline/api/deps.py` (provider, dependency injection)

**Analog:** `roof_pipeline/panel_snap_v2/schema.py` (partial -- Pydantic pattern only)

**Application:** New pattern for the project. No existing FastAPI dependency injection exists. Follow RESEARCH.md Pattern 2 (lru_cache + Depends). Must still follow project conventions:
- `from __future__ import annotations`
- Module docstring
- `log = logging.getLogger(__name__)`

---

### `roof_pipeline/api/snap.py` (controller, request-response)

**Analog:** `roof_pipeline/panel_snap_v2/__init__.py`

**Core function wrapping pattern** (lines 84-123):
```python
def snap_polygons(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> tuple[dict[int, np.ndarray], dict]:
    """Topology-aware snap: cluster, solve apices, densify edges, validate.

    Drop-in replacement for snapping.snap_shared_edges (TOPO-01), with an
    extended signature that accepts planes (needed for plane-aware solving).

    Returns:
        (snapped_polygons, feature_graph) -- the graph is needed by run_real.py
        for the snap_v2_features.json sidecar (INTG-02).
    """
    # Copy-on-write per established pipeline convention
    out = {pid: poly.copy() for pid, poly in polygons.items()}

    # 1. Normalize winding to CCW
    out = normalize_winding(out, planes)

    # 2. Build feature graph (clustering inside)
    graph = build_feature_graph(out, planes, tol=tol)

    # 3. Solve apex positions
    out, solved_positions = solve_apices(out, planes, graph, tol=tol)

    # ...stages continue...

    return out, graph
```

**Key conventions to follow for snap.py router:**
- The router wraps `snap_polygons()` and `build_feature_graph()` -- do NOT reimplement geometry
- Accept `PanelsInput` as the request body (reuse existing schema from `panel_snap_v2/schema.py`)
- Copy-on-write convention: functions return new data, not mutate inputs
- Log each stage with `log.info()`
- Return tuple of (polygons, graph) must be serialized to JSON response

**Feature graph JSON structure** from `graph.py` (lines 51-53):
```python
# Returns dict matching INTG-02 schema:
# {
#     "features": [{"id": int, "valence": int, "position_xyz": null, "panel_ids": [int]}],
#     "edges": [{"panel_a": int, "panel_b": int, "feature_ids": [int]}]
# }
```

---

### `roof_pipeline/api/pipeline.py` (controller, request-response + event-driven)

**Analog:** `roof_pipeline/run_real.py`

**Pipeline stage sequence pattern** (lines 91-175):
```python
log.info("=== plane fits ===")
planes = fit_all_panels(dsm, mask, res_m)

# ... click data or contour extraction ...

if args.snap_v2:
    log.info("=== snap-v2 engine (tol=%.3f m) ===", args.snap_tol)
    polygons, feature_graph = snap_v2(polygons, planes, tol=args.snap_tol)

    # Write snap_v2_features.json sidecar (INTG-02)
    features_path = args.out_dir / "snap_v2_features.json"
    with open(features_path, "w") as f:
        json.dump(feature_graph, f, indent=2, sort_keys=True)
    log.info("wrote snap_v2_features.json: %s", features_path)

log.info("=== mesh ===")
mesh = build_roof_mesh(polygons, planes)
paths = export_mesh(mesh, args.out_dir)

log.info("=== cut sheets ===")
pdf_path = write_cutsheets_pdf(
    polygons, planes, mesh, args.out_dir / "cutsheets.pdf",
)

log.info("=== TS exporter JSON ===")
json_path = write_ts_json(
    polygons, planes, mesh, args.out_dir / "cutsheets.ts.json",
)

log.info("=== TS-render PDF (mirrors browser output) ===")
ts_pdf_path = render_pdf_from_json(
    json_path, args.out_dir / "cutsheets.ts.pdf",
)

log.info("=== shop drawings PDF (Integrity-Metals format) ===")
# ... shop drawings ...

log.info("DONE  obj=%s  gltf=%s  pdf=%s  json=%s  ts_pdf=%s  shop_pdf=%s",
         paths["obj"], paths["gltf"], pdf_path, json_path,
         ts_pdf_path, shop_pdf_path)
```

**Error handling pattern from run_real.py** (lines 83-84):
```python
if mask.shape != dsm.shape:
    raise ValueError(f"mask shape {mask.shape} != dsm shape {dsm.shape}")
```

**Key conventions for pipeline.py:**
- Stage boundaries defined at lines 91, 109, 116, 138, 142, 147, 157 map to D-10 status updates: `plane_fits(15%) -> boundaries(30%) -> snap(50%) -> mesh(65%) -> cutsheets(80%) -> shop_drawings(90%) -> done(100%)`
- Each stage uses a plain function call from the respective module (no complex wrapping)
- Stage logging uses `log.info("=== stage name ===")` separator pattern
- File I/O uses `Path` objects with `mkdir(parents=True, exist_ok=True)`
- The `main()` function's DSM loading (lines 37-44, 76-86) must be refactored so the API can call `run_pipeline()` with pre-loaded data

**DSM loading pattern** (lines 37-44):
```python
def _load_dsm(path: Path) -> tuple[np.ndarray, float]:
    with rasterio.open(path) as src:
        dsm = src.read(1).astype(np.float32)
        res_m = abs(float(src.transform.a))
        nodata = src.nodata
    if nodata is not None:
        dsm = np.where(dsm == nodata, np.nan, dsm)
    return dsm, res_m
```

---

### `roof_pipeline/api/schemas.py` (model, response schemas)

**Analog:** `roof_pipeline/panel_snap_v2/schema.py`

**Pydantic model pattern** (lines 16-64):
```python
class PanelCorners(BaseModel):
    """One panel's click data: integer ID and list of [col_px, row_px] corners."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: int
    corners_pix: list[list[float]]

    @field_validator("corners_pix")
    @classmethod
    def strip_close_polygon_duplicate(cls, v: list[list[float]]) -> list[list[float]]:
        """Strip duplicate last corner if it matches the first."""
        # ... validation logic ...
        return v


class PanelsInput(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    panels: list[PanelCorners]
    res_m: float | None = None
    shape: list[int] | None = None
    panel_count: int | None = None
    panel_pixel_counts: dict[str, int] | None = None
```

**Key conventions for response schemas:**
- Use `ConfigDict(strict=True, extra="forbid")` for request models
- Response models can use `extra="ignore"` since they are server-constructed
- Field types use PEP 604 union syntax (`float | None`) thanks to `from __future__ import annotations`
- Docstrings on every model class explaining its purpose

---

### `roof_pipeline/run_real.py` (modify -- extract `run_pipeline()`)

**Self-analog.** The refactoring extracts the pipeline stages from `main()` (lines 47-176) into a new function `run_pipeline()` that takes data arguments instead of CLI args.

**Current `main()` structure** (lines 47-176):
- Lines 47-72: argparse setup (stays in `main()`)
- Lines 74-89: DSM/mask loading and validation (stays in `main()`, also callable from API)
- Lines 91-92: plane fits
- Lines 94-137: boundary extraction + snap
- Lines 138-175: mesh + PDF + JSON outputs

**Refactoring pattern:** Extract lines 91-175 into `run_pipeline(dsm, mask, res_m, ...)`. `main()` becomes a thin wrapper:
```python
def main():
    # ... argparse ...
    dsm, res_m = _load_dsm(args.dsm)
    mask = np.load(args.mask).astype(np.uint8)
    run_pipeline(dsm, mask, res_m, ...)
```

---

### `roof_pipeline/api/tests/__init__.py` (test, package marker)

**Analog:** `roof_pipeline/panel_snap_v2/tests/__init__.py`

**Full file pattern** (line 1):
```python
"""Tests for the panel_snap_v2 topology-aware snap engine subpackage."""
```

**Application:** Same single-line docstring convention:
```python
"""Tests for the FastAPI sidecar API endpoints."""
```

---

### `roof_pipeline/api/tests/conftest.py` (test, fixtures)

**Analog:** `roof_pipeline/panel_snap_v2/tests/conftest.py`

**Fixture pattern** (lines 1-27):
```python
"""Shared test helpers for panel_snap_v2 tests."""

from __future__ import annotations

import numpy as np

from roof_pipeline.planes import Plane


def _make_plane(normal=(0, 0, 1), centroid=(0, 0, 5)):
    """Helper: build a Plane from normal and centroid."""
    n = np.array(normal, dtype=float)
    n /= np.linalg.norm(n)
    if n[2] < 0:
        n = -n
    c = np.array(centroid, dtype=float)
    return Plane(normal=n, centroid=c, rms_residual=0.01, d=float(n @ c))


def pytest_addoption(parser):
    """Add --regenerate-golden CLI flag (D-11)."""
    parser.addoption(
        "--regenerate-golden",
        action="store_true",
        default=False,
        help="regenerate golden files instead of comparing against them",
    )
```

**Key conventions for API test conftest:**
- Module docstring
- `from __future__ import annotations`
- Helper functions prefixed with `_` for test data construction
- `pytest_addoption()` for custom CLI flags

**API-specific fixtures needed:**
- `TestClient` fixture from `starlette.testclient`
- Mock Supabase client fixture
- Sample `PanelsInput` fixture (reuse data from `test_schema.py`)

---

### `roof_pipeline/api/tests/test_snap.py` (test, API endpoint)

**Analog:** `roof_pipeline/panel_snap_v2/tests/test_schema.py`

**Test class pattern** (lines 1-48):
```python
"""Tests for Pydantic input validation schema (VALID-01, VALID-02)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from roof_pipeline.panel_snap_v2.schema import PanelCorners, PanelsInput


class TestSchemaValidation:
    """VALID-01/VALID-02: Pydantic schema rejects malformed panel JSON."""

    def test_valid_input_passes(self):
        """Well-formed dict passes PanelsInput.model_validate without error."""
        data = {
            "panels": [
                {"id": 1, "corners_pix": [[0, 0], [1, 0], [0.5, 1]]},
            ],
        }
        result = PanelsInput.model_validate(data)
        assert len(result.panels) == 1
        assert result.panels[0].id == 1
        assert len(result.panels[0].corners_pix) == 3

    def test_missing_corners_pix_raises(self):
        """Dict with missing corners_pix raises ValidationError."""
        data = {"panels": [{"id": 1}]}
        with pytest.raises(ValidationError):
            PanelsInput.model_validate(data)
```

**Key conventions for API tests:**
- Test classes named `TestXxxYyy` with docstring referencing requirement IDs
- Each test method has a descriptive docstring explaining the behavior under test
- Positive tests first, then negative/error tests
- `pytest.raises` for expected errors with optional `match=` for message validation
- Absolute imports from `roof_pipeline.*`

---

### `roof_pipeline/api/tests/test_pipeline.py` (test, pipeline integration)

**Analog:** `roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py`

**Module-scoped fixture pattern** (lines 40-62):
```python
@pytest.fixture(scope="module")
def gable_pipeline():
    """Run both v1 and v2 snap on synthetic gable, return results."""
    roof = make_synthetic_gable()
    planes = fit_all_panels(roof.dsm, roof.mask, roof.res_m)
    polygons = extract_panel_polygons(roof.mask, roof.dsm, roof.res_m, planes)

    # V1 path (reference)
    v1_polygons = snap_shared_edges(polygons, tol=0.15)
    v1_mesh = build_roof_mesh(v1_polygons, planes)

    # V2 path (under test)
    v2_polygons, v2_graph = snap_polygons(polygons, planes, tol=0.15)
    v2_mesh = build_roof_mesh(v2_polygons, planes)

    return {
        "v1_polygons": v1_polygons,
        "v2_polygons": v2_polygons,
        "v2_graph": v2_graph,
        "v1_mesh": v1_mesh,
        "v2_mesh": v2_mesh,
        "planes": planes,
    }
```

**Test class with fixture injection** (lines 65-92):
```python
class TestGableSmokeIdentity:
    """D-09: Tiered golden-file comparison for gable roof."""

    def test_tier0_polygon_allclose(self, request, gable_pipeline):
        """Tier 0 (pre-flight): Snapped polygon dict at atol=1e-12."""
        v2 = gable_pipeline["v2_polygons"]
        golden_path = GOLDEN_DIR / "polygons.npz"

        if request.config.getoption("--regenerate-golden"):
            # ... regeneration logic ...
            pytest.skip("regenerated golden: polygons.npz")

        assert golden_path.exists(), (
            f"Golden file missing: {golden_path}. Run with --regenerate-golden"
        )
```

**Key conventions for pipeline tests:**
- Heavy setup in `scope="module"` fixtures (expensive operations run once)
- Return dicts from fixtures for multiple result access
- Golden-file comparison for determinism testing
- Multi-line assert messages with f-strings

---

### `roof_pipeline/api/tests/test_middleware.py` (test, middleware)

**Analog:** `roof_pipeline/panel_snap_v2/tests/test_graph.py` (partial -- structural output validation)

**JSON structure validation pattern** (lines 78-116):
```python
class TestJsonSchema:
    """Feature graph output matches INTG-02 schema."""

    def test_schema_conformance(self):
        """Output has features and edges with correct field names and types."""
        poly1 = np.array([[0, 0, 5], [2, 0, 5], [1, 2, 5]], dtype=float)
        poly2 = np.array([[2, 0, 5], [4, 0, 5], [3, 2, 5]], dtype=float)

        plane = _make_plane()
        graph = build_feature_graph(
            {1: poly1, 2: poly2}, {1: plane, 2: plane}, tol=0.1,
        )

        # Top-level keys
        assert "features" in graph
        assert "edges" in graph

        # Feature fields
        for f in graph["features"]:
            assert "id" in f
            assert "valence" in f
            assert isinstance(f["id"], int)
            assert isinstance(f["valence"], int)
```

**Application to middleware tests:** Validate that log output contains required structured JSON fields (trace_id, sample_id, endpoint, latency_ms, error_type). Same "check each field exists and has correct type" pattern.

---

## Shared Patterns

### Module Header
**Source:** Every file in `roof_pipeline/` (e.g., `planes.py` lines 1-10, `boundaries.py` lines 1-15, `mesh.py` lines 1-14)
**Apply to:** All new files in `roof_pipeline/api/`
```python
"""Module docstring explaining purpose and context."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)
```

### Pydantic Model Convention
**Source:** `roof_pipeline/panel_snap_v2/schema.py` (lines 16-19)
**Apply to:** `api/config.py`, `api/schemas.py`
```python
class ModelName(BaseModel):
    """Docstring."""

    model_config = ConfigDict(strict=True, extra="forbid")

    field_name: type
```

### Error Handling Convention
**Source:** `roof_pipeline/planes.py` (lines 29-30, 70-78), `roof_pipeline/mesh.py` (lines 48-49, 68-69)
**Apply to:** All API endpoint handlers (translate to HTTP status codes)
```python
# Input validation: raise ValueError
if points_xyz.ndim != 2 or points_xyz.shape[1] != 3 or points_xyz.shape[0] < 3:
    raise ValueError(f"need (N>=3, 3) points, got {points_xyz.shape}")

# Algorithmic failure: raise RuntimeError
if tris.size == 0:
    raise RuntimeError(f"earcut returned no triangles for polygon shape {uv.shape}")

# Recoverable skip: log.warning() + continue
if rows.size < 3:
    log.warning("panel %d has %d pixels, skipping", pid, rows.size)
    continue
```

**API translation:**
- `ValueError` -> 422 Unprocessable Entity
- `RuntimeError` -> 500 Internal Server Error (with error_type in response)
- `log.warning()` + skip -> include skipped items in response metadata

### Path and Output Convention
**Source:** `roof_pipeline/mesh.py` (lines 79-88), `roof_pipeline/ts_export.py` (lines 105-112)
**Apply to:** Pipeline background task file handling before Supabase Storage upload
```python
def export_mesh(mesh: trimesh.Trimesh, out_dir: str | Path) -> dict[str, Path]:
    """Write OBJ and glTF; return the output paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    obj_path = out / "roof.obj"
    gltf_path = out / "roof.gltf"
    mesh.export(obj_path)
    mesh.export(gltf_path)
    log.info("wrote %s and %s", obj_path, gltf_path)
    return {"obj": obj_path, "gltf": gltf_path}
```

### Logging Convention
**Source:** `roof_pipeline/run_real.py` (lines 34, 48-52, 76-79, 91, 173-175)
**Apply to:** All API modules
```python
# Module-level logger
log = logging.getLogger(__name__)

# Stage separator
log.info("=== stage name ===")

# Per-item progress
log.info("panel %d: %d vertices ...", pid, count)

# Final summary
log.info("DONE  obj=%s  gltf=%s  pdf=%s  json=%s", ...)
```

### Test Organization Convention
**Source:** `roof_pipeline/panel_snap_v2/tests/test_schema.py` (lines 1-8), `test_graph.py` (lines 1-12)
**Apply to:** All test files in `roof_pipeline/api/tests/`
```python
"""Tests for [component] ([requirement IDs])."""

from __future__ import annotations

import pytest

from roof_pipeline.module import ClassName


class TestDescriptiveName:
    """REQ-ID: Brief description of what this test class covers."""

    def test_specific_behavior(self):
        """Concrete description of the specific behavior under test."""
        # arrange
        # act
        # assert
```

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `roof_pipeline/api/middleware.py` | middleware | request-response | No HTTP middleware exists in the project. This is an entirely new concern. Use RESEARCH.md Pattern 4 (structured logging middleware) as the template. |
| `roof_pipeline/api/labels.py` | controller | CRUD | No Supabase CRUD endpoints exist. This is a stub endpoint (D-07: table schema deferred to Phase 5). Use RESEARCH.md code examples for Supabase table operations. |
| `roof_pipeline/api/deps.py` | provider | request-response | No FastAPI dependency injection exists. Use RESEARCH.md Pattern 2 (lru_cache + Depends). Must still follow project conventions for imports and logging. |

## Metadata

**Analog search scope:** `roof_pipeline/` (all 13 modules + `panel_snap_v2/` subpackage with 7 modules + `tests/` with 9 test files)
**Files scanned:** 29 source files + 9 test files
**Pattern extraction date:** 2026-04-19
