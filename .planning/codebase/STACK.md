# Technology Stack

**Analysis Date:** 2026-04-18

## Languages

**Primary:**
- Python 3.11+ - All source code (`roof_pipeline/*.py`, 13 modules)

**Secondary:**
- None

## Runtime

**Environment:**
- CPython 3.11 (explicit in README setup instructions)
- macOS development target (README references Mac; planned DigitalOcean deployment)

**Package Manager:**
- pip
- Lockfile: missing (only `requirements.txt` with minimum version pins, no `requirements.lock` or `pip-compile` output)

## Frameworks

**Core:**
- No web framework - this is a CLI/library pipeline, not a server
- NumPy >= 1.26 - Core numerical computing, array operations throughout every module
- OpenCV (opencv-python >= 4.9) - Contour extraction and polygon simplification (`roof_pipeline/boundaries.py`)
- trimesh >= 4.0 - 3D mesh construction, concatenation, OBJ/glTF export (`roof_pipeline/mesh.py`)

**PDF Generation:**
- ReportLab >= 4.0 - Multi-page PDF creation for cut sheets and shop drawings (`roof_pipeline/cutsheets.py`, `roof_pipeline/ts_render_pdf.py`, `roof_pipeline/shop_drawings.py`)
- matplotlib >= 3.8 - Dimensioned panel drawings, 3D inset views, hillshade rendering for labeler (`roof_pipeline/cutsheets.py`, `roof_pipeline/label_panels.py`)

**Testing:**
- Not detected - no test framework configured, no test files present

**Build/Dev:**
- No build tools (pure Python, no compilation step)
- No `setup.py`, `pyproject.toml`, or `setup.cfg` - package is run as `python -m roof_pipeline.main`

## Key Dependencies

**Critical (core pipeline):**
- `numpy >= 1.26` - Array math, SVD plane fitting, coordinate transforms. Used in every module.
- `scipy >= 1.11` - Morphological operations for building detection in labeler (`roof_pipeline/label_panels.py`: `binary_closing`, `binary_opening`, `label`)
- `opencv-python >= 4.9` - `findContours`, `approxPolyDP` for boundary extraction (`roof_pipeline/boundaries.py`)
- `trimesh >= 4.0` - Mesh construction (`Trimesh`), concatenation (`trimesh.util.concatenate`), export to OBJ/glTF (`roof_pipeline/mesh.py`)
- `mapbox-earcut >= 1.0` - Polygon triangulation via earcut algorithm (`roof_pipeline/mesh.py`)
- `reportlab >= 4.0` - PDF generation for cut sheets, TS-render validation PDFs, and shop drawings (`roof_pipeline/cutsheets.py`, `roof_pipeline/ts_render_pdf.py`, `roof_pipeline/shop_drawings.py`)

**Geospatial (real-data path):**
- `rasterio >= 1.3` - GeoTIFF DSM loading (`roof_pipeline/run_real.py`, `roof_pipeline/label_panels.py`)

**Visualization:**
- `matplotlib >= 3.8` - Panel drawing PNGs embedded in PDFs, hillshade rendering, interactive labeler GUI (`roof_pipeline/cutsheets.py`, `roof_pipeline/label_panels.py`)
- `scikit-image >= 0.22` - `skimage.draw.polygon` for rasterizing clicked polygons to mask (`roof_pipeline/label_panels.py`)

**Mesh export support:**
- `pygltflib >= 1.16` - glTF export support (used indirectly via trimesh's glTF exporter)

## Configuration

**Environment:**
- No `.env` file detected
- No environment variables required
- All configuration via CLI arguments (`--out-dir`, `--snap-tol`, `--project-name`, etc. in `roof_pipeline/run_real.py`)

**Build:**
- No build configuration - pure Python package
- `requirements.txt` at project root for dependency installation

## Platform Requirements

**Development:**
- Python 3.11+
- macOS (primary dev target per README)
- GDAL/rasterio C libraries required for GeoTIFF support (rasterio dependency)
- matplotlib GUI backend required for `label_panels.py` (interactive labeler)

**Production:**
- Planned: DigitalOcean API backend (per README: "porting to a DigitalOcean API backend that the Next.js frontend (My Metal Roofer) will call")
- matplotlib Agg backend for headless PDF rendering (`cutsheets.py` sets `matplotlib.use("Agg")`)
- No server framework currently implemented

## Entry Points

**CLI commands:**
- `python -m roof_pipeline.main` - Synthetic demo pipeline (`roof_pipeline/main.py`)
- `python -m roof_pipeline.run_real <dsm.tif> <mask.npy>` - Real data pipeline (`roof_pipeline/run_real.py`)
- `python -m roof_pipeline.label_panels <dsm.tif>` - Interactive panel labeler GUI (`roof_pipeline/label_panels.py`)
- `python -m roof_pipeline.ts_render_pdf <json>` - Re-render PDF from JSON (`roof_pipeline/ts_render_pdf.py`)

## Version

- Package version: `0.1.0` (defined in `roof_pipeline/__init__.py`)

---

*Stack analysis: 2026-04-18*
