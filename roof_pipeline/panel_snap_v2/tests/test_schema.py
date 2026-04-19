"""Tests for Pydantic input validation schema (VALID-01, VALID-02)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from roof_pipeline.panel_snap_v2.schema import PanelCorners, PanelsInput


class TestSchemaValidation:
    """VALID-01/VALID-02: Pydantic schema rejects malformed panel JSON."""

    def test_valid_input_passes(self):
        """Well-formed dict passes PanelsInput.model_validate without error."""
        data = {
            "panels": [
                {"id": 1, "corners_pix": [[0, 0], [1, 0], [0.5, 1]]},
            ],
        }
        result = PanelsInput.model_validate(data)
        assert len(result.panels) == 1
        assert result.panels[0].id == 1
        assert len(result.panels[0].corners_pix) == 3

    def test_missing_corners_pix_raises(self):
        """Dict with missing corners_pix raises ValidationError."""
        data = {"panels": [{"id": 1}]}
        with pytest.raises(ValidationError):
            PanelsInput.model_validate(data)

    def test_wrong_type_corners_raises(self):
        """Dict with corners_pix as string raises ValidationError."""
        data = {"panels": [{"id": 1, "corners_pix": "not_a_list"}]}
        with pytest.raises(ValidationError):
            PanelsInput.model_validate(data)

    def test_empty_corners_raises(self):
        """Dict with empty corners_pix raises ValidationError mentioning 3 corners."""
        data = {"panels": [{"id": 1, "corners_pix": []}]}
        with pytest.raises(ValidationError, match="3 corners"):
            PanelsInput.model_validate(data)

    def test_two_vertex_polygon_raises(self):
        """Dict with only 2 corners raises ValidationError mentioning 3 corners."""
        data = {"panels": [{"id": 1, "corners_pix": [[0, 0], [1, 0]]}]}
        with pytest.raises(ValidationError, match="3 corners"):
            PanelsInput.model_validate(data)

    def test_missing_panels_key_raises(self):
        """Dict without 'panels' key raises ValidationError."""
        data = {}
        with pytest.raises(ValidationError):
            PanelsInput.model_validate(data)

    def test_non_numeric_id_raises(self):
        """Dict with id='abc' raises ValidationError."""
        data = {"panels": [{"id": "abc", "corners_pix": [[0, 0], [1, 0], [0.5, 1]]}]}
        with pytest.raises(ValidationError):
            PanelsInput.model_validate(data)

    def test_multiple_panels_valid(self):
        """Dict with 3 valid panels passes validation."""
        data = {
            "panels": [
                {"id": 1, "corners_pix": [[0, 0], [1, 0], [0.5, 1]]},
                {"id": 2, "corners_pix": [[2, 0], [3, 0], [2.5, 1]]},
                {"id": 3, "corners_pix": [[4, 0], [5, 0], [4.5, 1], [4.5, 0.5]]},
            ],
        }
        result = PanelsInput.model_validate(data)
        assert len(result.panels) == 3
