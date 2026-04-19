"""Shared test fixtures for the FastAPI API test suite."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

# Set dummy env vars BEFORE importing app (Settings validates on import)
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from roof_pipeline.api.main import app
from roof_pipeline.api.deps import get_supabase


@pytest.fixture
def client():
    """FastAPI TestClient with mocked Supabase dependency."""
    mock_supabase = MagicMock()
    # Override the Supabase dependency to avoid real connections
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_supabase_client():
    """Standalone mock Supabase client for unit tests."""
    mock = MagicMock()
    mock.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "test-uuid"}])
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock.storage.from_.return_value.upload.return_value = {"Key": "test/path"}
    return mock


@pytest.fixture
def two_panel_input():
    """Two adjacent rectangular panels sharing an edge at x=100."""
    return {
        "panels": [
            {"id": 1, "corners_pix": [[0, 0], [100, 0], [100, 100], [0, 100]]},
            {"id": 2, "corners_pix": [[100, 0], [200, 0], [200, 100], [100, 100]]},
        ],
    }


@pytest.fixture
def single_panel_input():
    """Single triangular panel."""
    return {
        "panels": [
            {"id": 1, "corners_pix": [[0, 0], [100, 0], [50, 80]]},
        ],
    }
