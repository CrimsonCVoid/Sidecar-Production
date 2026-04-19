# Architecture

**Analysis Date:** 2026-04-18

## Pattern Overview

**Overall:** Sequential pipeline (DSM raster -> 3D mesh -> PDF documents)

**Key Characteristics:**
- Pure data-transformation pipeline: each stage consumes the output of the previous stage
- No web framework, no database, no API server -- local CLI prototype
- Two execution modes: synthetic demo (`main.py`) and real-data (`run_real.py`)
- All geometry stays in-memory as NumPy arrays; final outputs are files on disk (OBJ, glTF, PDF, JSON)
- Designed for eventual port to a DigitalOcean API backend called by a Next.js frontend ("My Metal Roofer")

## Layers

**Data Input Layer:**
- Purpose: Produce or load the DSM elevation grid and panel segmentation mask
- Location: `roof_pipeline/synthetic.py`, `roof_pipeline/run_real.py`, `roof_pipeline/label_panels.py`
- Contains: Synthetic gable generator, GeoTIFF loader via rasterio, interactive matplotlib labeler
- Depends on: numpy, rasterio, matplotlib, scipy, skimage
- Used by: Pipeline orchestrators (`main.py`, `run_real.py`)

**Geometry Processing Layer:**
- Purpose: Transform raster inputs into clean 3D planar polygons
- Location: `roof_pipeline/planes.py`, `roof_pipeline/boundaries.py`, `roof_pipeline/snapping.py`
- Contains: SVD plane fitting, contour extraction + RDP simplification, edge/corner snapping (3D and 2D modes)
- Depends on: numpy, scipy (via SVD), OpenCV
- Used by: Pipeline orchestrators, mesh builder, output generators

**Mesh Construction Layer:**
- Purpose: Triangulate planar polygons and export 3D mesh files
- Location: `roof_pipeline/mesh.py`
- Contains: Earcut triangulation in local 2D plane frames, OBJ + glTF export via trimesh
- Depends on: numpy, mapbox_earcut, trimesh
- Used by: Cut-sheet generator (for 3D context inset), shop drawings (for plan views)

**Document Generation Layer:**
- Purpose: Produce dimensioned PDF output for fabrication and estimation
- Location: `roof_pipeline/cutsheets.py`, `roof_pipeline/ts_export.py`, `roof_pipeline/ts_render_pdf.py`, `roof_pipeline/shop_drawings.py`
- Contains: Multi-page cut-sheet PDFs (ReportLab + matplotlib), TS-compatible JSON exporter, shop drawings with panel layout / trim / cut lists
- Depends on: numpy, matplotlib, reportlab, trimesh (for mesh rendering)
- Used by: End users (PDF files), future TS frontend (JSON)

## Data Flow

**Synthetic Pipeline (`main.py` -- 8 stages):**

1. `synthetic.make_synthetic_gable()` -> `SyntheticRoof(dsm, mask, res_m)`
2. `planes.fit_all_panels(dsm, mask, res_m)` -> `dict[int, Plane]`
3. `boundaries.extract_panel_polygons(mask, dsm, res_m, planes)` -> `dict[int, ndarray(K,3)]`
4. `snapping.snap_shared_edges(polygons, tol)` -> `dict[int, ndarray(K,3)]` (mutated copies)
5. `mesh.build_roof_mesh(polygons, planes)` -> `trimesh.Trimesh` + `export_mesh()` -> OBJ/glTF
6. `cutsheets.write_cutsheets_pdf(polygons, planes, mesh, path)` -> PDF
7. `ts_export.write_ts_json(polygons, planes, mesh, path)` -> JSON
8. `ts_render_pdf.render_pdf_from_json(json_path, path)` -> PDF (validation mirror)

**Real-Data Pipeline (`run_real.py` -- adds shop drawings):**

1. Load DSM via `rasterio.open()`, load mask via `np.load()`
2. `planes.fit_all_panels(dsm, mask, res_m)` -> `dict[int, Plane]`
3. Branch: if `panels.json` sidecar exists, use `boundaries.polygons_from_clicks()` (exact corners); else fall back to `extract_panel_polygons()` (contour re-trace)
4. Branch: click path uses XY-mode snapping (`snap_shared_corners_xy` + `densify_shared_edges_xy`); contour path uses 3D `snap_shared_edges`
5. `mesh.build_roof_mesh()` + `export_mesh()`
6. `cutsheets.write_cutsheets_pdf()`
7. `ts_export.write_ts_json()` + `ts_render_pdf.render_pdf_from_json()`
8. `shop_drawings.roof_dict_from_pipeline()` -> roof dict -> `generate_shop_drawings()` -> 4-page fabrication PDF

**State Management:**
- No persistent state. All data flows through function arguments as NumPy arrays and dicts.
- The core data containers are `dict[int, Plane]` (plane fits keyed by panel ID) and `dict[int, np.ndarray]` (polygon vertices keyed by panel ID).
- `trimesh.Trimesh` is the mesh interchange format between mesh construction and rendering.

