"""Pydantic input validation schema for panel click data (VALID-01, D-07).

Single source of truth for both CLI (polygons_from_clicks) and future
HTTP API (Milestone 2 FastAPI). Lives in panel_snap_v2 per D-08.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, field_validator

log = logging.getLogger(__name__)


class PanelCorners(BaseModel):
    """One panel's click data: integer ID and list of [col_px, row_px] corners."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: int
    corners_pix: list[list[float]]

    @field_validator("corners_pix")
    @classmethod
    def strip_close_polygon_duplicate(cls, v: list[list[float]]) -> list[list[float]]:
        """Strip duplicate last corner if it matches the first (D-01, D-02, D-03).

        The matplotlib labeler's double-click auto-close produces mask.json files
        where the last corner duplicates the first. This silently removes it.
        Only strips the LAST corner, and only if it matches the FIRST within
        a small pixel-space tolerance. Does NOT strip all consecutive duplicates.
        """
        if len(v) < 2:
            return v
        first = v[0]
        last = v[-1]
        dist_sq = sum((a - b) ** 2 for a, b in zip(first, last))
        if dist_sq < 0.5 ** 2:  # 0.5 pixel tolerance
            log.debug(
                "stripped duplicate close-polygon corner (dist=%.4f px)",
                dist_sq ** 0.5,
            )
            return v[:-1]
        return v

    @field_validator("corners_pix")
    @classmethod
    def at_least_three_corners(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError(
                f"need >= 3 corners to form a polygon, got {len(v)}"
            )
        return v


class PanelsInput(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    panels: list[PanelCorners]
    res_m: float | None = None
    shape: list[int] | None = None
    panel_count: int | None = None
    panel_pixel_counts: dict[str, int] | None = None
