"""Tests for pipeline run endpoints (API-02)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestPipelineRunTrigger:
    """API-02: POST /run-pipeline returns 202 and creates pipeline_runs row."""

    def test_trigger_returns_202(self, client, mock_supabase_client):
        """POST /api/pipeline/run returns 202 Accepted."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        r = client.post("/api/pipeline/run", json={
            "sample_id": "test-sample-uuid",
        })
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"

        app.dependency_overrides.clear()

    def test_response_has_run_id_and_status_url(self, client, mock_supabase_client):
        """Response contains run_id (UUID) and status_url."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        r = client.post("/api/pipeline/run", json={
            "sample_id": "test-sample-uuid",
        })
        data = r.json()
        assert "run_id" in data
        assert "status_url" in data
        assert len(data["run_id"]) == 36  # UUID format
        assert data["status_url"].startswith("/api/pipeline/run/")

        app.dependency_overrides.clear()

    def test_inserts_queued_status_row(self, client, mock_supabase_client):
        """Trigger inserts a pipeline_runs row with status='queued'."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        client.post("/api/pipeline/run", json={
            "sample_id": "test-sample-uuid",
        })

        # Verify insert was called on pipeline_runs table
        mock_supabase_client.table.assert_any_call("pipeline_runs")
        insert_calls = mock_supabase_client.table.return_value.insert.call_args_list
        assert len(insert_calls) >= 1
        inserted_data = insert_calls[0][0][0]
        assert inserted_data["status"] == "queued"
        assert inserted_data["sample_id"] == "test-sample-uuid"
        assert inserted_data["progress_pct"] == 0

        app.dependency_overrides.clear()

    def test_malformed_request_returns_422(self, client):
        """Missing sample_id returns 422."""
        r = client.post("/api/pipeline/run", json={})
        assert r.status_code == 422


class TestPipelineRunStatus:
    """API-02: GET /run/{run_id} returns current pipeline status."""

    def test_existing_run_returns_status(self, client, mock_supabase_client):
        """GET returns pipeline_runs row data for existing run_id."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app

        # Configure mock to return a pipeline_runs row
        mock_supabase_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "test-run-id",
                "sample_id": "test-sample",
                "status": "running",
                "stage_name": "mesh",
                "progress_pct": 65,
                "error_message": None,
                "started_at": "2026-04-19T00:00:00Z",
                "completed_at": None,
            }]
        )
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        r = client.get("/api/pipeline/run/test-run-id")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "running"
        assert data["stage_name"] == "mesh"
        assert data["progress_pct"] == 65

        app.dependency_overrides.clear()

    def test_nonexistent_run_returns_404(self, client, mock_supabase_client):
        """GET with unknown run_id returns 404."""
        from roof_pipeline.api.deps import get_supabase
        from roof_pipeline.api.main import app

        mock_supabase_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        app.dependency_overrides[get_supabase] = lambda: mock_supabase_client

        r = client.get("/api/pipeline/run/nonexistent-id")
        assert r.status_code == 404

        app.dependency_overrides.clear()


class TestPipelineBackgroundTask:
    """API-02: Background task updates status at stage boundaries."""

    def test_update_status_calls_supabase(self):
        """_update_status writes to pipeline_runs table."""
        from roof_pipeline.api.pipeline import _update_status

        mock_client = MagicMock()
        _update_status(
            mock_client, "test-run-id",
            status="running", stage_name="mesh", progress_pct=65,
        )
        mock_client.table.assert_called_with("pipeline_runs")
        update_data = mock_client.table.return_value.update.call_args[0][0]
        assert update_data["status"] == "running"
        assert update_data["stage_name"] == "mesh"
        assert update_data["progress_pct"] == 65

    def test_upload_output_sets_content_type(self):
        """_upload_output sets explicit content-type for each file extension."""
        from roof_pipeline.api.pipeline import _CONTENT_TYPES
        assert _CONTENT_TYPES[".pdf"] == "application/pdf"
        assert _CONTENT_TYPES[".gltf"] == "model/gltf+json"
        assert _CONTENT_TYPES[".obj"] == "model/obj"
        assert _CONTENT_TYPES[".json"] == "application/json"
