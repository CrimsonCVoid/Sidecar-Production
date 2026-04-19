# Codebase Concerns

**Analysis Date:** 2026-04-18

## Tech Debt

**Monolithic shop_drawings.py (2089 lines):**
- Issue: `roof_pipeline/shop_drawings.py` is a single 2089-line file containing all PDF rendering logic for 5 pages, label placement engine, scan-line panel layout, edge classification, sheet layout, sample data, and the pipeline-to-dict adapter. It is by far the largest file in the codebase (48% of all code).
- Files: `roof_pipeline/shop_drawings.py`
- Impact: Hard to navigate, test, or modify individual pages without risking regressions in others. The label placement engine alone (~200 lines, classes `_EdgeLabelSpec`, `_LabelPlacement`, `_place_edge_labels`) is complex enough to warrant its own module.
- Fix approach: Extract into subpackage `shop_drawings/` with separate modules: `page_layout.py`, `page_edge_trim.py`, `page_cut_list.py`, `page_combined.py`, `page_3d_views.py`, `label_engine.py`, `adapter.py`, `sample_data.py`.

**Hardcoded sample data at module level:**
- Issue: `SAMPLE_ROOF = _build_sample_roof()` executes at import time (line 1888), constructing a full sample roof dict with random number generation every time the module is imported, even in production. This wastes startup time and pollutes the module namespace.
- Files: `roof_pipeline/shop_drawings.py` (lines 1813-1888)
- Impact: Unnecessary computation on every import. The sample is only needed when running the module as `__main__`.
- Fix approach: Move `_build_sample_roof()` call inside the `if __name__ == "__main__"` block or into a separate `sample_data.py` module.

**Untyped roof dict as primary data contract:**
- Issue: The entire shop drawings system operates on a loosely-typed `dict` (`roof` parameter) with deeply nested keys like `roof["roof_panels"][i]["edges"][j]["type"]`. No dataclass, TypedDict, or schema validates this structure. The `roof_dict_from_pipeline()` adapter constructs it; every rendering function reads it with `.get()` and silent defaults.
- Files: `roof_pipeline/shop_drawings.py` (all `_render_page*` functions, `roof_dict_from_pipeline`, `_meta`)
- Impact: Silent failures when keys are missing or misspelled. Adding a new field requires hunting through all consumers. No IDE support for field names.
- Fix approach: Define a `RoofDrawingData` dataclass (or Pydantic model) with nested `RoofPanel`, `Edge`, `Sheet` types. Validate at the boundary in `roof_dict_from_pipeline()`.

**Duplicated conversion constants:**
- Issue: `M_TO_FT = 3.280839895` is defined in three places: `roof_pipeline/cutsheets.py` (line 36), `roof_pipeline/shop_drawings.py` (line 581 inside `_scan_line_sheets`), and `roof_pipeline/shop_drawings.py` (line 2001 inside `roof_dict_from_pipeline`). `SQM_TO_SQFT` is defined in `cutsheets.py` and imported elsewhere. `M_TO_IN = 39.37007874` is in `ts_export.py` (line 44).
- Files: `roof_pipeline/cutsheets.py`, `roof_pipeline/shop_drawings.py`, `roof_pipeline/ts_export.py`
- Impact: Risk of inconsistent values if one is updated and others are not.
- Fix approach: Create a `roof_pipeline/units.py` module exporting all conversion constants. Import from there everywhere.

**Duplicated math helpers across modules:**
- Issue: `rotation_to_horizontal()`, `polygon_area_2d()`, `slope_rise_over_12()`, `azimuth_degrees()`, `meters_to_ft_in()`, `interior_angle_deg()` live in `cutsheets.py` but are imported by `ts_export.py` and `shop_drawings.py`. These are general geometry utilities, not cut-sheet-specific.
- Files: `roof_pipeline/cutsheets.py` (lines 44-133), `roof_pipeline/ts_export.py` (lines 31-39), `roof_pipeline/shop_drawings.py` (line 29)
- Impact: The `cutsheets` module has become an implicit utility module. Importing "cutsheets" to get `polygon_area_2d` is confusing.
- Fix approach: Extract geometry and unit-conversion helpers into `roof_pipeline/geometry.py` or `roof_pipeline/math_utils.py`.

## Known Bugs

