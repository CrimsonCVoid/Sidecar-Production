---
phase: 03-bug-fixes
verified: 2026-04-19T05:44:17Z
status: human_needed
score: 3/3 must-haves verified (automated)
overrides_applied: 0
must_haves:
  truths:
    - "Running run_real.py --snap-v2 on the 12-panel hip-and-valley roof (fb7e705c) completes without error -- panel 8 passes through densify and Shapely validation without area-change rejection"
    - "A golden-file regression test for the 12-panel hip-and-valley roof exists and passes in the test suite, confirming the densify fix does not regress"
    - "A mask.json file containing duplicate last corners is loaded via polygons_from_clicks and produces the same polygon as the deduplicated version -- no error, no extra zero-length edges"
  artifacts:
    - path: "roof_pipeline/panel_snap_v2/schema.py"
      provides: "close-polygon dedup field_validator on PanelCorners.corners_pix"
    - path: "roof_pipeline/panel_snap_v2/tests/test_schema.py"
      provides: "Tests for duplicate-corner dedup behavior"
    - path: "roof_pipeline/panel_snap_v2/densify.py"
      provides: "Fixed edge-walking densification with source_snapshot pattern"
    - path: "roof_pipeline/panel_snap_v2/tests/test_densify_regression.py"
      provides: "Regression test for 12-panel hip-and-valley roof densify"
    - path: ".planning/phases/03-bug-fixes/panel8_diagnostic.log"
      provides: "Captured diagnostic output from investigation run"
  key_links:
    - from: "roof_pipeline/panel_snap_v2/schema.py"
      to: "roof_pipeline/boundaries.py"
      via: "PanelsInput.model_validate() in polygons_from_clicks()"
    - from: "roof_pipeline/panel_snap_v2/densify.py"
      to: "roof_pipeline/panel_snap_v2/__init__.py"
      via: "densify_edges() called from snap_polygons()"
    - from: "roof_pipeline/panel_snap_v2/tests/test_densify_regression.py"
      to: "roof_pipeline/panel_snap_v2/densify.py"
      via: "imports densify_edges and exercises it with real-data constants"
human_verification:
  - test: "Run run_real.py --snap-v2 on the fb7e705c 12-panel hip-and-valley roof with the real DSM .tif"
    expected: "Pipeline completes without RuntimeError. Panel 8 passes through densify and Shapely validation. No area-change rejection."
    why_human: "The regression test uses synthetic tilted planes, not the real DSM. The mutation-chain fix is verified, but the full end-to-end run with real DSM planes is needed to confirm the exact 65.9% area-loss scenario is resolved. Requires the DSM .tif file only available on the dev machine."
---

# Phase 3: Bug Fixes Verification Report

**Phase Goal:** The snap engine handles complex hip-and-valley roofs without area-loss rejection, and legacy mask.json files with duplicate corners are silently cleaned during ingestion
**Verified:** 2026-04-19T05:44:17Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running run_real.py --snap-v2 on the 12-panel hip-and-valley roof (fb7e705c) completes without error | VERIFIED (code) / ? HUMAN NEEDED (end-to-end) | The source_snapshot fix in densify.py breaks the mutation chain (line 96). Regression test confirms panel 8 survives densify with 0 vertex growth. But the full pipeline with real DSM planes has not been re-run -- the regression test uses synthetic tilted planes. |
| 2 | A golden-file regression test for the 12-panel hip-and-valley roof exists and passes in the test suite | VERIFIED | `test_densify_regression.py` exists with 3 tests (panel 8 no rejection, all 12 survive, multi-neighbor no mutation chain). All 3 pass. Uses inline constants per D-10, not golden-file comparison -- plan chose assertion-based verification over file diffing. |
| 3 | A mask.json with duplicate last corners is loaded via polygons_from_clicks and produces the same polygon as the deduplicated version | VERIFIED | `strip_close_polygon_duplicate` validator in schema.py (line 26-45). PanelsInput.model_validate called in boundaries.py line 77. 5 dedicated dedup tests pass. Spot-check confirms 4-corner input with duplicate last -> 3 corners. |

