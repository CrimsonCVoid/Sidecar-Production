# Testing Patterns

**Analysis Date:** 2026-04-18

## Test Framework

**Runner:**
- No test framework configured
- No `pytest`, `unittest`, or other test runner in `requirements.txt`
- No test configuration files (`pytest.ini`, `setup.cfg [tool:pytest]`, `pyproject.toml [tool.pytest]`, `tox.ini`)

**Assertion Library:**
- Not applicable (no tests exist)

**Run Commands:**
```bash
# No test commands available -- none configured
```

## Test File Organization

**Location:**
- No test files exist anywhere in the project
- No `tests/` directory
- No `test_*.py` or `*_test.py` files within `roof_pipeline/`

**Naming:**
- Not established

**Structure:**
```
# No test directory structure exists
roof_pipeline/       # source only, no co-located tests
```

## Test Structure

**No tests exist.** The codebase has zero automated test coverage.

## Mocking

**Framework:** Not applicable

**What WOULD need mocking (for future tests):**
- `rasterio.open()` for DSM file loading in `roof_pipeline/run_real.py` and `roof_pipeline/label_panels.py`
- `matplotlib.pyplot` for headless rendering tests in `roof_pipeline/cutsheets.py`
- File system I/O for PDF/OBJ/glTF output validation
- The interactive matplotlib event loop in `roof_pipeline/label_panels.py`

## Fixtures and Factories

**Test Data:**
- `roof_pipeline/synthetic.py` provides `make_synthetic_gable()` which generates a deterministic synthetic DSM + mask
- This is the closest thing to a test fixture: it creates known-geometry input with a fixed `seed=0`
- The `SyntheticRoof` dataclass bundles `dsm`, `mask`, and `res_m` -- a complete pipeline input

**Existing synthetic data factory:**
```python
# roof_pipeline/synthetic.py -- usable as test fixture
from roof_pipeline.synthetic import make_synthetic_gable

roof = make_synthetic_gable(
    width_px=400, height_px=300, res_m=0.05,
    pitch=6.0/12.0, eave_height=2.5,
    noise_std=0.01, seed=0,
)
# roof.dsm: (300, 400) float32 array
# roof.mask: (300, 400) uint8 array with panels 1 and 2
# roof.res_m: 0.05
```

**Location:**
- No dedicated fixtures directory

## Coverage

**Requirements:** None enforced
**Current coverage:** 0% -- no tests exist

## Test Types

**Unit Tests:**
- Not present. Candidates for unit testing:
  - `roof_pipeline/planes.py`: `fit_plane()` -- pure math, easy to test with known geometry
  - `roof_pipeline/snapping.py`: `_point_to_segment_dist()`, `_edges_match()` -- pure geometry helpers
  - `roof_pipeline/cutsheets.py`: `rotation_to_horizontal()`, `polygon_area_2d()`, `slope_rise_over_12()`, `meters_to_ft_in()`, `interior_angle_deg()` -- pure math utility functions
  - `roof_pipeline/mesh.py`: `_plane_basis()` -- orthonormal basis construction
  - `roof_pipeline/boundaries.py`: `_bilinear_sample()`, `_project_onto_plane()` -- pure NumPy operations

**Integration Tests:**
- Not present. The `roof_pipeline/main.py` `run()` function exercises the full synthetic pipeline end-to-end and could serve as the basis for an integration test (it runs all 8 stages on synthetic data with no external dependencies)

**E2E Tests:**
- Not present
- `roof_pipeline/run_real.py` requires real GeoTIFF files and a labeled mask, making true E2E testing dependent on sample data files

## Testability Assessment

**Highly testable modules (pure functions, no I/O):**
- `roof_pipeline/planes.py` -- `fit_plane()` and `fit_all_panels()` are pure NumPy math
- `roof_pipeline/snapping.py` -- all snapping functions take and return `dict[int, np.ndarray]`
- `roof_pipeline/mesh.py` -- `_plane_basis()` and `_triangulate_polygon()` are pure geometry
- `roof_pipeline/boundaries.py` -- `_bilinear_sample()` and `_project_onto_plane()` are pure NumPy
- `roof_pipeline/cutsheets.py` math helpers -- `rotation_to_horizontal()`, `polygon_area_2d()`, `slope_rise_over_12()`, `meters_to_ft_in()`, `interior_angle_deg()`
- `roof_pipeline/synthetic.py` -- deterministic with `seed` parameter, produces known geometry

**Harder to test (I/O or GUI):**
- `roof_pipeline/cutsheets.py` `write_cutsheets_pdf()` -- requires matplotlib + ReportLab, writes PDF files, uses temp directories
- `roof_pipeline/ts_render_pdf.py` `render_pdf_from_json()` -- reads JSON, writes PDF via ReportLab
- `roof_pipeline/label_panels.py` `PanelLabeler` -- interactive matplotlib GUI with mouse/keyboard events
- `roof_pipeline/shop_drawings.py` `generate_shop_drawings()` -- large PDF generation function

**Recommended test strategy for new tests:**
1. Add `pytest` to `requirements.txt`
2. Create `tests/` directory at project root
3. Start with `tests/test_planes.py` -- test `fit_plane()` with a known planar point cloud
4. Add `tests/test_snapping.py` -- test edge matching and corner snapping with simple 2-panel geometries
5. Add `tests/test_math_helpers.py` -- test `meters_to_ft_in()`, `polygon_area_2d()`, `slope_rise_over_12()` with known values
6. Add `tests/test_pipeline.py` -- run `make_synthetic_gable()` through the full pipeline and assert output files exist and mesh has expected face/vertex counts

## Common Anti-Patterns to Avoid

**When adding tests:**
- Do NOT mock NumPy operations -- test the actual math
- Use `make_synthetic_gable()` from `roof_pipeline/synthetic.py` as the standard integration test fixture
- Use `tmp_path` pytest fixture for any file-writing tests (PDF, OBJ, glTF output)
- For PDF tests, assert file exists and has nonzero size rather than pixel-diffing

## Validation Currently Done at Runtime

The codebase validates inputs at runtime (acting as a partial substitute for tests):
- Shape validation: `roof_pipeline/planes.py` lines 29, 62
- NaN filtering: `roof_pipeline/planes.py` lines 74-78
- Minimum vertex counts: `roof_pipeline/boundaries.py` lines 82-84, `roof_pipeline/planes.py` lines 69-70
- Mask/DSM shape match: `roof_pipeline/run_real.py` line 76
- Earcut triangle output validation: `roof_pipeline/mesh.py` line 48-49

---

*Testing analysis: 2026-04-18*
