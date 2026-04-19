"""Pipeline run endpoints: POST /run-pipeline, GET /run/{run_id} (API-02)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from .schemas import PipelineRunCreated, PipelineRunRequest, PipelineRunStatus

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/run", status_code=202, response_model=PipelineRunCreated)
async def trigger_pipeline_run(body: PipelineRunRequest):
    """Trigger a full pipeline run for the given sample.

    Returns 202 Accepted with a run_id and status polling URL.
    Stub -- implementation in Plan 04.
    """
    raise HTTPException(status_code=501, detail="Not implemented -- see Plan 04")


@router.get("/run/{run_id}", response_model=PipelineRunStatus)
async def get_run_status(run_id: str):
    """Return the current status of a pipeline run.

    Stub -- implementation in Plan 04.
    """
    raise HTTPException(status_code=501, detail="Not implemented -- see Plan 04")