**Score:** 3/3 truths verified (automated checks). 1 item requires human end-to-end confirmation.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `roof_pipeline/panel_snap_v2/schema.py` | close-polygon dedup field_validator | VERIFIED | Contains `strip_close_polygon_duplicate` (line 26), 0.5px tolerance (line 39), `log.debug` (line 40), `return v[:-1]` (line 44). Ordered BEFORE `at_least_three_corners` (line 47). 65 lines, substantive. |
| `roof_pipeline/panel_snap_v2/tests/test_schema.py` | Tests for dedup behavior | VERIFIED | Contains `TestDuplicateCornerDedup` class (line 75) with 5 tests: duplicate stripped, near-duplicate stripped, no false positive, dedup + count check, full PanelsInput path. 146 lines, substantive. |
| `roof_pipeline/panel_snap_v2/densify.py` | Fixed densify with source_snapshot | VERIFIED | Contains `source_snapshot` dict (line 96) and `source_poly = source_snapshot[source_pid]` (line 123). API signature unchanged: `def densify_edges(polygons, planes, graph, tol=1.0)` (line 60). Also has D-05 diagnostic logging (lines 113-201). 212 lines, substantive. |
| `roof_pipeline/panel_snap_v2/tests/test_densify_regression.py` | Regression test with inline constants | VERIFIED | Contains `TestFb7e705cRegression` (line 69) with 3 tests. Inline polygon arrays for all 12 panels (lines 33-48) and 12 Plane objects (lines 51-66). No runtime file paths (D-10 satisfied -- the docstring reference to Downloads/ is documentation only, no `open()` or `Path()` calls). 139 lines, substantive. |
| `.planning/phases/03-bug-fixes/panel8_diagnostic.log` | Diagnostic output with before/after | VERIFIED | Contains PRE-FIX section (root cause analysis, lines 1-96) and POST-FIX section (verification results, lines 97-112). Shows `panel_a=` log lines for all 11 graph edges. 112 lines. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `schema.py` | `boundaries.py` | `PanelsInput.model_validate()` | WIRED | boundaries.py line 77: `validated = PanelsInput.model_validate(raw)`. Dedup fires before `polygons_from_clicks` processes corners. |
| `densify.py` | `__init__.py` | `densify_edges()` call | WIRED | __init__.py line 115: `out = densify_edges(out, planes, graph, tol=tol)`. Source_snapshot fix active for all snap_polygons calls. |
| `test_densify_regression.py` | `densify.py` | import + exercise | WIRED | Line 23: `from roof_pipeline.panel_snap_v2.densify import densify_edges`. All 3 tests call `densify_edges()` with inline fb7e705c data. |

### Data-Flow Trace (Level 4)

Not applicable -- modified artifacts are a Pydantic schema validator, an algorithm module, and test files. No dynamic-data rendering components.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Dedup validator strips duplicate last corner | `PanelCorners(id=1, corners_pix=[[0,0],[1,0],[0.5,1],[0,0]])` -- check len == 3 | 3 corners, duplicate stripped | PASS |
| Non-duplicate corner preserved | `PanelCorners(id=1, corners_pix=[[0,0],[1,0],[0.5,1],[0.5,0]])` -- check len == 4 | 4 corners, all preserved | PASS |
| Panel 8 survives densify | `densify_edges()` on fb7e705c data -- check panel 8 in output, vertex growth == 0 | Panel 8: 5->5 vertices, 0 growth | PASS |
| All 12 panels survive | Same call -- check all pids in result | All 12 present | PASS |
| Diagnostic logging at DEBUG | `LOG_LEVEL=DEBUG` -- check for `panel_a=` log lines | `densify edge panel_a=1 panel_b=2 candidates_considered=60...` visible | PASS |
| Schema tests pass | `pytest test_schema.py` | 13/13 passed | PASS |
| Regression tests pass | `pytest test_densify_regression.py` | 3/3 passed | PASS |
| Full test suite passes | `pytest panel_snap_v2/tests/` | 49/49 passed | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| FIX-01 | 03-02 | Fix densify make_valid MultiPolygon 65.9% area loss on fb7e705c panel 8 | SATISFIED | source_snapshot pattern in densify.py breaks mutation chain. Panel 8 vertex growth = 0 after fix. |
| FIX-02 | 03-02 | Golden-file regression test for 12-panel hip-and-valley roof | SATISFIED | test_densify_regression.py with 3 inline-constant tests (assertion-based, not golden-file diffing -- plan chose this approach per D-10). |
| LABEL-01 | 03-01 | Silent duplicate-corner removal protecting legacy mask.json | SATISFIED | strip_close_polygon_duplicate in schema.py with 0.5px tolerance, DEBUG-only logging. 5 tests confirm behavior. |

No orphaned requirements -- REQUIREMENTS.md maps exactly FIX-01, FIX-02, LABEL-01 to Phase 3, and all three appear in plan frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | No TODO, FIXME, placeholder, stub, or empty implementation patterns found in any modified file. |

### Human Verification Required

### 1. End-to-end run_real.py --snap-v2 on fb7e705c with real DSM

**Test:** Run `python -m roof_pipeline.run_real <fb7e705c.dsm.tif> <fb7e705c.mask.npy> --snap-v2` with the actual DSM GeoTIFF and labeled mask from the dev machine.
**Expected:** Pipeline completes without RuntimeError. All 12 panels survive. Panel 8 does not trigger the 65.9% area-loss rejection. Output mesh and PDFs are generated.
**Why human:** The regression test exercises `densify_edges` directly with synthetic tilted planes, not the full pipeline with real DSM-fitted planes. The SUMMARY documents this deviation: "full pipeline with synthetic planes hits unrelated area-change thresholds on panels 2-3 due to approximate plane geometry." The mutation-chain fix is verified at the algorithm level, but confirming it resolves the specific production failure requires the real DSM data available only on the dev machine.

### Gaps Summary

No gaps found. All three requirements (FIX-01, FIX-02, LABEL-01) have implementation evidence in the codebase. All artifacts exist, are substantive, and are wired. All 49 tests pass. No anti-patterns detected.

The single open item is human verification of the end-to-end pipeline run with real DSM data. The algorithmic fix (source_snapshot pattern) is sound and verified by regression tests, but the ROADMAP SC-1 specifically references "Running run_real.py --snap-v2" which needs the real DSM file.

---

_Verified: 2026-04-19T05:44:17Z_
_Verifier: Claude (gsd-verifier)_
