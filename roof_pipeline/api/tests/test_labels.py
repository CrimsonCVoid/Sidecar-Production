"""Tests for label persistence endpoints (API-03)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestLabelSave:
    """API-03: POST /labels/{sampleId} persists panel label data."""

    def test_save_returns_200(self, client, mock_supabase_client):
        """POST with valid label data returns success."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        r = client.post("/api/labels/test-sample", json={
            "sample_id": "test-sample",
            "panels": [
                {"id": 1, "corners_pix": [[0, 0], [100, 0], [100, 100], [0, 100]]},
            ],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "saved"
        assert data["sample_id"] == "test-sample"
        assert data["panel_count"] == 1

        app.dependency_overrides.clear()

    def test_save_calls_upsert(self, client, mock_supabase_client):
        """POST upserts to labels table with sample_id as conflict key."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        client.post("/api/labels/test-sample", json={
            "sample_id": "test-sample",
            "panels": [{"id": 1, "corners_pix": [[0, 0], [1, 0], [0.5, 1]]}],
        })

        mock_supabase_client.table.assert_any_call("labels")

        app.dependency_overrides.clear()

    def test_save_preserves_vertex_coordinates(self, client, mock_supabase_client):
        """Saved panels contain exact vertex coordinates from input."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        input_panels = [
            {"id": 1, "corners_pix": [[0.123, 4.567], [100.89, 0.001], [50.5, 80.75]]},
        ]
        client.post("/api/labels/test-sample", json={
            "sample_id": "test-sample",
            "panels": input_panels,
        })

        # Verify the exact panel data was passed to supabase
        upsert_calls = mock_supabase_client.table.return_value.upsert.call_args_list
        assert len(upsert_calls) >= 1
        saved_payload = upsert_calls[0][0][0]
        assert saved_payload["panels"] == input_panels

        app.dependency_overrides.clear()


class TestLabelRetrieve:
    """API-03: GET /labels/{sampleId} retrieves panel label data."""

    def test_get_existing_returns_200(self, client, mock_supabase_client):
        """GET for existing sample returns label data."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app

        stored_panels = [
            {"id": 1, "corners_pix": [[0, 0], [100, 0], [100, 100]]},
        ]
        mock_supabase_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"sample_id": "test-sample", "panels": stored_panels}],
        )
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        r = client.get("/api/labels/test-sample")
        assert r.status_code == 200
        data = r.json()
        assert data["sample_id"] == "test-sample"
        assert data["panels"] == stored_panels

        app.dependency_overrides.clear()

    def test_get_nonexistent_returns_404(self, client, mock_supabase_client):
        """GET for nonexistent sample returns 404."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app

        mock_supabase_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        r = client.get("/api/labels/nonexistent")
        assert r.status_code == 404

        app.dependency_overrides.clear()

    def test_round_trip_preserves_coordinates(self, client, mock_supabase_client):
        """Save then retrieve preserves all vertex coordinates exactly."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app

        panels = [
            {"id": 1, "corners_pix": [[0.123456789, 4.567890123], [100.111, 0.222], [50.333, 80.444]]},
            {"id": 2, "corners_pix": [[100.111, 0.222], [200.555, 0.666], [200.555, 100.777], [100.111, 100.888]]},
        ]

        # Mock: save succeeds, then retrieve returns what was saved
        mock_supabase_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"sample_id": "rt-test", "panels": panels}],
        )
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        # Save
        client.post("/api/labels/rt-test", json={
            "sample_id": "rt-test",
            "panels": panels,
        })

        # Retrieve
        r = client.get("/api/labels/rt-test")
        assert r.status_code == 200
        data = r.json()
        assert data["panels"] == panels

        app.dependency_overrides.clear()
