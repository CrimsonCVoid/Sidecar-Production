"""Snap preview endpoint: POST /snap-preview (API-01)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from roof_pipeline.panel_snap_v2.schema import PanelsInput

from .schemas import SnapPreviewResponse

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/preview", response_model=SnapPreviewResponse)
async def snap_preview(body: PanelsInput):
    """Return the snap feature graph and snapped polygon coordinates.

    Stub -- implementation in Plan 03.
    """
    raise HTTPException(status_code=501, detail="Not implemented -- see Plan 03")
