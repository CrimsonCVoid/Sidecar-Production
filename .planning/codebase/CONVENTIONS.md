# Coding Conventions

**Analysis Date:** 2026-04-18

## Naming Patterns

**Files:**
- Use `snake_case.py` for all module files
- Single-word or two-word names describing the module's domain: `boundaries.py`, `shop_drawings.py`, `label_panels.py`
- Entry-point scripts prefixed with `run_`: `run_real.py`
- Export/render modules use prefixed names: `ts_export.py`, `ts_render_pdf.py`

**Functions:**
- Use `snake_case` for all functions
- Public functions use verb-noun style: `fit_plane()`, `build_roof_mesh()`, `export_mesh()`, `write_cutsheets_pdf()`
- Private/internal helper functions prefixed with underscore: `_bilinear_sample()`, `_plane_basis()`, `_triangulate_polygon()`, `_z_on_plane()`, `_render_panel_drawing_png()`
- Constructor-like functions use `make_` prefix: `make_synthetic_gable()`

**Variables:**
- Use `snake_case` for all variables
- Short math-style names acceptable in numerical code: `u`, `v`, `n`, `d`, `fx`, `fy`, `z_hat`, `vt`
- Panel ID consistently named `pid` throughout the codebase
- Polygon vertices consistently named `verts_3d`, `verts_rot`, `verts_xy_m`, `verts_xy_ft`
- NumPy arrays use descriptive suffixes for units: `xs_m`, `ys_m`, `zs_m`, `uv_in` (inches), `verts_xy_ft`

**Types/Classes:**
- Use `PascalCase` for classes and dataclasses: `Plane`, `SyntheticRoof`, `PanelLabeler`
- Dataclasses preferred over plain classes for value types

**Constants:**
- Use `UPPER_SNAKE_CASE`: `M_TO_FT`, `SQM_TO_SQFT`, `M_TO_IN`, `PAGE_W`, `PAGE_H`, `SCALE`, `FONT`, `ANSI_B_PORTRAIT`
- Module-level constants defined at top of file after imports
- Color palettes as module-level lists: `_PANEL_COLORS`, `PANEL_PALETTE`

## Code Style

**Formatting:**
- No auto-formatter configured (no `.prettierrc`, `pyproject.toml` [tool.black], or similar)
- Consistent 4-space indentation throughout
- Line length generally under 100 characters; some log lines stretch longer
- Trailing commas used in multi-line function calls and dict literals

**Linting:**
- No linter configuration detected (no `.flake8`, `ruff.toml`, etc.)
- Code is clean and consistent despite no enforced linting
- One `# noqa: F401` suppression in `roof_pipeline/ts_render_pdf.py` line 24

**Type Hints:**
- Use `from __future__ import annotations` in every module for PEP 604 union syntax
- All public function signatures are fully type-annotated
- Private helpers have type annotations on parameters and return types
- Use `str | Path` for path parameters (accepting both types)
- Use `dict[int, np.ndarray]` for the core polygons data structure throughout
- Use `dict[int, Plane]` for the planes data structure throughout
- Return type annotations present on all functions

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first, in every module)
2. Standard library imports (`logging`, `math`, `json`, `tempfile`, `argparse`, `dataclasses`)
3. Third-party imports (`numpy`, `cv2`, `trimesh`, `matplotlib`, `reportlab`, `rasterio`)
4. Relative intra-package imports (`from .planes import Plane`, `from .cutsheets import ...`)

**Path Aliases:**
- None used; all imports are relative within the package

**Specific Patterns:**
- `matplotlib.use("Agg")` called immediately after `import matplotlib` and before `import matplotlib.pyplot` in `roof_pipeline/cutsheets.py` line 13
- Logging always imported as `import logging` with per-module logger: `log = logging.getLogger(__name__)`

## Error Handling

**Patterns:**
- Use `ValueError` for invalid input shapes or mismatched dimensions:
  - `roof_pipeline/planes.py` line 29: `raise ValueError(f"need (N>=3, 3) points, got {points_xyz.shape}")`
  - `roof_pipeline/planes.py` line 62: `raise ValueError(f"dsm {dsm.shape} != mask {mask.shape}")`
  - `roof_pipeline/run_real.py` line 76: `raise ValueError(f"mask shape {mask.shape} != dsm shape {dsm.shape}")`
