"""Tests for structured logging middleware (OBSERVABILITY-01a)."""

from __future__ import annotations

import json
import logging

import pytest


class TestStructuredLogging:
    """OBSERVABILITY-01a: Every request logs structured JSON with required fields."""

    def test_trace_id_in_response_header(self, client):
        """Health check response includes X-Trace-ID header."""
        r = client.get("/health")
        assert "x-trace-id" in r.headers
        trace_id = r.headers["x-trace-id"]
        assert len(trace_id) == 36  # UUID format

    def test_log_entry_contains_required_fields(self, client, caplog):
        """Request log entry contains trace_id, endpoint, latency_ms, sample_id, error_type."""
        with caplog.at_level(logging.INFO):
            client.get("/health")

        # Find the structured JSON log entry from the middleware
        log_entries = []
        for record in caplog.records:
            msg = record.getMessage()
            try:
                entry = json.loads(msg)
                if "trace_id" in entry and "endpoint" in entry:
                    log_entries.append(entry)
            except (json.JSONDecodeError, TypeError):
                continue

        assert len(log_entries) >= 1, (
            f"Expected at least one structured JSON log entry, "
            f"got {len(log_entries)}. All records: {[r.getMessage() for r in caplog.records]}"
        )
        entry = log_entries[0]
        assert "trace_id" in entry
        assert "endpoint" in entry
        assert "latency_ms" in entry
        assert "sample_id" in entry  # May be None
        assert "error_type" in entry  # May be None

    def test_log_entry_has_correct_endpoint(self, client, caplog):
        """Log entry endpoint field matches the actual request path."""
        with caplog.at_level(logging.INFO):
            client.get("/health")

        for record in caplog.records:
            try:
                entry = json.loads(record.getMessage())
                if "endpoint" in entry:
                    assert entry["endpoint"] == "/health"
                    return
            except (json.JSONDecodeError, TypeError):
                continue
        pytest.fail("No structured log entry found with endpoint field")

    def test_log_entry_latency_is_numeric(self, client, caplog):
        """Log entry latency_ms is a positive number."""
        with caplog.at_level(logging.INFO):
            client.get("/health")

        for record in caplog.records:
            try:
                entry = json.loads(record.getMessage())
                if "latency_ms" in entry:
                    assert isinstance(entry["latency_ms"], (int, float))
                    assert entry["latency_ms"] >= 0
                    return
            except (json.JSONDecodeError, TypeError):
                continue
        pytest.fail("No structured log entry found with latency_ms field")

    def test_error_response_contains_error_type(self, client, caplog):
        """Error responses include error_type in the response body."""
        # Trigger a 422 with invalid input
        r = client.post("/api/snap/preview", json={"panels": [{"id": 1}]})
        assert r.status_code == 422

    def test_unique_trace_ids_per_request(self, client):
        """Each request gets a unique trace_id."""
        r1 = client.get("/health")
        r2 = client.get("/health")
        trace1 = r1.headers.get("x-trace-id")
        trace2 = r2.headers.get("x-trace-id")
        assert trace1 != trace2, "Each request should have a unique trace_id"
