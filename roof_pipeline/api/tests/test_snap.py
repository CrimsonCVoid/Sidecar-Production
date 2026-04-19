"""Tests for snap preview endpoint (API-01)."""

from __future__ import annotations

import pytest


class TestSnapPreview:
    """API-01: POST /snap-preview returns feature graph + snapped polygons."""

    def test_two_panels_returns_200(self, client, two_panel_input):
        """Two adjacent panels produce a valid snap preview response."""
        r = client.post("/api/snap/preview", json=two_panel_input)
        assert r.status_code == 200
        data = r.json()
        assert "feature_graph" in data
        assert "snapped_polygons" in data

    def test_response_has_features_and_edges(self, client, two_panel_input):
        """Feature graph contains features list and edges list."""
        r = client.post("/api/snap/preview", json=two_panel_input)
        data = r.json()
        fg = data["feature_graph"]
        assert "features" in fg
        assert "edges" in fg
        assert isinstance(fg["features"], list)
        assert isinstance(fg["edges"], list)

    def test_shared_edge_detected(self, client, two_panel_input):
        """Two panels sharing x=100 edge produce at least one graph edge."""
        r = client.post("/api/snap/preview", json=two_panel_input)
        data = r.json()
        edges = data["feature_graph"]["edges"]
        assert len(edges) >= 1, "Expected at least one shared edge between panels 1 and 2"

    def test_snapped_polygons_contain_both_panels(self, client, two_panel_input):
        """Response snapped_polygons dict contains keys for both panel IDs."""
        r = client.post("/api/snap/preview", json=two_panel_input)
        data = r.json()
        sp = data["snapped_polygons"]
        assert "1" in sp
        assert "2" in sp

    def test_polygon_vertices_are_lists_of_floats(self, client, two_panel_input):
        """Each polygon is a list of [x, y, z] float triples."""
        r = client.post("/api/snap/preview", json=two_panel_input)
        data = r.json()
        for pid, verts in data["snapped_polygons"].items():
            assert isinstance(verts, list)
            for v in verts:
                assert len(v) == 3, f"Panel {pid} vertex should have 3 coords, got {len(v)}"
                assert all(isinstance(c, (int, float)) for c in v)

    def test_single_panel_returns_200(self, client, single_panel_input):
        """Single panel without shared edges still returns valid response."""
        r = client.post("/api/snap/preview", json=single_panel_input)
        assert r.status_code == 200
        data = r.json()
        assert "1" in data["snapped_polygons"]
        assert data["feature_graph"]["edges"] == []

    def test_empty_panels_returns_422(self, client):
        """Empty panels list returns 422."""
        r = client.post("/api/snap/preview", json={"panels": []})
        assert r.status_code == 422

    def test_malformed_input_returns_422(self, client):
        """Missing corners_pix field returns 422 validation error."""
        r = client.post("/api/snap/preview", json={"panels": [{"id": 1}]})
        assert r.status_code == 422

    def test_too_few_corners_returns_422(self, client):
        """Panel with 2 corners (not enough for polygon) returns 422."""
        r = client.post("/api/snap/preview", json={
            "panels": [{"id": 1, "corners_pix": [[0, 0], [1, 0]]}],
        })
        assert r.status_code == 422

    def test_response_has_trace_id_header(self, client, two_panel_input):
        """Every response includes X-Trace-ID header from logging middleware."""
        r = client.post("/api/snap/preview", json=two_panel_input)
        assert "x-trace-id" in r.headers
        # UUID format: 8-4-4-4-12 hex chars
        trace_id = r.headers["x-trace-id"]
        assert len(trace_id) == 36

    def test_feature_nodes_have_required_fields(self, client, two_panel_input):
        """Each feature node has id, valence, position_xyz, panel_ids."""
        r = client.post("/api/snap/preview", json=two_panel_input)
        data = r.json()
        features = data["feature_graph"]["features"]
        assert len(features) > 0
        for f in features:
            assert "id" in f
            assert "valence" in f
            assert "position_xyz" in f
            assert "panel_ids" in f
            assert isinstance(f["panel_ids"], list)
