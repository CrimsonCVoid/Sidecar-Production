"""Pydantic response models for the FastAPI sidecar endpoints."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snap preview (API-01)
# ---------------------------------------------------------------------------

class FeatureNode(BaseModel):
    """One feature in the snap feature graph."""

    id: int
    valence: int
    position_xyz: list[float] | None
    panel_ids: list[int]


class FeatureEdge(BaseModel):
    """One edge in the snap feature graph."""

    panel_a: int
    panel_b: int
    feature_ids: list[int]


class SnapPreviewResponse(BaseModel):
    """Response from POST /snap-preview (API-01)."""

    feature_graph: dict  # {features: [...], edges: [...]}
    snapped_polygons: dict[str, list[list[float]]]  # panel_id -> [[x,y,z],...]


# ---------------------------------------------------------------------------
# Pipeline run (API-02)
# ---------------------------------------------------------------------------

class PipelineRunRequest(BaseModel):
    """Request body for POST /run-pipeline."""

    model_config = ConfigDict(strict=True, extra="forbid")

    sample_id: str
    snap_tol: float = 1.0
    use_snap_v2: bool = True
    project_name: str = "ROOF PROTOTYPE"
    project_address: str = "ADDRESS UNKNOWN"
    coverage_in: float = 24.0
    profile: str = "SV"
    waste_pct: float = 11.0


class PipelineRunCreated(BaseModel):
    """Response from POST /run-pipeline (API-02, D-09)."""

    run_id: str
    status_url: str


class PipelineRunStatus(BaseModel):
    """Response from GET /run/{run_id} (API-02)."""

    id: str
    sample_id: str
    status: str  # queued | running | done | error
    stage_name: str | None = None
    progress_pct: int = 0
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


# ---------------------------------------------------------------------------
# Labels (API-03, D-07 stub)
# ---------------------------------------------------------------------------

class FlaggedCorner(BaseModel):
    """One panel corner whose Z is suspect after DSM-aware checks.

    DSMs include vegetation; a corner that lands on a tree reads canopy
    height, which throws off downstream cut sheets. We surface these so
    the labeling UI can highlight them for review. Not an error — the
    save still succeeds.
    """

    panel_id: int
    corner_idx: int
    residual_m: float
    reason: str  # "canopy" | "plane_outlier"


class LabelData(BaseModel):
    """Panel label data for POST/GET /labels/{sampleId} (API-03, D-07 stub)."""

    sample_id: str
    panels: list[dict]  # Schema TBD per D-07, Phase 5 owns
    flagged_corners: list[FlaggedCorner] = []


class SaveLabelsResponse(BaseModel):
    """Response from POST /labels/{sampleId}."""

    status: str
    sample_id: str
    panel_count: int
    flagged_corners: list[FlaggedCorner] = []


# ---------------------------------------------------------------------------
# Shared error shape
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Standard error response shape."""

    error_type: str
    message: str
    trace_id: str | None = None
