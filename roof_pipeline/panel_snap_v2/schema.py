"""Pydantic input validation schema for panel click data (VALID-01, D-07).

Single source of truth for both CLI (polygons_from_clicks) and future
HTTP API (Milestone 2 FastAPI). Lives in panel_snap_v2 per D-08.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class PanelCorners(BaseModel):
    """One panel's click data: integer ID and list of [col_px, row_px] corners."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: int
    corners_pix: list[list[float]]

    @field_validator("corners_pix")
    @classmethod
    def at_least_three_corners(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError(
                f"need >= 3 corners to form a polygon, got {len(v)}"
            )
        return v


class PanelsInput(BaseModel):
    """Top-level input: list of panels with click coordinates."""

    model_config = ConfigDict(strict=True, extra="forbid")

    panels: list[PanelCorners]
