"""Label persistence endpoints: POST/GET /labels/{sampleId} (API-03, D-07 stub)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from .schemas import LabelData

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{sample_id}")
async def save_labels(sample_id: str, body: LabelData):
    """Persist panel label data for a sample.

    Stub -- implementation in Plan 04.
    """
    raise HTTPException(status_code=501, detail="Not implemented -- see Plan 04")


@router.get("/{sample_id}")
async def get_labels(sample_id: str):
    """Retrieve panel label data for a sample.

    Stub -- implementation in Plan 04.
    """
    raise HTTPException(status_code=501, detail="Not implemented -- see Plan 04")
