# Codebase Structure

**Analysis Date:** 2026-04-18

## Directory Layout

```
Mymetalrooferbackupmvp-firstcommit/
├── roof_pipeline/              # All source code (Python package)
│   ├── __init__.py             # Package marker + version
│   ├── main.py                 # Synthetic demo entry point
│   ├── run_real.py             # Real-data entry point (GeoTIFF + mask)
│   ├── label_panels.py         # Interactive panel labeler (matplotlib GUI)
│   ├── synthetic.py            # Synthetic gable DSM generator
│   ├── planes.py               # SVD plane fitting (Plane dataclass)
│   ├── boundaries.py           # Contour extraction + click-based polygons
│   ├── snapping.py             # Edge/corner snapping (3D and 2D modes)
│   ├── mesh.py                 # Earcut triangulation + OBJ/glTF export
│   ├── cutsheets.py            # Multi-page cut-sheet PDF (ReportLab + matplotlib)
│   ├── ts_export.py            # TS-compatible JSON exporter
│   ├── ts_render_pdf.py        # Python PDF renderer mirroring TS output
│   └── shop_drawings.py        # 4-page fabrication shop drawings PDF
├── data/                       # Real project data (not committed to git)
│   └── 301_indian_branch/      # Sample real-world dataset
├── requirements.txt            # Python dependencies
├── README.md                   # Project overview + usage
└── .gitignore                  # Git exclusions
```

## Directory Purposes

**`roof_pipeline/`:**
- Purpose: The entire application -- a single flat Python package
- Contains: 13 Python modules, no subdirectories
- Key files: `main.py` (demo driver), `run_real.py` (production driver), `planes.py` (core data type)

**`data/`:**
- Purpose: Real-world DSM tiles and labeled masks for testing
- Contains: Subdirectories per project/address (e.g., `301_indian_branch/`)
- Not committed to git (listed in `.gitignore` or untracked)

**`output/` (generated):**
- Purpose: Default output directory for synthetic pipeline
- Contains: `roof.obj`, `roof.gltf`, `cutsheets.pdf`, `cutsheets.ts.json`, `cutsheets.ts.pdf`
- Generated: Yes
- Committed: No

**`output_real/` (generated):**
- Purpose: Default output directory for real-data pipeline
- Contains: Same as `output/` plus `shop_drawings.pdf`
- Generated: Yes
- Committed: No

## Key File Locations

**Entry Points:**
- `roof_pipeline/main.py`: Synthetic demo -- `python -m roof_pipeline.main`
- `roof_pipeline/run_real.py`: Real data -- `python -m roof_pipeline.run_real <dsm.tif> <mask.npy>`
- `roof_pipeline/label_panels.py`: Labeler -- `python -m roof_pipeline.label_panels <dsm.tif>`
- `roof_pipeline/ts_render_pdf.py`: Standalone JSON-to-PDF -- `python -m roof_pipeline.ts_render_pdf <json>`
- `roof_pipeline/shop_drawings.py`: Standalone sample shop drawings -- `python -m roof_pipeline.shop_drawings`

**Configuration:**
- `requirements.txt`: Python package dependencies (10 packages)
- `.gitignore`: Git exclusions

**Core Data Types:**
- `roof_pipeline/planes.py`: `Plane` dataclass (the most important abstraction -- used by every downstream module)
- `roof_pipeline/synthetic.py`: `SyntheticRoof` dataclass

**Geometry Processing (pipeline stages 1-4):**
- `roof_pipeline/planes.py`: SVD plane fitting (`fit_plane`, `fit_all_panels`) -- 90 lines
- `roof_pipeline/boundaries.py`: Contour extraction + click-based polygons (`extract_panel_polygons`, `polygons_from_clicks`) -- 145 lines
- `roof_pipeline/snapping.py`: 3D and 2D edge/corner snapping (6 public functions) -- 465 lines
- `roof_pipeline/mesh.py`: Earcut triangulation + export (`build_roof_mesh`, `export_mesh`) -- 88 lines

