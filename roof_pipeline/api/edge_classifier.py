"""Phase 4: edge-classifier ops + on-demand inference surface.

  GET  /api/v2/edge-classifier/health           → load + predict stats
  POST /api/v2/edge-classifier/suggest/{sample_id}
                                               → on-demand predictions for the
                                                 panels saved on a sample, used
                                                 by the test-only "Suggest edge
                                                 types" button.

Auth: ``require_principal`` (internal key or Supabase JWT).
The /suggest route bypasses EDGE_CLASSIFIER_ENABLED so the model can
run on demand even when the prod cutsheet path has it off.
"""

from __future__ import annotations

import json
import logging
import tempfile
from io import BytesIO
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from supabase import Client

from ..edge_classifier import classifier_health
from ..edge_classifier.predict import predict_edges
from .config import Settings
from .deps import (
    Principal,
    get_settings,
    get_supabase,
    require_principal,
    verify_sample_access,
)

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def get_health(
    _principal: Principal = Depends(require_principal),
) -> dict:
    """Snapshot of the edge classifier's load + per-process prediction
    stats. Counters reset on process restart. Either auth path
    (internal API key or Supabase JWT) is accepted — ops dashboards use
    the JWT path, the web v2 proxy uses the shared secret."""
    return classifier_health()


@router.post("/suggest/{sample_id}")
async def suggest_edges(
    sample_id: str,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
) -> dict:
    """On-demand edge-type suggestions for a project's saved panels.

    Steps:
      1. Auth + tenant gate (read_only=True so capturers can call it too).
      2. Pull saved panels from training_labels.annotations.panels.
      3. Download DSM, rasterize the panels onto a uint8 mask, fit
         planes, lift clicks to plane-projected 3D polygons. Same
         prep the training-data extractor does.
      4. For each panel, call predict_edges(force=True) — bypasses the
         EDGE_CLASSIFIER_ENABLED gate so this works even when prod
         cutsheets have the classifier turned off.
      5. Return per-edge (suggested label, confidence) keyed on
         (panel_id, edge_index). Caller (the website) is responsible
         for the test-account allowlist; this route is gated only on
         project access, not on identity.

    Response:
      {
        "loaded": bool,
        "suggestions": [
          {
            "panel_id": int,
            "edge_index": int,
            "suggested_label": str | null,   # null when below confidence threshold
            "confidence": float
          },
          ...
        ]
      }
    """
    request.state.sample_id = sample_id
    verify_sample_access(principal, sample_id, supabase, read_only=True)

    # Local imports — keep top-of-file lean for the health endpoint.
    import cv2
    import rasterio
    from ..planes import fit_all_panels
    from ..boundaries import polygons_from_clicks
    from ..edge_classifier.predict import load_model

    # 1. Load saved panels
    label_row = (
        supabase.table("training_labels")
        .select("annotations")
        .eq("sample_id", sample_id)
        .execute()
    )
    if not label_row.data:
        raise HTTPException(status_code=404, detail="No saved labels for this project")
    panels = (label_row.data[0].get("annotations") or {}).get("panels") or []
    if not panels:
        raise HTTPException(
            status_code=400, detail="Project has no panels — draw some in the Labeler first."
        )

    # 2. Sample metadata + DSM
    sample_row = (
        supabase.table("training_samples")
        .select("dsm_storage_path, meters_per_px")
        .eq("id", sample_id)
        .execute()
    )
    if not sample_row.data:
        raise HTTPException(status_code=404, detail="Sample row not found")
    dsm_path = sample_row.data[0].get("dsm_storage_path")
    res_m = float(sample_row.data[0].get("meters_per_px") or 0.1)
    if not dsm_path:
        raise HTTPException(status_code=400, detail="Project has no DSM yet")

    dsm_bytes = None
    for bucket in (settings.training_bucket, settings.storage_bucket):
        try:
            dsm_bytes = supabase.storage.from_(bucket).download(dsm_path)
            break
        except Exception:
            continue
    if dsm_bytes is None:
        raise HTTPException(status_code=502, detail="Could not download DSM from storage")

    with rasterio.open(BytesIO(dsm_bytes)) as ds:
        dsm = ds.read(1).astype("float32")
    h, w = dsm.shape

    # 3. Rasterize + fit planes + lift to 3D polygons
    mask = np.zeros((h, w), dtype="uint8")
    panels_json = []
    for i, p in enumerate(panels):
        pid = i + 1
        corners = p.get("corners_pix") or []
        if len(corners) < 3:
            continue
        cv2.fillPoly(mask, [np.asarray(corners, dtype=np.int32)], pid)
        panels_json.append({**p, "id": pid})
    if not panels_json:
        raise HTTPException(status_code=400, detail="No panel has ≥3 corners")

    planes = fit_all_panels(dsm, mask, res_m)
    if not planes:
        raise HTTPException(status_code=500, detail="Plane fitting produced no results")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tf:
        json.dump({"panels": panels_json}, tf)
        tf_path = Path(tf.name)
    try:
        polygons_3d = polygons_from_clicks(tf_path, dsm, res_m, planes)
    finally:
        try:
            tf_path.unlink()
        except OSError:
            pass

    # 4. Force-load (idempotent) + per-panel predictions
    if not load_model():
        raise HTTPException(
            status_code=503,
            detail="Edge classifier model not available on this sidecar build.",
        )

    suggestions: list[dict] = []
    for pid, poly3d in polygons_3d.items():
        plane = planes.get(pid)
        if plane is None:
            continue
        preds = predict_edges(
            pid=pid,
            poly=poly3d,
            plane=plane,
            polygons=polygons_3d,
            planes=planes,
            sample_id=sample_id,
            force=True,
        )
        if preds is None:
            continue
        for edge_index, item in enumerate(preds):
            label, conf = item if item is not None else (None, 0.0)
            suggestions.append(
                {
                    "panel_id": pid,
                    "edge_index": edge_index,
                    "suggested_label": label,
                    "confidence": round(float(conf), 3),
                }
            )

    log.info(
        "edge-classifier.suggest sample=%s panels=%d edges=%d",
        sample_id, len(polygons_3d), len(suggestions),
    )
    return {"loaded": True, "suggestions": suggestions}
