"""Label persistence endpoints: POST/GET /labels/{sampleId} (API-03).

Uses the training_labels table with schema:
  - id (uuid, auto)
  - sample_id (uuid, FK to training_samples)
  - labeled_by (uuid, nullable)
  - annotations (jsonb -- the panel click data + cached flagged_corners)
  - status (text: complete|skipped|flagged|in_progress)
  - duration_ms (int, nullable)
  - notes (text, nullable)
  - created_at, updated_at (timestamptz)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from supabase import Client

from ..boundaries import _bilinear_sample, buffered_panel_mask, robust_dsm_sample
from ..planes import fit_plane_ransac
from .config import Settings
from .deps import Principal, get_settings, get_supabase, require_principal, verify_sample_access
from .hillshade import load_dsm
from .schemas import FlaggedCorner, LabelData, SaveLabelsResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _check_panel_corners(
    panels: list[dict],
    dsm: np.ndarray,
    res_m: float,
    *,
    abs_threshold_m: float = 0.5,
    mad_k: float = 3.0,
) -> list[FlaggedCorner]:
    """Per-panel: rasterize, RANSAC plane-fit, flag corners with high residual.

    A corner is flagged when it sits more than ``abs_threshold_m`` AND more
    than ``mad_k * MAD`` off the panel's robust plane. The MAD floor catches
    the easy cases (corner in a tree); the absolute floor avoids false
    positives on a panel that happens to be very flat (tiny MAD inflates
    the relative threshold).

    Honors a per-panel ``corner_z_overrides`` array (when the labeler's
    Auto Correct accepted a system suggestion, that corner is taken as
    user-confirmed and is NOT flagged again on the next save).
    """
    h, w = dsm.shape
    flagged: list[FlaggedCorner] = []

    # Optional in-process import. Falls back to plane prediction when the
    # XGBoost artifact isn't loaded.
    try:
        from ..elevation_predictor.predict import predict_corner_z, predictor_available
    except Exception:
        predict_corner_z = None  # type: ignore
        predictor_available = lambda: False  # type: ignore

    for panel in panels:
        pid = int(panel.get("id", 0))
        corners = panel.get("corners_pix") or []
        if len(corners) < 3:
            continue
        corners_arr = np.asarray(corners, dtype=np.float64)
        cols = corners_arr[:, 0]
        rows = corners_arr[:, 1]

        # Per-corner overrides (length matches corners, missing/null = no override)
        overrides_raw = panel.get("corner_z_overrides") or []
        has_override = [
            i < len(overrides_raw) and overrides_raw[i] is not None
            for i in range(len(corners))
        ]

        # Rasterize this single panel and erode inward by 30 cm so the
        # plane fit ignores ridge-cap / gutter / adjacent-face bleed.
        mask = buffered_panel_mask(corners_arr, (h, w), res_m, buffer_m=0.30)
        rs, cs = np.where(mask == 1)
        if rs.size < 12:
            continue
        zs = dsm[rs, cs]
        good = ~np.isnan(zs)
        if good.sum() < 12:
            continue
        rs, cs, zs = rs[good], cs[good], zs[good]
        pts = np.stack([cs * res_m, -rs * res_m, zs], axis=1).astype(np.float64)
        try:
            plane = fit_plane_ransac(pts)
        except ValueError:
            continue

        # Sample DSM at each clicked corner with the canopy-aware sampler,
        # then compare to the plane prediction at that XY.
        z_dsm_bilinear = _bilinear_sample(dsm, cols, rows)
        z_samples = robust_dsm_sample(dsm, cols, rows)
        nx, ny, nz = plane.normal
        if abs(nz) < 1e-9:
            continue
        xs_m = cols * res_m
        ys_m = -rows * res_m
        z_plane = (plane.d - nx * xs_m - ny * ys_m) / nz
        residuals = z_samples - z_plane
        abs_residuals = np.abs(residuals)
        mad = float(np.median(np.abs(abs_residuals - np.median(abs_residuals))))
        rel_threshold = mad_k * (mad if mad > 1e-6 else abs_threshold_m)
        threshold = max(abs_threshold_m, rel_threshold)

        # If the trained predictor is loaded, prefer its suggestion; otherwise
        # fall back to the plane prediction.
        nn_loaded = bool(predictor_available()) if predict_corner_z else False

        for idx, r_signed in enumerate(residuals):
            if abs(r_signed) <= threshold:
                continue
            if has_override[idx]:
                # User already accepted a system suggestion for this corner.
                # Don't re-nag.
                continue
            reason = "canopy" if r_signed > 0 else "plane_outlier"

            # Compute suggested_z. Plane prediction is the safe default; the
            # NN can refine it on tree clicks where sibling-corner stats
            # carry more signal than the plane fit alone.
            suggested_z = float(z_plane[idx])
            if nn_loaded and predict_corner_z is not None:
                # Build the same feature dict the click-time endpoint uses.
                siblings = [
                    float(z_dsm_bilinear[j])
                    for j in range(len(corners))
                    if j != idx
                ]
                siblings_arr = np.array(siblings) if siblings else np.array([float(z_dsm_bilinear[idx])])
                feats = {
                    "col_px": float(cols[idx]),
                    "row_px": float(rows[idx]),
                    "panel_corner_count": len(corners),
                    "patch_mean": float(z_dsm_bilinear[idx]),
                    "patch_std": float(abs(r_signed)),
                    "patch_min": float(z_samples[idx]),
                    "patch_p20": float(z_samples[idx]),
                    "patch_p50": float(z_dsm_bilinear[idx]),
                    "patch_p80": float(z_dsm_bilinear[idx]),
                    "patch_max": float(z_dsm_bilinear[idx]),
                    "dsm_z_bilinear": float(z_dsm_bilinear[idx]),
                    "dsm_z_robust": float(z_samples[idx]),
                    "siblings_z_median": float(np.median(siblings_arr)),
                    "siblings_z_std": float(np.std(siblings_arr)),
                    "meters_per_px": res_m,
                }
                try:
                    nn_result = predict_corner_z(feats)
                except Exception:
                    nn_result = None
                if nn_result is not None:
                    suggested_z = float(nn_result[0])

            flagged.append(FlaggedCorner(
                panel_id=pid,
                corner_idx=idx,
                residual_m=float(abs(r_signed)),
                reason=reason,
                dsm_z=float(z_dsm_bilinear[idx]),
                suggested_z=suggested_z,
            ))

    return flagged


def _validate_corners_best_effort(
    sample_id: str,
    panels: list[dict],
    supabase: Client,
    settings: Settings,
) -> list[FlaggedCorner]:
    """Run the corner-height check; swallow failures and return [] on error.

    Reasons the check might fail: DSM not yet uploaded, sample row missing,
    storage hiccup, OpenCV not installed in this image. The save itself has
    already succeeded by the time this runs, so a failure here just means
    the UI doesn't get flag highlights — never that labels are lost.
    """
    try:
        result = (
            supabase.table("training_samples")
            .select("meters_per_px")
            .eq("id", sample_id)
            .execute()
        )
        row = result.data[0] if result.data else {}
        res_m = float(row.get("meters_per_px") or 0.1)
        dsm = load_dsm(supabase, settings, sample_id)
        return _check_panel_corners(panels, dsm, res_m)
    except Exception as exc:
        log.warning("corner check skipped for %s: %s", sample_id, exc)
        return []


@router.post("/{sample_id}", response_model=SaveLabelsResponse)
async def save_labels(
    sample_id: str,
    body: LabelData,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
):
    """Persist panel label data for a sample (API-03).

    Upserts into training_labels and returns any DSM-flagged corners so the
    labeling UI can surface them for review.
    """
    request.state.sample_id = sample_id
    verify_sample_access(principal, sample_id, supabase)

    # Run the DSM corner-height check off the event loop. Best-effort:
    # never fails the save. If it returns flags on >=2 corners of any
    # panel, we mark status="flagged" so the dashboard can surface the
    # row; otherwise status stays "complete".
    flagged = await asyncio.to_thread(
        _validate_corners_best_effort, sample_id, body.panels, supabase, settings
    )
    flag_dump = [f.model_dump() for f in flagged]
    counts: dict[int, int] = {}
    for f in flagged:
        counts[f.panel_id] = counts.get(f.panel_id, 0) + 1
    has_panel_with_two_plus = any(c >= 2 for c in counts.values())
    status_value = "flagged" if has_panel_with_two_plus else "complete"

    now = datetime.now(timezone.utc).isoformat()

    try:
        existing = (
            supabase.table("training_labels")
            .select("id")
            .eq("sample_id", sample_id)
            .execute()
        )

        annotations_payload = {
            "panels": body.panels,
            "flagged_corners": flag_dump,
        }

        if existing.data:
            supabase.table("training_labels").update({
                "annotations": annotations_payload,
                "status": status_value,
                "updated_at": now,
            }).eq("sample_id", sample_id).execute()
        else:
            supabase.table("training_labels").insert({
                "sample_id": sample_id,
                "annotations": annotations_payload,
                "status": status_value,
            }).execute()

    except Exception as exc:
        log.error("Failed to save labels for sample %s: %s", sample_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save labels: {exc}",
        ) from exc

    log.info(
        "saved labels for sample %s (%d panels, %d flagged corners, status=%s)",
        sample_id, len(body.panels), len(flagged), status_value,
    )
    return SaveLabelsResponse(
        status="saved",
        sample_id=sample_id,
        panel_count=len(body.panels),
        flagged_corners=flagged,
    )


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
    # read_only=True so training capturers (migration 028) can load existing
    # labels for any sample to seed their scratch editor view. Mutate path
    # (POST /labels) stays strict.
    verify_sample_access(principal, sample_id, supabase, read_only=True)

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
    cached_flags = annotations.get("flagged_corners") or []
    flagged_models: list[FlaggedCorner] = []
    for f in cached_flags:
        try:
            flagged_models.append(FlaggedCorner.model_validate(f))
        except Exception:
            continue
    return LabelData(
        sample_id=row["sample_id"],
        panels=panels,
        flagged_corners=flagged_models,
    )