## Key Abstractions

**`Plane` dataclass:**
- Purpose: Represents a fitted plane for one roof panel (normal, centroid, RMS residual, offset d)
- Defined in: `roof_pipeline/planes.py` (line 13)
- Pattern: Immutable value object created by `fit_plane()`, consumed by every downstream stage
- Fields: `normal: ndarray(3,)`, `centroid: ndarray(3,)`, `rms_residual: float`, `d: float`

**`SyntheticRoof` dataclass:**
- Purpose: Bundles a DSM array, panel mask, and pixel resolution for the synthetic test case
- Defined in: `roof_pipeline/synthetic.py` (line 14)
- Pattern: Simple data holder returned by `make_synthetic_gable()`

**Panel polygon dict (`dict[int, np.ndarray]`):**
- Purpose: The primary interchange format -- maps panel ID to (K, 3) ordered boundary vertices
- Pattern: Created by `extract_panel_polygons()` or `polygons_from_clicks()`, mutated in-place by snapping, consumed by mesh builder and document generators
- Not a formal class -- raw dict of arrays passed through function signatures

**Roof dict (`dict`):**
- Purpose: Bridge between the geometry pipeline and shop drawings; contains panels with edges, sheets, and project metadata
- Created by: `shop_drawings.roof_dict_from_pipeline()` (line 1986)
- Pattern: Nested dict with keys `roof_panels`, `estimate_number`, `project_name`, `primary_slope`, etc. Each panel has `boundary_3d`, `edges` (typed/measured), `sheets` (layout), `plane_normal`

## Entry Points

**`roof_pipeline/main.py` (synthetic demo):**
- Location: `roof_pipeline/main.py`
- Triggers: `python -m roof_pipeline.main`
- Responsibilities: Run the full 8-stage pipeline on a synthetic 2-panel gable; outputs to `output/`

**`roof_pipeline/run_real.py` (real data):**
- Location: `roof_pipeline/run_real.py`
- Triggers: `python -m roof_pipeline.run_real path/to/dsm.tif path/to/mask.npy [--out-dir ...] [--snap-tol ...] [--project-name ...] ...`
- Responsibilities: Run the full pipeline on real GeoTIFF DSM + labeled mask; outputs to `output_real/`

**`roof_pipeline/label_panels.py` (interactive labeler):**
- Location: `roof_pipeline/label_panels.py`
- Triggers: `python -m roof_pipeline.label_panels path/to/dsm.tif [--out mask.npy]`
- Responsibilities: Interactive matplotlib GUI for clicking panel corners on a hillshade; saves `mask.npy` + `panels.json` sidecar

**`roof_pipeline/ts_render_pdf.py` (standalone renderer):**
- Location: `roof_pipeline/ts_render_pdf.py`
- Triggers: `python -m roof_pipeline.ts_render_pdf path/to/cutsheets.ts.json [--out ...]`
- Responsibilities: Render a PDF from the TS exporter JSON (validation tool)

**`roof_pipeline/shop_drawings.py` (standalone sample):**
- Location: `roof_pipeline/shop_drawings.py` (line 2084, `__main__` block)
- Triggers: `python -m roof_pipeline.shop_drawings`
- Responsibilities: Generate shop drawings from built-in `SAMPLE_ROOF` dict for development testing

## Error Handling

**Strategy:** Fail-fast with exceptions for invalid inputs; warn-and-skip for individual panels that can't be processed.

**Patterns:**
- `ValueError` raised on shape mismatches (e.g., `dsm.shape != mask.shape` in `planes.py` line 62)
- `RuntimeError` raised when earcut returns no triangles (`mesh.py` line 49) or no panels exist (`mesh.py` line 69)
- `log.warning()` + `continue` for panels with insufficient pixels/vertices (`planes.py` lines 70-78, `boundaries.py` lines 126-127, `shop_drawings.py` line 2042)
- No try/except wrapping at the pipeline level -- errors propagate to the CLI

## Cross-Cutting Concerns

**Logging:** Python `logging` module throughout; each module creates `log = logging.getLogger(__name__)`. Pipeline stages are numbered in log output (`=== stage N: ... ===`). Configured by `logging.basicConfig()` in each entry point.

**Validation:** Input validation at function boundaries (shape checks, minimum vertex counts). No schema validation library -- manual checks with `ValueError`.

**Coordinate Systems:**
- Raster: pixel (row, col) with origin top-left
- World: meters (x = col * res_m, y = row * res_m, z = dsm elevation)
- Drawing: feet-inches for user-facing dimensions; inches for TS JSON export
- All conversions use constants `M_TO_FT = 3.280839895`, `SQM_TO_SQFT = 10.7639104`, `M_TO_IN = 39.37007874`

**Unit Conversions:** Handled per-module at output boundaries. Internal geometry is always in meters.

---

*Architecture analysis: 2026-04-18*
