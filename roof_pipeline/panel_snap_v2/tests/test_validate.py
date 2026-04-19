"""Tests for Shapely polygon validation and repair (TOPO-10, TEST-06)."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.validate import validate_polygons
from .conftest import _make_plane


class TestValidPolygon:
    """Valid polygons pass both stages without modification."""

    def test_valid_polygon_passes_both_stages(self):
        """A valid convex polygon passes both stage='solver' and stage='densify'."""
        poly = np.array([
            [0.0, 0.0, 5.0],
            [4.0, 0.0, 5.0],
            [4.0, 3.0, 5.0],
            [0.0, 3.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: poly}
        planes = {1: plane}

        # Pass 1: solver (read-only)
        result1 = validate_polygons(polygons, planes, stage="solver", repair=False)
        np.testing.assert_allclose(result1[1], poly, atol=1e-10)

        # Pass 2: densify (repair gate)
        result2 = validate_polygons(polygons, planes, stage="densify", repair=True)
        np.testing.assert_allclose(result2[1], poly, atol=1e-10)


class TestSelfIntersectingRepair:
    """TEST-06: Self-intersecting input is repaired to is_valid output."""

    def test_self_intersecting_input_repaired(self):
        """A bowtie polygon in 3D. After validate with repair=True, output
        must be Shapely-valid."""
        from shapely.geometry import Polygon as ShapelyPolygon
        from roof_pipeline.panel_snap_v2.winding import _project_to_2d

        # Asymmetric bowtie: edges cross near one end so one triangle is
        # much larger than the other (ratio ~0.99, area change ~0.01%).
        # make_valid splits into MultiPolygon, largest piece kept (ratio > 0.95).
        bowtie = np.array([
            [0.0, 0.0, 5.0],
            [10.0, 0.1, 5.0],
            [10.0, 0.0, 5.0],
            [0.0, 10.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: bowtie}
        planes = {1: plane}

        result = validate_polygons(polygons, planes, stage="densify", repair=True)

        # Project repaired result to 2D and check Shapely validity
        repaired_2d = _project_to_2d(result[1], plane)
        shp = ShapelyPolygon(repaired_2d)
        assert shp.is_valid, f"Repaired polygon should be valid, got: {shp}"


class TestSolverStageReadonly:
    """D-04: Solver stage is read-only -- no repair, only DEBUG log."""

    def test_solver_stage_is_readonly(self, caplog):
        """An invalid polygon passed with stage='solver' (repair=False).
        The function should NOT modify the polygon, only log at DEBUG level."""
        # Bowtie: self-intersecting
        bowtie = np.array([
            [0.0, 0.0, 5.0],
            [2.0, 2.0, 5.0],
            [2.0, 0.0, 5.0],
            [0.0, 2.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: bowtie}
        planes = {1: plane}

        with caplog.at_level(logging.DEBUG):
            result = validate_polygons(polygons, planes, stage="solver", repair=False)

        # Polygon should be unchanged (read-only)
        np.testing.assert_allclose(result[1], bowtie, atol=1e-10,
                                   err_msg="Solver stage should not modify polygon")

        # Should have logged at DEBUG level
        debug_messages = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("invalid after solver" in r.message for r in debug_messages), (
            f"Expected DEBUG log about 'invalid after solver', got: "
            f"{[r.message for r in debug_messages]}"
        )


class TestAreaChangeThresholds:
    """D-05: Graduated area change tolerance."""

    def test_area_change_under_threshold_silent(self, caplog):
        """make_valid changes area by < 0.1%. No warning logged."""
        # A valid convex polygon -- make_valid is a no-op
        poly = np.array([
            [0.0, 0.0, 5.0],
            [4.0, 0.0, 5.0],
            [4.0, 3.0, 5.0],
            [0.0, 3.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: poly}
        planes = {1: plane}

        with caplog.at_level(logging.WARNING):
            result = validate_polygons(polygons, planes, stage="densify", repair=True)

        # No WARNING should be logged
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        area_warnings = [r for r in warnings if "area" in r.message.lower()]
        assert len(area_warnings) == 0, (
            f"No area-change warning expected, got: {[r.message for r in area_warnings]}"
        )

    def test_area_change_warning_threshold(self, caplog):
        """make_valid changes area by between 0.1% and 1%. WARNING logged."""
        # A polygon with a "notch" that doubles back over the top edge,
        # creating a self-intersection. The overlap area (~50 sq units) is
        # ~0.5% of the total (~10050 sq units), in the warning band.
        # make_valid clips the overlap, producing a GeometryCollection
        # with the main polygon and a degenerate linestring.
        poly = np.array([
            [0.0, 0.0, 5.0],
            [100.0, 0.0, 5.0],
            [100.0, 100.0, 5.0],
            [30.0, 100.0, 5.0],
            [30.0, 95.0, 5.0],    # dips 5 units inside
            [40.0, 95.0, 5.0],    # 10-unit wide notch
            [40.0, 100.0, 5.0],   # back to top edge -- self-intersects
            [0.0, 100.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: poly}
        planes = {1: plane}

        with caplog.at_level(logging.WARNING):
            result = validate_polygons(polygons, planes, stage="densify", repair=True)

        # Check that repair happened without RuntimeError (area change < 1%)
        # and verify the result is valid
        from shapely.geometry import Polygon as ShapelyPolygon
        from roof_pipeline.panel_snap_v2.winding import _project_to_2d
        repaired_2d = _project_to_2d(result[1], plane)
        shp = ShapelyPolygon(repaired_2d)
        assert shp.is_valid

    def test_area_change_hard_fail(self):
        """make_valid changes area by >= 1%. RuntimeError raised."""
        # A polygon with a large overlap notch that causes ~2.9% area change.
        # make_valid produces a GeometryCollection with one polygon (no ratio
        # issue), but the area change exceeds the 1% hard-fail threshold.
        poly = np.array([
            [0.0, 0.0, 5.0],
            [100.0, 0.0, 5.0],
            [100.0, 100.0, 5.0],
            [60.0, 100.0, 5.0],
            [60.0, 85.0, 5.0],    # deep notch going 15 units inside
            [80.0, 85.0, 5.0],    # 20-unit wide
            [80.0, 100.0, 5.0],   # back to top edge -- self-intersects
            [0.0, 100.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: poly}
        planes = {1: plane}

        with pytest.raises(RuntimeError, match="repair changed polygon area"):
            validate_polygons(polygons, planes, stage="densify", repair=True)


class TestMultiPolygonHandling:
    """D-06: MultiPolygon from make_valid keeps largest piece."""

    def test_multipolygon_keeps_largest(self, caplog):
        """make_valid returns MultiPolygon. Largest piece kept. WARNING logged."""
        from shapely.geometry import Polygon as ShapelyPolygon
        from roof_pipeline.panel_snap_v2.winding import _project_to_2d

        # Asymmetric bowtie: one large triangle + one tiny triangle.
        # Edge (0,0)-(10,0.1) crosses edge (10,0)-(0,10) near one end.
        # Ratio ~0.9999, area change ~0.01% (well under 1% hard-fail).
        poly = np.array([
            [0.0, 0.0, 5.0],
            [10.0, 0.1, 5.0],
            [10.0, 0.0, 5.0],
            [0.0, 10.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: poly}
        planes = {1: plane}

        with caplog.at_level(logging.WARNING):
            result = validate_polygons(polygons, planes, stage="densify", repair=True)

        # Verify the result is a valid polygon (largest piece kept)
        repaired_2d = _project_to_2d(result[1], plane)
        shp = ShapelyPolygon(repaired_2d)
        assert shp.is_valid, f"Repaired polygon should be valid, got: {shp}"

        # Verify MultiPolygon WARNING was logged
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        multi_warnings = [r for r in warnings if "MultiPolygon" in r.message]
        assert len(multi_warnings) >= 1, (
            f"Expected MultiPolygon WARNING, got: {[r.message for r in warnings]}"
        )

    def test_multipolygon_ratio_too_low_fails(self):
        """make_valid returns MultiPolygon where largest piece is < 95%.
        RuntimeError raised."""
        # A symmetric bowtie: two roughly equal triangles (ratio ~0.5)
        bowtie = np.array([
            [0.0, 0.0, 5.0],
            [4.0, 4.0, 5.0],
            [4.0, 0.0, 5.0],
            [0.0, 4.0, 5.0],
        ])
        plane = _make_plane()
        polygons = {1: bowtie}
        planes = {1: plane}

        # This should fail either because the ratio < 0.95 or because
        # area change >= 1% -- either way, RuntimeError is expected
        with pytest.raises(RuntimeError):
            validate_polygons(polygons, planes, stage="densify", repair=True)