**Potential index mismatch in edge diagram rendering:**
- Symptoms: If `len(panel["edges"])` differs from `len(outline_pg)` (number of polygon vertices), the edge labels and polygon edges become misaligned. The code clips with `edges[:n]` (line 1238) which silently drops extra edges, and if there are fewer edges than vertices, some edges go unlabeled.
- Files: `roof_pipeline/shop_drawings.py` (line 1238: `for i, edge in enumerate(edges[:n])`)
- Trigger: Occurs when the degenerate-edge filter in `roof_dict_from_pipeline()` removes vertices but the edge list count doesn't match the cleaned boundary vertex count.
- Workaround: The current pipeline usually produces matched counts, but any manual editing of the roof dict could trigger this.

**`_polyline` skip logic in ts_render_pdf.py:**
- Symptoms: Line 49 `if i == 1 and i == n - 1` is always False when `n > 2` (both conditions can't be true simultaneously unless n=2 and i=1). For n=2, this skips the only closing edge, which is the documented intent. But the condition is confusing and brittle.
- Files: `roof_pipeline/ts_render_pdf.py` (line 49)
- Trigger: Only affects 2-point polylines (degenerate).
- Workaround: Works correctly in practice but the logic is unclear.

## Security Considerations

**No input validation on GeoTIFF files:**
- Risk: `rasterio.open()` processes arbitrary GeoTIFF files with no size limits or format validation. A maliciously crafted GeoTIFF could cause excessive memory allocation (e.g., declaring a 100,000 x 100,000 pixel grid).
- Files: `roof_pipeline/run_real.py` (line 34, `_load_dsm`), `roof_pipeline/label_panels.py` (line 341)
- Current mitigation: None. The pipeline assumes trusted input from Google Solar API.
- Recommendations: Add explicit size checks after reading DSM shape (e.g., reject if total pixels > 10M). Validate that `res_m` is within a reasonable range (0.01-1.0 m/px).

**No input validation on JSON sidecar files:**
- Risk: `polygons_from_clicks()` loads a JSON file and directly indexes into it without schema validation. Malformed JSON with unexpected types could cause cryptic errors.
- Files: `roof_pipeline/boundaries.py` (lines 72-73)
- Current mitigation: None.
- Recommendations: Add basic schema validation (check for required keys, validate types) or use a typed parser.

**Uncontrolled file writes:**
- Risk: Output paths are user-provided with no sanitization. Path traversal via `--out-dir ../../etc/` is possible in theory.
- Files: `roof_pipeline/run_real.py` (line 52), `roof_pipeline/main.py` (line 27)
- Current mitigation: The tool is CLI-only and assumes a trusted user.
- Recommendations: If this becomes a web service, validate and sandbox output paths.

## Performance Bottlenecks

**O(N^2) union-find vertex snapping:**
- Problem: `snap_shared_corners()` and `snap_shared_corners_xy()` compare every vertex pair across all panels with a naive O(N^2) loop.
- Files: `roof_pipeline/snapping.py` (lines 221-228 and 288-293)
- Cause: Brute-force pairwise distance check. For P panels with V vertices each, cost is O((P*V)^2).
- Improvement path: Use a spatial index (scipy.spatial.KDTree) to find neighbors within tolerance. Would reduce to O(N log N). Currently acceptable for typical roofs (tens of panels, 4-8 vertices each = ~50-100 total vertices), but would not scale to large commercial roofs.

**O(P^2 * E^2) edge snapping:**
- Problem: `snap_shared_edges()` compares every edge of every panel pair.
- Files: `roof_pipeline/snapping.py` (lines 430-462)
- Cause: Four `_point_to_segment_dist()` calls per edge pair comparison.
- Improvement path: Same as above -- spatial indexing on edge midpoints would dramatically reduce comparisons. The code even documents this: "O(P^2 * E^2) which is fine for tens of panels" (line 423).

**O(P * E * N) edge classification:**
- Problem: `_classify_panel_edges()` checks every edge against every edge of every other panel.
- Files: `roof_pipeline/shop_drawings.py` (lines 1895-1951)
- Cause: Nested loops with no spatial pruning.
- Improvement path: Pre-build an edge adjacency map during snapping and pass it downstream, avoiding redundant geometric queries.

**Matplotlib 3D rendering per panel for cut sheets:**
- Problem: Each panel generates two matplotlib figures (drawing + inset) saved as PNG then embedded in the PDF. For a 10-panel roof, that is 21 matplotlib figure creations.
- Files: `roof_pipeline/cutsheets.py` (lines 139-253)
- Cause: matplotlib figure creation and teardown is heavyweight.
- Improvement path: Draw directly with ReportLab vector primitives (like `shop_drawings.py` does) instead of rasterizing through matplotlib. This would also produce sharper PDFs.

**Module-level sample roof construction:**
- Problem: `_build_sample_roof()` runs at import time with `np.random.default_rng(42)` and array operations.
- Files: `roof_pipeline/shop_drawings.py` (line 1888)
- Cause: Module-level execution.
- Improvement path: Lazy-load or move to `__main__` guard.

## Fragile Areas

**Label placement engine:**
- Files: `roof_pipeline/shop_drawings.py` (lines 750-1057)
- Why fragile: The 6-tier fallback placement engine (inline -> shift -> shrink -> push -> leader -> marker) has deep nesting with O(labels * tiers * steps) brute-force collision checks. Each tier modifies placement state in-place, making it hard to reason about final state.
- Safe modification: Add unit tests with known polygon configurations before changing placement logic. Test edge cases: very small panels, many adjacent edges, all-colliding scenarios.
- Test coverage: Zero automated tests.

**Coordinate convention coupling:**
- Files: `roof_pipeline/ts_export.py` (lines 66-70), `roof_pipeline/ts_render_pdf.py` (lines 34-36)
- Why fragile: The TS export uses a specific coordinate mapping (`x -> -v_in, z -> u_in`) that must match the TS renderer's `pageX = z * scale + 300, pageY = -x * scale + 400` transform. Changing one without the other produces garbled output. The convention is documented in comments but not enforced programmatically.
- Safe modification: Extract the coordinate convention into a shared module with bidirectional conversion functions. Add round-trip tests.
- Test coverage: None.

**Panel face mask recovery via vertex ordering:**
- Files: `roof_pipeline/cutsheets.py` (lines 260-283)
- Why fragile: `_panel_face_masks()` relies on `trimesh.util.concatenate` preserving per-submesh vertex ordering. If trimesh changes this behavior in a future version, the face-to-panel mapping silently breaks.
- Safe modification: Store panel IDs in face metadata during `build_roof_mesh()` rather than recovering them post-hoc from vertex offsets.
- Test coverage: None.

## Scaling Limits

**Panel count:**
- Current capacity: Designed for residential roofs with 2-20 panels.
- Limit: The O(N^2) snapping algorithms and edge classification become noticeably slow beyond ~50 panels. The Page 2 Edge/Trim diagram paginates at 6 panels per page but the combined Page 4 view renders all panels on one page, becoming unreadable beyond ~15 panels.
- Scaling path: Implement spatial indexing for snapping. Add pagination or detail-on-demand for Page 4.

**PDF page layout:**
- Current capacity: Sheet cut list (Page 3) grid handles up to ~36 panels (6 per row, multiple rows). Beyond that, bars become too small to read.
- Limit: Large commercial roofs with 50+ panels and 200+ sheets would produce illegible cut lists.
- Scaling path: Add multi-page cut list support with configurable panels-per-page.

## Dependencies at Risk

**pygltflib listed but not imported:**
- Risk: `requirements.txt` includes `pygltflib>=1.16` but no source file imports it. Trimesh handles glTF export internally.
- Files: `requirements.txt` (line 10)
- Impact: Unnecessary dependency inflating install size.
- Migration plan: Remove from `requirements.txt` after confirming trimesh's glTF export works without it.

**Unpinned major versions:**
- Risk: All dependencies use `>=` minimum version constraints with no upper bound. A breaking change in any dependency (e.g., `trimesh>=4.0` to 5.0, `reportlab>=4.0` to 5.0) could silently break the pipeline.
- Files: `requirements.txt`
- Impact: Non-reproducible builds. CI/CD or fresh installs may pull incompatible versions.
- Migration plan: Pin to major version ranges (e.g., `trimesh>=4.0,<5.0`) or use a lockfile (`pip freeze > requirements.lock`).

## Missing Critical Features

**No automated tests:**
- Problem: The entire codebase (4368 lines across 13 files) has zero test files. No `tests/` directory, no `*_test.py` files, no `conftest.py`.
- Blocks: Safe refactoring, CI/CD integration, regression detection. Any change to snapping tolerances, coordinate transforms, or PDF layout could silently break output.

**No configuration system:**
- Problem: All defaults are hardcoded as function parameters or module-level constants. There is no config file, no environment variable support, no settings module.
- Files: `roof_pipeline/run_real.py` (CLI args with hardcoded defaults like `--coverage-in 24.0`, `--waste-pct 11.0`, `--profile SV`), `roof_pipeline/shop_drawings.py` (hardcoded fabricator name "INTEGRITY METALS", gauge "24 GA", material "GALVALUME")
- Blocks: Multi-tenant usage, different fabricator branding, regional unit preferences.

**No error recovery in pipeline stages:**
- Problem: The pipeline in `run_real.py` is a linear sequence of stages with no checkpointing, no partial output on failure, and no retry logic. If stage 5 (mesh build) fails after 30 seconds of processing, all prior work is lost.
- Files: `roof_pipeline/run_real.py` (lines 43-141), `roof_pipeline/main.py` (lines 20-56)
- Blocks: Reliability for production use. Users must re-run the entire pipeline from scratch on any failure.

**No input format detection or validation:**
- Problem: The pipeline assumes a very specific input format (GeoTIFF DSM + `.npy` mask + optional `.json` sidecar) with no validation of coordinate reference systems, bit depth, or data range.
- Files: `roof_pipeline/run_real.py` (lines 33-40, 74)
- Blocks: Handling diverse input sources (drone surveys, different satellite providers, different CRS).

## Test Coverage Gaps

**Entire codebase is untested:**
- What's not tested: Every function in every module. Critical untested paths include:
  - Plane fitting with noisy/degenerate data (`roof_pipeline/planes.py`)
  - Edge snapping with various tolerance values (`roof_pipeline/snapping.py`)
  - Polygon clipping edge cases in scan-line layout (`roof_pipeline/shop_drawings.py`)
  - PDF generation correctness (`roof_pipeline/cutsheets.py`, `roof_pipeline/shop_drawings.py`, `roof_pipeline/ts_render_pdf.py`)
  - Coordinate round-trip between ts_export and ts_render (`roof_pipeline/ts_export.py`, `roof_pipeline/ts_render_pdf.py`)
  - Edge type classification heuristics (`roof_pipeline/shop_drawings.py` lines 1895-1951)
  - Unit conversion helpers (`meters_to_ft_in`, `feet_to_ft_in`)
- Files: All 13 Python files
- Risk: Any refactoring or bug fix could introduce silent regressions in PDF output, mesh geometry, or dimensional accuracy. For a construction-industry tool where dimensional errors translate to material waste or structural issues, this is high-severity.
- Priority: High. Start with unit tests for math/geometry helpers and the coordinate pipeline, then add integration tests for end-to-end pipeline runs with synthetic data.

## Hardcoded Values

**Fabricator-specific defaults:**
- `"INTEGRITY METALS"` hardcoded as default fabricator name in `_meta()` (line 94)
- `"24 GA"` gauge, `"GALVALUME"` material, `"MILL FINISH"` finish color (lines 95-97)
- `"MRQ -- Material Requisition Quote (sample)"` footer text (line 559)
- Files: `roof_pipeline/shop_drawings.py`

**Layout magic numbers:**
- Page 1 drawing area: `draw_x0=50, draw_y0=220` (lines 367-368)
- Title block: `tb_w=320, tb_h=130` (lines 507-508)
- Legend width: `260.0` (line 461)
- North arrow position: `draw_x0 + 40, draw_y0 + draw_h - 50` (line 504)
- Label placement outward steps: `[22.0, 28.0, 34.0, 42.0]` (line 897)
- Files: `roof_pipeline/shop_drawings.py` (throughout)

**Pipeline defaults:**
- Snap tolerance: `tol=0.15` in `snap_shared_edges()` (line 407), `tol=1.0` in `snap_shared_corners()` (line 181)
- RDP epsilon: `rdp_epsilon_px=0.5` in `extract_panel_polygons()` (line 106)
- Building detection: `min_pixels=3000`, height threshold `1.5` m in `_building_bbox()` (lines 94, 75)
- Files: `roof_pipeline/snapping.py`, `roof_pipeline/boundaries.py`, `roof_pipeline/label_panels.py`

---

*Concerns audit: 2026-04-18*