**Document Generation (pipeline stages 5-8):**
- `roof_pipeline/cutsheets.py`: ReportLab + matplotlib cut-sheet PDF -- 392 lines
- `roof_pipeline/ts_export.py`: JSON exporter for TS frontend -- 273 lines
- `roof_pipeline/ts_render_pdf.py`: Python PDF renderer mirroring TS -- 178 lines
- `roof_pipeline/shop_drawings.py`: 4-page fabrication PDF (largest file) -- 2089 lines

## Naming Conventions

**Files:**
- `snake_case.py`: All module names use lowercase snake_case
- Modules named after their domain concept: `planes`, `boundaries`, `snapping`, `mesh`, `cutsheets`
- Prefix `ts_` for TypeScript-interop modules: `ts_export.py`, `ts_render_pdf.py`
- Entry points named for their run mode: `main.py`, `run_real.py`, `label_panels.py`

**Functions:**
- `snake_case`: All functions use lowercase snake_case
- Private helpers prefixed with underscore: `_bilinear_sample`, `_project_onto_plane`, `_render_panel_drawing_png`
- Public API functions have descriptive verb-noun names: `fit_all_panels`, `extract_panel_polygons`, `snap_shared_edges`, `build_roof_mesh`, `write_cutsheets_pdf`

**Classes:**
- `PascalCase`: `Plane`, `SyntheticRoof`, `PanelLabeler`
- Only 3 classes in the entire codebase; most logic is in standalone functions

## Where to Add New Code

**New pipeline stage:**
- Create a new module in `roof_pipeline/` named after the stage (e.g., `roof_pipeline/panel_colors.py`)
- Follow the pattern: module-level `log = logging.getLogger(__name__)`, public function taking `polygons` + `planes` dicts, returning transformed data
- Wire it into `roof_pipeline/main.py` and `roof_pipeline/run_real.py` at the appropriate stage position
- Import the `Plane` type from `roof_pipeline/planes.py` if needed

**New output format:**
- Add a new module in `roof_pipeline/` (e.g., `roof_pipeline/dxf_export.py`)
- Follow the `write_*` / `export_*` naming convention
- Accept `polygons: dict[int, np.ndarray]`, `planes: dict[int, Plane]`, and an output path
- Wire into orchestrators as a new numbered stage

**New snapping algorithm:**
- Add to `roof_pipeline/snapping.py` following the existing pattern of 3D vs 2D mode functions
- Match the signature `(polygons: dict[int, np.ndarray], ...) -> dict[int, np.ndarray]`
- Work on copies (`poly.copy()`) to avoid mutating inputs

**New cut-sheet page type:**
- Add rendering function to `roof_pipeline/cutsheets.py` following `_render_panel_drawing_png` pattern
- Add the flowable to `write_cutsheets_pdf()` in the appropriate position

**Utility/helper functions:**
- Math helpers (rotation, area, angle): add to `roof_pipeline/cutsheets.py` where existing helpers live
- Coordinate conversion helpers: add near the existing `M_TO_FT`, `SQM_TO_SQFT` constants in `roof_pipeline/cutsheets.py`
- Geometry helpers shared across modules: consider `roof_pipeline/planes.py` or a new `roof_pipeline/geometry.py`

## Special Directories

**`.venv/`:**
- Purpose: Python virtual environment
- Generated: Yes (by `python3 -m venv .venv`)
- Committed: No (in `.gitignore`)

**`data/`:**
- Purpose: Real-world input data (DSM tiles, masks, JSON sidecars)
- Generated: No (manually placed or downloaded)
- Committed: No (untracked)

**`output/` and `output_real/`:**
- Purpose: Pipeline output artifacts
- Generated: Yes (created by pipeline runs)
- Committed: No

## File Size Distribution

The codebase is compact (4,368 lines total across 13 Python files):
- `shop_drawings.py` dominates at 2,089 lines (48% of codebase) -- complex multi-page PDF rendering
- `snapping.py` is the second largest at 465 lines -- multiple snapping modes with detailed algorithms
- `cutsheets.py` at 392 lines -- matplotlib rendering + ReportLab PDF assembly
- Most modules are 80-180 lines -- focused single-responsibility

---

*Structure analysis: 2026-04-18*
