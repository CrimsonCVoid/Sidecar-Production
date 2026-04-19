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


class TestDuplicateCornerDedup:
    """LABEL-01: Silent close-polygon duplicate-corner removal (D-01, D-02, D-03)."""

    def test_duplicate_last_corner_stripped(self):
        """Exact duplicate last corner (first == last) is silently removed.

        Covers the matplotlib double-click auto-close bug: labeler appends the
        first corner again as the last vertex. After PanelCorners validation
        the duplicate must be gone so downstream geometry sees 3 clean edges.
        """
        # 4 corners, last == first
        corners = [[0, 0], [1, 0], [0.5, 1], [0, 0]]
        panel = PanelCorners(id=1, corners_pix=corners)
        assert len(panel.corners_pix) == 3
        assert panel.corners_pix == [[0, 0], [1, 0], [0.5, 1]]

    def test_near_duplicate_last_corner_stripped(self):
        """Last corner within 0.5 pixel of first is treated as duplicate and removed.

        Accounts for sub-pixel rounding in the labeler: the final auto-close
        click is 0.001 px away from the first, not exactly equal.
        """
        # last is within 0.5 pixel of first
        corners = [[0, 0], [100, 0], [50, 100], [0.001, 0.001]]
        panel = PanelCorners(id=1, corners_pix=corners)
        assert len(panel.corners_pix) == 3
        assert panel.corners_pix[0] == [0, 0]
        assert panel.corners_pix[-1] == [50, 100]

    def test_no_false_positive_dedup(self):
        """Last corner far from first is NOT stripped (no false positive).

        A legitimate 4-corner panel whose last vertex happens to be distinct
        from the first must pass through with all 4 corners intact.
        """
        # last != first (0.5, 0) is well away from first (0, 0)
        corners = [[0, 0], [1, 0], [0.5, 1], [0.5, 0]]
        panel = PanelCorners(id=1, corners_pix=corners)
        assert len(panel.corners_pix) == 4

    def test_dedup_still_requires_three_corners(self):
        """Dedup reducing polygon below 3 corners triggers at_least_three_corners error.

        Input: 3 corners, last == first. After dedup: 2 corners. The count
        validator must then reject with '3 corners' message.
        """
        corners = [[0, 0], [1, 0], [0, 0]]  # 3 corners, last == first
        with pytest.raises(ValidationError, match="3 corners"):
            PanelCorners(id=1, corners_pix=corners)

    def test_dedup_via_panels_input(self):
        """Full PanelsInput.model_validate succeeds on panel with duplicate last corner.

        Verifies the dedup works through the full schema path (the same path
        polygons_from_clicks uses at the input boundary).
        """
        data = {
            "panels": [
                # panel 1: clean polygon (no duplicate)
                {"id": 1, "corners_pix": [[0, 0], [1, 0], [0.5, 1]]},
                # panel 2: duplicate last corner from matplotlib auto-close
                {"id": 2, "corners_pix": [[2, 0], [3, 0], [2.5, 1], [2, 0]]},
            ],
        }
        result = PanelsInput.model_validate(data)
        assert len(result.panels) == 2
        # panel 1 unchanged
        assert len(result.panels[0].corners_pix) == 3
        # panel 2 deduplicated
        assert len(result.panels[1].corners_pix) == 3
        assert result.panels[1].corners_pix[-1] == [2.5, 1]
