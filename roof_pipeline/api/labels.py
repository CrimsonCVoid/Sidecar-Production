"""Label persistence endpoints: POST/GET /labels/{sampleId} (API-03).

Uses the training_labels table with schema:
  - id (uuid, auto)
  - sample_id (uuid, FK to training_samples)
  - labeled_by (uuid, nullable)
  - annotations (jsonb -- the panel click data)
  - status (text: complete|skipped|flagged|in_progress)
  - duration_ms (int, nullable)
  - notes (text, nullable)
  - created_at, updated_at (timestamptz)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from supabase import Client

from .deps import Principal, get_supabase, require_principal, verify_sample_access
from .schemas import LabelData

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{sample_id}")
async def save_labels(
    sample_id: str,
    body: LabelData,
    request: Request,
    supabase: Client = Depends(get_supabase),
    principal: Principal = Depends(require_principal),
):
    """Persist panel label data for a sample (API-03).

    Upserts into training_labels: stores panels as annotations jsonb.
    """
    request.state.sample_id = sample_id
    verify_sample_access(principal, sample_id, supabase)

    now = datetime.now(timezone.utc).isoformat()

    try:
        # Check if a label row already exists for this sample
        existing = (
            supabase.table("training_labels")
            .select("id")
            .eq("sample_id", sample_id)
            .execute()
        )

        if existing.data:
            # Update existing row
            supabase.table("training_labels").update({
                "annotations": {"panels": body.panels},
                "status": "complete",
                "updated_at": now,
            }).eq("sample_id", sample_id).execute()
        else:
            # Insert new row
            supabase.table("training_labels").insert({
                "sample_id": sample_id,
                "annotations": {"panels": body.panels},
                "status": "complete",
            }).execute()

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
    principal: Principal = Depends(require_principal),
):
    """Retrieve panel label data for a sample (API-03).

    Reads annotations jsonb from training_labels and returns as LabelData.
    Returns 404 if no labels exist for the sample.
    """
    request.state.sample_id = sample_id
    verify_sample_access(principal, sample_id, supabase)

    result = (
        supabase.table("training_labels")
        .select("*")
        .eq("sample_id", sample_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail=f"No labels found for sample {sample_id}",
        )

    row = result.data[0]
    annotations = row.get("annotations") or {}
    panels = annotations.get("panels", [])
    return LabelData(
        sample_id=row["sample_id"],
        panels=panels,
    )
