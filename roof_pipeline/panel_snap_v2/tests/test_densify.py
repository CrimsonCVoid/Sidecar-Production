"""Tests for edge-walking densification (TOPO-09)."""

from __future__ import annotations

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.densify import densify_edges
from roof_pipeline.panel_snap_v2.graph import build_feature_graph
from .conftest import _make_plane


class TestSharedEdgeDensification:
    """TOPO-09: Shared edges carry the same vertex list after densification."""

    def test_shared_edge_gets_same_vertices(self):
        """Panel A has 4 verts, Panel B has 5 (extra mid-edge). After densify,
        Panel A gains the mid-edge vertex so both panels share the same edge."""
        # Panel 1: rectangle on the positive-Y side of the X-axis
        #   (0,0,5) -> (4,0,5) -> (4,2,5) -> (0,2,5)
        poly1 = np.array([
            [0.0, 0.0, 5.0],
            [4.0, 0.0, 5.0],
            [4.0, 2.0, 5.0],
            [0.0, 2.0, 5.0],
        ])
        # Panel 2: rectangle on the negative-Y side, with extra mid-edge vertex
        #   (0,0,5) -> (0,-2,5) -> (4,-2,5) -> (4,0,5) -> (2,0,5)
        # The extra vertex (2,0,5) sits mid-edge on the shared edge
        poly2 = np.array([
            [0.0, 0.0, 5.0],
            [0.0, -2.0, 5.0],
            [4.0, -2.0, 5.0],
            [4.0, 0.0, 5.0],
            [2.0, 0.0, 5.0],
        ])

        plane = _make_plane()
        polygons = {1: poly1, 2: poly2}
        planes = {1: plane, 2: plane}

        graph = build_feature_graph(polygons, planes, tol=1.0)
        result = densify_edges(polygons, planes, graph, tol=1.0)

        # Panel 1 should now have (2,0,5) inserted on its shared edge
        # Find vertices on the shared edge (Y=0) in Panel 1's result
        r1 = result[1]
        shared_verts_1 = sorted(
            [tuple(v[:2]) for v in r1 if abs(v[1]) < 0.01],
            key=lambda p: p[0],
        )

        # Panel 2's shared-edge vertices (Y=0)
        r2 = result[2]
        shared_verts_2 = sorted(
            [tuple(v[:2]) for v in r2 if abs(v[1]) < 0.01],
            key=lambda p: p[0],
        )

        # Both should have (0,0), (2,0), (4,0) on the shared edge
        assert len(shared_verts_1) >= 3, (
            f"Panel 1 should have >= 3 vertices on shared edge, got {shared_verts_1}"
        )
        assert len(shared_verts_2) >= 3, (
            f"Panel 2 should have >= 3 vertices on shared edge, got {shared_verts_2}"
        )

        # The shared-edge XY coordinates should match
        for v1, v2 in zip(shared_verts_1, shared_verts_2):
            np.testing.assert_allclose(v1, v2, atol=1e-10,
                                       err_msg="Shared edge vertices should have same XY")

    def test_insertions_sorted_by_t(self):
        """Two extra mid-edge vertices. After densify, insertions are sorted by t."""
        # Panel 1: rectangle with long shared edge (0 to 10) -- extra vertices
        # at x=3 and x=7 are well outside tol=1.0 from endpoints
        poly1 = np.array([
            [0.0, 0.0, 5.0],
            [10.0, 0.0, 5.0],
            [10.0, 2.0, 5.0],
            [0.0, 2.0, 5.0],
        ])
        # Panel 2: has two extra vertices at (3,0,5) and (7,0,5) on shared edge
        poly2 = np.array([
            [0.0, 0.0, 5.0],
            [0.0, -2.0, 5.0],
            [10.0, -2.0, 5.0],
            [10.0, 0.0, 5.0],
            [7.0, 0.0, 5.0],
            [3.0, 0.0, 5.0],
        ])

        plane = _make_plane()
        polygons = {1: poly1, 2: poly2}
        planes = {1: plane, 2: plane}

        graph = build_feature_graph(polygons, planes, tol=1.0)
        result = densify_edges(polygons, planes, graph, tol=1.0)

        # Find vertices on Y=0 in Panel 1, sorted by X
        r1 = result[1]
        shared_xs = sorted(
            [float(v[0]) for v in r1 if abs(v[1]) < 0.01],
        )

        # Should have 0, 3, 7, 10 (endpoints + two insertions)
        assert len(shared_xs) >= 4, (
            f"Panel 1 should have >= 4 vertices on shared edge, got {shared_xs}"
        )

        # Verify sorted order (insertions appear in parameter-t order)
        for i in range(len(shared_xs) - 1):
            assert shared_xs[i] <= shared_xs[i + 1] + 1e-10, (
                f"Vertices not sorted by t: {shared_xs}"
            )

    def test_no_duplicate_near_endpoints(self):
        """A vertex very close to an endpoint (within tol) should NOT be inserted."""
        # Panel 1: rectangle
        poly1 = np.array([
            [0.0, 0.0, 5.0],
            [4.0, 0.0, 5.0],
            [4.0, 2.0, 5.0],
            [0.0, 2.0, 5.0],
        ])
        # Panel 2: has extra vertex at (0.01, 0, 5) -- within tol of (0,0,5)
        poly2 = np.array([
            [0.0, 0.0, 5.0],
            [0.0, -2.0, 5.0],
            [4.0, -2.0, 5.0],
            [4.0, 0.0, 5.0],
            [0.01, 0.0, 5.0],
        ])

        plane = _make_plane()
        polygons = {1: poly1, 2: poly2}
        planes = {1: plane, 2: plane}

        graph = build_feature_graph(polygons, planes, tol=1.0)
        result = densify_edges(polygons, planes, graph, tol=1.0)

        # Panel 1 should NOT have an extra vertex near (0,0,5)
        r1 = result[1]
        shared_on_edge = [v for v in r1 if abs(v[1]) < 0.01]

        # Should still only have 2 vertices on the shared edge (the endpoints)
        # The (0.01, 0, 5) vertex is within tol of endpoint and should be skipped
        assert len(shared_on_edge) == 2, (
            f"Expected 2 vertices on shared edge (no duplicate near endpoint), "
            f"got {len(shared_on_edge)}: {[tuple(v) for v in shared_on_edge]}"
        )
