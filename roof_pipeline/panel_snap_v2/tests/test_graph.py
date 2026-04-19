"""Tests for feature graph construction (TEST-05)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.graph import build_feature_graph
from .conftest import _make_plane


class TestMixedWindingHip:
    """TEST-05: Opposite winding still produces correct feature graph."""

    def test_mixed_winding_hip(self):
        """Two panels traversing shared edge in opposite order produce correct graph."""
        # Panel 1: triangle A(0,0,5) -> B(2,0,5) -> C(1,2,5)  (CCW)
        # Panel 2: triangle B(2,0,5) -> A(0,0,5) -> D(1,-2,5) (edge B-A is reversed)
        # After winding normalization, both should be CCW.
        # Shared vertices: A and B appear in both panels.
        poly1 = np.array([[0, 0, 5], [2, 0, 5], [1, 2, 5]], dtype=float)
        poly2 = np.array([[2, 0, 5], [0, 0, 5], [1, -2, 5]], dtype=float)

        plane = _make_plane()
        polygons = {1: poly1, 2: poly2}
        planes = {1: plane, 2: plane}

        graph = build_feature_graph(polygons, planes, tol=0.1)

        # Find features that touch both panels
        shared_features = [
            f for f in graph["features"]
            if set(f["panel_ids"]) == {1, 2}
        ]
        # A and B are shared, so 2 shared features
        assert len(shared_features) == 2

        # There should be an edge between panel 1 and panel 2
        edges_1_2 = [
            e for e in graph["edges"]
            if {e["panel_a"], e["panel_b"]} == {1, 2}
        ]
        assert len(edges_1_2) == 1
        # The edge should reference the 2 shared feature IDs
        assert len(edges_1_2[0]["feature_ids"]) == 2


class TestValenceDistribution:
    """Valence classification: corner=2, ridge_apex=3, hip_apex=4+."""

    def test_four_panel_hip_apex(self):
        """4 panels meeting at one point produce a valence-4 hip apex."""
        # 4 triangles meeting at origin
        apex = [0, 0, 10]
        poly1 = np.array([apex, [2, 0, 5], [0, 2, 5]], dtype=float)
        poly2 = np.array([apex, [0, 2, 5], [-2, 0, 5]], dtype=float)
        poly3 = np.array([apex, [-2, 0, 5], [0, -2, 5]], dtype=float)
        poly4 = np.array([apex, [0, -2, 5], [2, 0, 5]], dtype=float)

        plane = _make_plane(centroid=[0, 0, 7])
        polygons = {1: poly1, 2: poly2, 3: poly3, 4: poly4}
        planes = {1: plane, 2: plane, 3: plane, 4: plane}

        graph = build_feature_graph(polygons, planes, tol=0.1)

        # Find the apex feature (touches all 4 panels)
        apex_features = [
            f for f in graph["features"]
            if len(f["panel_ids"]) >= 4
        ]
        assert len(apex_features) == 1
        assert apex_features[0]["valence"] == 4


class TestJsonSchema:
    """Feature graph output matches INTG-02 schema."""

    def test_schema_conformance(self):
        """Output has features and edges with correct field names and types."""
        poly1 = np.array([[0, 0, 5], [2, 0, 5], [1, 2, 5]], dtype=float)
        poly2 = np.array([[2, 0, 5], [4, 0, 5], [3, 2, 5]], dtype=float)

        plane = _make_plane()
        graph = build_feature_graph(
            {1: poly1, 2: poly2}, {1: plane, 2: plane}, tol=0.1,
        )

        # Top-level keys
        assert "features" in graph
        assert "edges" in graph

        # Feature fields
        for f in graph["features"]:
            assert "id" in f
            assert "valence" in f
            assert "position_xyz" in f  # must be present, even if null
            assert "panel_ids" in f
            assert f["position_xyz"] is None  # Phase 1: unsolved
            assert isinstance(f["id"], int)
            assert isinstance(f["valence"], int)
            assert isinstance(f["panel_ids"], list)

        # Edge fields
        for e in graph["edges"]:
            assert "panel_a" in e
            assert "panel_b" in e
            assert "feature_ids" in e
            assert isinstance(e["panel_a"], int)
            assert isinstance(e["panel_b"], int)
            assert isinstance(e["feature_ids"], list)

        # Must be JSON-serializable
        json.dumps(graph)


class TestCornerValence:
    """Corner (valence-2) classification."""

    def test_shared_single_vertex_is_valence_2(self):
        """Two panels sharing one vertex: that cluster has valence 2."""
        # Panel 1 and 2 share vertex B at (2,0,5)
        poly1 = np.array([[0, 0, 5], [2, 0, 5], [1, 2, 5]], dtype=float)
        poly2 = np.array([[2, 0, 5], [4, 0, 5], [3, 2, 5]], dtype=float)

        plane = _make_plane()
        graph = build_feature_graph(
            {1: poly1, 2: poly2}, {1: plane, 2: plane}, tol=0.1,
        )

        # Find the shared vertex feature
        shared = [f for f in graph["features"] if len(f["panel_ids"]) == 2]
        assert len(shared) >= 1
        assert all(f["valence"] == 2 for f in shared)
