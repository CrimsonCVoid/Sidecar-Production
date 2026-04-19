"""Tests for valence-aware apex solver (TOPO-05, TOPO-06, TOPO-07, TOPO-08)."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.solver import solve_apices
from roof_pipeline.panel_snap_v2.graph import build_feature_graph
from .conftest import _make_plane


def _plane_from_triangle(v0, v1, v2):
    """Compute a Plane from three 3D vertices using cross-product normal."""
    v0 = np.asarray(v0, dtype=float)
    v1 = np.asarray(v1, dtype=float)
    v2 = np.asarray(v2, dtype=float)
    e1 = v1 - v0
    e2 = v2 - v0
    n = np.cross(e1, e2)
    n = n / np.linalg.norm(n)
    if n[2] < 0:
        n = -n
    centroid = (v0 + v1 + v2) / 3.0
    d = float(n @ centroid)
    return Plane(normal=n, centroid=centroid, rms_residual=0.01, d=d)


class TestHipApexWeld:
    """TEST-02: 4 triangular panels meeting at a hip apex weld to one point."""

    def test_hip_apex_four_panels_welds(self):
        """4 panels meeting at origin (0,0,10) with different plane normals.

        After solve_apices, all 4 output polygons contain the exact same
        (x,y,z) at vertex index 0.
        """
        apex = np.array([0.0, 0.0, 10.0])
        # 4 triangular panels meeting at apex, each in a different quadrant
        v1a, v1b = np.array([2.0, 0.0, 5.0]), np.array([0.0, 2.0, 5.0])
        v2a, v2b = np.array([0.0, 2.0, 5.0]), np.array([-2.0, 0.0, 5.0])
        v3a, v3b = np.array([-2.0, 0.0, 5.0]), np.array([0.0, -2.0, 5.0])
        v4a, v4b = np.array([0.0, -2.0, 5.0]), np.array([2.0, 0.0, 5.0])

        poly1 = np.array([apex, v1a, v1b])
        poly2 = np.array([apex, v2a, v2b])
        poly3 = np.array([apex, v3a, v3b])
        poly4 = np.array([apex, v4a, v4b])

        plane1 = _plane_from_triangle(apex, v1a, v1b)
        plane2 = _plane_from_triangle(apex, v2a, v2b)
        plane3 = _plane_from_triangle(apex, v3a, v3b)
        plane4 = _plane_from_triangle(apex, v4a, v4b)

        polygons = {1: poly1, 2: poly2, 3: poly3, 4: poly4}
        planes = {1: plane1, 2: plane2, 3: plane3, 4: plane4}
        graph = build_feature_graph(polygons, planes, tol=0.5)

        polygons_out, solved_positions = solve_apices(
            polygons, planes, graph, tol=0.5,
        )

        # All 4 panels' vertex 0 should be the exact same point
        apex_positions = [polygons_out[pid][0] for pid in [1, 2, 3, 4]]
        for i in range(1, 4):
            np.testing.assert_allclose(
                apex_positions[i], apex_positions[0], atol=1e-9,
                err_msg=f"Panel {i+1} apex differs from Panel 1 apex",
            )


class TestRidgeWeld:
    """TEST-03: 3 panels meeting at a ridge point weld to one point."""

    def test_ridge_three_panels_welds(self):
        """3 panels meeting at a ridge point all share the exact apex.

        Panel 1 and 2 form a gable ridge, Panel 3 is a perpendicular hip face.
        """
        # Ridge apex at (5, 0, 10)
        apex = np.array([5.0, 0.0, 10.0])

        # Panel 1: left side of ridge
        p1v1 = np.array([0.0, 0.0, 5.0])
        p1v2 = np.array([0.0, 4.0, 5.0])
        poly1 = np.array([apex, p1v1, p1v2])

        # Panel 2: right side of ridge
        p2v1 = np.array([10.0, 0.0, 5.0])
        p2v2 = np.array([10.0, 4.0, 5.0])
        poly2 = np.array([apex, p2v1, p2v2])

        # Panel 3: hip face at the end
        p3v1 = np.array([0.0, 0.0, 5.0])
        p3v2 = np.array([10.0, 0.0, 5.0])
        poly3 = np.array([apex, p3v1, p3v2])

        plane1 = _plane_from_triangle(apex, p1v1, p1v2)
        plane2 = _plane_from_triangle(apex, p2v1, p2v2)
        plane3 = _plane_from_triangle(apex, p3v1, p3v2)

        polygons = {1: poly1, 2: poly2, 3: poly3}
        planes = {1: plane1, 2: plane2, 3: plane3}
        graph = build_feature_graph(polygons, planes, tol=0.5)

        polygons_out, solved_positions = solve_apices(
            polygons, planes, graph, tol=0.5,
        )

        # All 3 panels' vertex 0 should be the exact same point
        apex_positions = [polygons_out[pid][0] for pid in [1, 2, 3]]
        for i in range(1, 3):
            np.testing.assert_allclose(
                apex_positions[i], apex_positions[0], atol=1e-9,
                err_msg=f"Panel {i+1} ridge apex differs from Panel 1",
            )


class TestValence2:
    """TOPO-05: Valence-2 uses XY centroid + per-plane Z reconstruction."""

    def test_valence2_xy_centroid_per_plane_z(self):
        """2 panels sharing a corner with different planes.

        After solving, the shared XY is the centroid of the two original XY
        positions and each panel gets its own Z from its plane equation.
        """
        # Panel 1: tilted 30 degrees, shared corner near (1, 1, z1)
        # Panel 2: tilted 45 degrees, shared corner near (1.05, 1.02, z2)
        # Within tol=0.5, these should cluster.
        p1_shared = np.array([1.0, 1.0, 5.0])
        p1_other1 = np.array([3.0, 1.0, 4.0])
        p1_other2 = np.array([2.0, 3.0, 4.5])
        poly1 = np.array([p1_shared, p1_other1, p1_other2])

        p2_shared = np.array([1.05, 1.02, 7.0])
        p2_other1 = np.array([-1.0, 1.0, 6.0])
        p2_other2 = np.array([0.0, 3.0, 6.5])
        poly2 = np.array([p2_shared, p2_other1, p2_other2])

        # Build planes with distinct normals
        # Panel 1: tilted ~30 deg from horizontal
        plane1 = _make_plane(
            normal=[0.0, -np.sin(np.radians(30)), np.cos(np.radians(30))],
            centroid=p1_shared,
        )
        # Panel 2: tilted ~45 deg from horizontal
        plane2 = _make_plane(
            normal=[np.sin(np.radians(45)), 0.0, np.cos(np.radians(45))],
            centroid=p2_shared,
        )

        polygons = {1: poly1, 2: poly2}
        planes = {1: plane1, 2: plane2}
        graph = build_feature_graph(polygons, planes, tol=0.5)

        polygons_out, solved_positions = solve_apices(
            polygons, planes, graph, tol=0.5,
        )

        # Expected XY centroid of the two original positions
        expected_x = (1.0 + 1.05) / 2.0
        expected_y = (1.0 + 1.02) / 2.0

        # Panel 1 should have XY = centroid, Z from plane1
        out1 = polygons_out[1][0]
        assert abs(out1[0] - expected_x) < 1e-9, f"Panel 1 X: {out1[0]} != {expected_x}"
        assert abs(out1[1] - expected_y) < 1e-9, f"Panel 1 Y: {out1[1]} != {expected_y}"

        # Panel 2 should have XY = same centroid, Z from plane2
        out2 = polygons_out[2][0]
        assert abs(out2[0] - expected_x) < 1e-9, f"Panel 2 X: {out2[0]} != {expected_x}"
        assert abs(out2[1] - expected_y) < 1e-9, f"Panel 2 Y: {out2[1]} != {expected_y}"

        # XY should be identical between both panels
        np.testing.assert_allclose(out1[:2], out2[:2], atol=1e-9)

        # Z should differ (different planes)
        assert abs(out1[2] - out2[2]) > 0.01, (
            f"Panel Z values should differ: {out1[2]} vs {out2[2]}"
        )


class TestConditionNumberFallback:
    """D-01: Condition number > 1e8 triggers centroid fallback with WARNING."""

    def test_cond_warn_fallback(self, caplog):
        """3 near-parallel planes (cond > 1e8) fall back to centroid."""
        # 3 panels meeting at a point, but planes are nearly parallel
        # (normals differ by ~0.001 radians)
        apex = np.array([0.0, 0.0, 5.0])
        v1 = np.array([2.0, 0.0, 5.0])
        v2 = np.array([0.0, 2.0, 5.0])
        v3 = np.array([-2.0, 0.0, 5.0])

        poly1 = np.array([apex, v1, v2])
        poly2 = np.array([apex, v2, v3])
        poly3 = np.array([apex, v3, v1])

        # Near-parallel planes: normals differ by tiny amounts
        plane1 = _make_plane(normal=[0.0, 0.0, 1.0], centroid=apex)
        plane2 = _make_plane(normal=[0.001, 0.0, 0.9999995], centroid=apex)
        plane3 = _make_plane(normal=[0.0, 0.001, 0.9999995], centroid=apex)

        polygons = {1: poly1, 2: poly2, 3: poly3}
        planes = {1: plane1, 2: plane2, 3: plane3}
        graph = build_feature_graph(polygons, planes, tol=0.5)

        with caplog.at_level(logging.WARNING):
            polygons_out, solved_positions = solve_apices(
                polygons, planes, graph, tol=0.5,
            )

        # Should NOT raise -- fallback to centroid
        # Should log a WARNING matching "snap_v2 fallback"
        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("snap_v2 fallback" in msg for msg in warning_msgs), (
            f"Expected WARNING with 'snap_v2 fallback', got: {warning_msgs}"
        )


class TestConditionNumberHardFail:
    """D-01: Condition number > 1e12 raises RuntimeError."""

    def test_cond_fail_hard(self):
        """3 truly parallel planes (cond > 1e12) raise RuntimeError."""
        # 3 panels meeting at a point, but all planes are exactly parallel
        apex = np.array([0.0, 0.0, 5.0])
        v1 = np.array([2.0, 0.0, 5.0])
        v2 = np.array([0.0, 2.0, 5.0])
        v3 = np.array([-2.0, 0.0, 5.0])

        poly1 = np.array([apex, v1, v2])
        poly2 = np.array([apex, v2, v3])
        poly3 = np.array([apex, v3, v1])

        # Truly parallel planes -- all normal=[0,0,1] but different d values
        plane1 = Plane(
            normal=np.array([0.0, 0.0, 1.0]),
            centroid=np.array([0.0, 0.0, 5.0]),
            rms_residual=0.01,
            d=5.0,
        )
        plane2 = Plane(
            normal=np.array([0.0, 0.0, 1.0]),
            centroid=np.array([0.0, 0.0, 5.001]),
            rms_residual=0.01,
            d=5.001,
        )
        plane3 = Plane(
            normal=np.array([0.0, 0.0, 1.0]),
            centroid=np.array([0.0, 0.0, 5.002]),
            rms_residual=0.01,
            d=5.002,
        )

        polygons = {1: poly1, 2: poly2, 3: poly3}
        planes = {1: plane1, 2: plane2, 3: plane3}
        graph = build_feature_graph(polygons, planes, tol=0.5)

        with pytest.raises(RuntimeError, match="snap_v2 singular"):
            solve_apices(polygons, planes, graph, tol=0.5)