- Use `RuntimeError` for algorithmic failures:
  - `roof_pipeline/mesh.py` line 49: `raise RuntimeError(f"earcut returned no triangles for polygon shape {uv.shape}")`
  - `roof_pipeline/mesh.py` line 69: `raise RuntimeError("no panels to mesh")`
- Use `log.warning()` for recoverable skip conditions (panel has too few pixels, missing plane fit, too few corners) -- do NOT raise, just skip and continue
- Bare `except Exception: pass` used once in `roof_pipeline/cutsheets.py` line 228 for optional `set_box_aspect` call
- No custom exception classes defined
- No try/except wrapping around file I/O operations

**Validation Style:**
- Validate early at function entry (shape checks, minimum point counts)
- Skip invalid items in loops with `log.warning()` and `continue`
- NaN handling explicit: filter NaN pixels before plane fitting (`roof_pipeline/planes.py` line 74)

## Logging

**Framework:** Python `logging` module

**Patterns:**
- Every module creates a module-level logger: `log = logging.getLogger(__name__)`
- Exception: `roof_pipeline/main.py` uses `logging.getLogger("roof_pipeline")` and `roof_pipeline/run_real.py` uses `logging.getLogger("roof_pipeline.real")`
- Pipeline stages logged as `log.info("=== stage N: description ===")` in driver modules
- Per-item progress logged as `log.info("panel %d: %d vertices ...", pid, count)`
- Warnings for skipped items: `log.warning("panel %d has %d pixels, skipping", pid, count)`
- Final summary logged with all output paths: `log.info("DONE  obj=%s  gltf=%s  pdf=%s ...", ...)`
- Logging configured in entry points only (`main.py`, `run_real.py`, `label_panels.py`) with format `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"`

## Comments

**When to Comment:**
- Module-level docstrings on every file explaining purpose and context
- Function-level docstrings on all public functions and most private helpers
- Inline comments for non-obvious math or algorithmic decisions
- Section dividers using `# ---------------------------------------------------------------------------` blocks in larger modules

**Docstring Style:**
- Triple-quoted, imperative mood: `"""Fit a plane to (N, 3) points using centered SVD."""`
- Multi-line docstrings include explanation of algorithm, math rationale, or pipeline context
- Parameter descriptions embedded in prose, not in structured `:param:` format
- No RST/NumPy/Google docstring format enforced -- freeform explanatory style

**Inline Comments:**
- Used liberally to explain mathematical formulas and geometric reasoning
- Algorithm complexity notes: `# Complexity is O(P^2 * E^2) which is fine for tens of panels` (`roof_pipeline/snapping.py` line 423)
- Decision rationale: `# Orient so normal points up (positive z)` (`roof_pipeline/planes.py` line 41)

## Function Design

**Size:**
- Functions range from 5-50 lines typically
- Largest functions are the PDF rendering entry points (~90 lines in `write_cutsheets_pdf`)
- Helper functions extracted aggressively for reuse and clarity

**Parameters:**
- Core data passed as `dict[int, np.ndarray]` (polygons) and `dict[int, Plane]` (planes)
- Tolerance parameters have sensible defaults: `tol=0.15`, `rdp_epsilon_px=0.5`
- Output paths accept `str | Path` and are immediately converted: `out_path = Path(out_path)`
- Output directories created with `mkdir(parents=True, exist_ok=True)` inside the function

**Return Values:**
- Functions return concrete types, not None (except void functions returning `None`)
- Path-returning functions return `Path` objects
- Mesh export returns `dict[str, Path]` with named outputs
- Data-processing functions return the same type as input (`dict[int, np.ndarray]`)

## Module Design

**Exports:**
- No `__all__` defined in any module
- `roof_pipeline/__init__.py` contains only `__version__`
- Each module exposes 1-3 public functions; private helpers prefixed with `_`
- Cross-module imports use specific names, not wildcard

**Barrel Files:**
- Not used; each module imported directly by consumers

**Data Flow Pattern:**
- Core data types threaded through the pipeline: `(polygons: dict[int, np.ndarray], planes: dict[int, Plane])`
- Functions are pure transforms: take data in, return new data out
- No global mutable state; all state is local or passed as parameters
- Copy-on-write in snapping: `out = {pid: poly.copy() for pid, poly in polygons.items()}`

---

*Convention analysis: 2026-04-18*
