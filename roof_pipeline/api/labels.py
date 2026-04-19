"""Label persistence endpoints: POST/GET /labels/{sampleId} (API-03, D-07).

Table schema is deferred to Phase 5 per D-07. This endpoint provides the
interface contract. Phase 5's labeling dashboard owns the table definition.

For Phase 4, the endpoint reads/writes to a `labels` table with columns:
  - sample_id (text, primary key or unique)
  - panels (jsonb -- the panel click data)
  - updated_at (timestamptz)

If the table doesn't exist yet, the endpoint returns a clear error.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from supabase import Client

from .deps import get_supabase
from .schemas import LabelData

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{sample_id}")
async def save_labels(
    sample_id: str,
    body: LabelData,
    request: Request,
    supabase: Client = Depends(get_supabase),
):
    """Persist panel label data for a sample (API-03).

    Upserts label data: if a row for sample_id exists, updates it.
    Otherwise inserts a new row. Round-trip preserves all vertex coordinates.
    """
    request.state.sample_id = sample_id

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "sample_id": sample_id,
        "panels": body.panels,
        "updated_at": now,
    }

    try:
        # Try upsert: insert or update on conflict
        supabase.table("labels").upsert(
            payload, on_conflict="sample_id",
        ).execute()
    except Exception as exc:
        log.error("Failed to save labels for sample %s: %s", sample_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save labels: {exc}",
        ) from exc

    log.info("saved labels for sample %s (%d panels)", sample_id, len(body.panels))
    return {"status": "saved", "sample_id": sample_id, "panel_count": len(body.panels)}


@router.get("/{sample_id}")
async def get_labels(
    sample_id: str,
    request: Request,
    supabase: Client = Depends(get_supabase),
):
    """Retrieve panel label data for a sample (API-03).

    Returns the stored panel data with all vertex coordinates preserved.
    Returns 404 if no labels exist for the sample.
    """
    request.state.sample_id = sample_id

    result = supabase.table("labels").select("*").eq("sample_id", sample_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail=f"No labels found for sample {sample_id}",
        )

    row = result.data[0]
    return LabelData(
        sample_id=row["sample_id"],
        panels=row["panels"],
    )
