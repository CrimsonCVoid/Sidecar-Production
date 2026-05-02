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

    # extra="forbid" was rejecting the optional edge_types array the
    # frontend sends per panel. Switched to "ignore" so additional
    # fields the labeler tacks on (edge_types, future per-panel
    # metadata) don't 422 the whole pipeline run.
    model_config = ConfigDict(strict=True, extra="ignore")

    id: int
    corners_pix: list[list[float]]
    # Frontend EdgeType strings, lowercase, length == len(corners_pix).
    # Threaded through to roof_dict_from_pipeline by run_real.py so the
    # shop-drawing PDF uses the user's labels instead of the geometric
    # classifier. Optional and ignored when not present.
    edge_types: list[str] | None = None
    # Per-corner z override in meters, length matches corners_pix when set.
    # Populated by the labeler's "Auto Correct" path: when a corner was
    # flagged as canopy-contaminated, the user can accept the system's
    # suggested z and we ship that value through to the pipeline so
    # plane fitting and edge length use the corrected elevation rather
    # than the raw bilinear DSM read. None inside the array = no
    # override for that index.
    corner_z_overrides: list[float | None] | None = None
    # Match this face's sheet run direction to another face's resolved
    # run direction. Set when the auto-resolver picks the wrong axis on
    # a face that should obviously align with a sibling (typical case:
    # two parallel slopes meeting at a ridge — they should run the same
    # way). The pipeline runs the resolver normally for every panel
    # first, then in a post-pass copies the resolved run_dir from the
    # referenced panel onto any panel that names it here.
    match_run_with_panel_id: int | None = None

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
    # Same rationale as PanelCorners: tolerate forward-compatible
    # extras instead of 422'ing the whole pipeline run.
    model_config = ConfigDict(strict=True, extra='ignore')

    panels: list[PanelCorners]
    res_m: float | None = None
    shape: list[int] | None = None
    panel_count: int | None = None
    panel_pixel_counts: dict[str, int] | None = None
