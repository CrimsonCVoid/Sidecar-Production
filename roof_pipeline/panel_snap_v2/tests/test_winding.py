"""Tests for winding normalization (TEST-07, D-12)."""

from __future__ import annotations

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.winding import normalize_winding
from .conftest import _make_plane


class TestLShapedWinding:
    """TEST-07: Non-convex L-shaped panel winding normalization."""

    # L-shape in CCW order (6 vertices, concave at vertex 2):
    #   (0,0) -> (2,0) -> (2,1) -> (1,1) -> (1,2) -> (0,2)
    L_CCW_2D = np.array([
        [0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2],
    ], dtype=float)

    # Same L-shape in CW order (reversed):
    L_CW_2D = L_CCW_2D[::-1].copy()

    @staticmethod
    def _to_3d(verts_2d, z=5.0):
        """Lift 2D vertices to 3D on a horizontal plane at height z."""
        return np.column_stack([verts_2d, np.full(len(verts_2d), z)])

    def test_ccw_and_cw_l_shape_produce_same_result(self):
        """Both CW and CCW orderings normalize to identical CCW output."""
        plane = _make_plane([0, 0, 1], [1, 1, 5])
        ccw_3d = self._to_3d(self.L_CCW_2D)
        cw_3d = self._to_3d(self.L_CW_2D)

        result_from_ccw = normalize_winding({1: ccw_3d}, {1: plane})
        result_from_cw = normalize_winding({1: cw_3d}, {1: plane})

        np.testing.assert_allclose(result_from_ccw[1], result_from_cw[1], atol=1e-10)

    def test_ccw_input_unchanged(self):
        """A polygon already in CCW order is not modified."""
        plane = _make_plane([0, 0, 1], [1, 1, 5])
        ccw_3d = self._to_3d(self.L_CCW_2D)

        result = normalize_winding({1: ccw_3d}, {1: plane})

        np.testing.assert_allclose(result[1], ccw_3d, atol=1e-10)


class TestSteepPlaneWinding:
    """D-12: 60-degree pitch panel where naive XY-drop would fail."""

    def test_steep_plane_normalizes_correctly(self):
        """A panel tilted 60 degrees from horizontal normalizes without flipping."""
        # 60-degree pitch: normal in YZ plane, 30 degrees from Z axis
        # normal = [0, -sin(60), cos(60)] but oriented upward (n_z > 0)
        normal = [0.0, -np.sin(np.radians(60)), np.cos(np.radians(60))]
        centroid = [5.0, 5.0, 10.0]
        plane = _make_plane(normal, centroid)

        # Build a rectangular panel in the tilted plane's local frame
        u, v = _plane_basis_for_test(plane.normal)
        center = plane.centroid
        # 4 vertices forming a 2m x 3m rectangle in the plane
        verts_3d = np.array([
            center - 1.0 * u - 1.5 * v,
            center + 1.0 * u - 1.5 * v,
            center + 1.0 * u + 1.5 * v,
            center - 1.0 * u + 1.5 * v,
        ])

        # This is CCW when viewed from the normal direction
        result = normalize_winding({1: verts_3d}, {1: plane})
        # Should not flip -- output matches input
        np.testing.assert_allclose(result[1], verts_3d, atol=1e-10)

        # Now reverse (CW in plane frame) -- should get flipped back to CCW
        cw_verts = verts_3d[::-1].copy()
        result_cw = normalize_winding({1: cw_verts}, {1: plane})
        np.testing.assert_allclose(result_cw[1], verts_3d, atol=1e-10)


class TestSelfIntersectingRaises:
    """D-12: Bowtie polygon raises with panel ID."""

    def test_bowtie_raises_with_panel_id(self):
        """A self-intersecting (bowtie) polygon raises an error mentioning the panel ID."""
        plane = _make_plane([0, 0, 1], [1, 1, 5])
        # Bowtie: edges (0,0)-(2,2) and (2,0)-(0,2) cross
        bowtie = np.array([
            [0, 0, 5], [2, 2, 5], [2, 0, 5], [0, 2, 5],
        ], dtype=float)

        with pytest.raises(Exception, match="42"):
            normalize_winding({42: bowtie}, {42: plane})


def _plane_basis_for_test(normal):
    """Replicate _plane_basis from mesh.py for test fixture construction."""
    normal = np.asarray(normal, dtype=float)
    if abs(normal[0]) < 0.9:
        seed = np.array([1.0, 0.0, 0.0])
    else:
        seed = np.array([0.0, 1.0, 0.0])
    u = seed - (seed @ normal) * normal
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    return u, v
