"""Click-time corner check endpoint: POST /labels/{sample_id}/check-corner.

Why this exists:
  DSM is a Digital *Surface* Model — it includes vegetation. When a labeler
  places a panel corner on a tree, the DSM at that pixel reads canopy
  height instead of roof height. We don't want to wait until Save to tell
  the user; this endpoint runs the same compensation math used inside the
  pipeline (RANSAC plane fit + canopy-aware DSM sample) and returns a
  "looks like a tree" verdict + a suggested corrected elevation, so the
  labeler UI can pop a confirm dialog at click time.

Performance:
  Each call downloads the project's DSM from Supabase Storage. To keep
  per-click latency tolerable, we cache the last few DSMs in-process. A
  busy labeling session usually touches one project at a time, so a tiny
  FIFO cache is enough.

Fallbacks (in order of preference for `suggested_z`):
  1. Trained XGBoost elevation predictor (Phase 3) — if loaded.
  2. RANSAC plane prediction (panel has >=3 corners drawn).
  3. Robust window-percentile DSM sample (any time we have a DSM).
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Tuple

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from supabase import Client

from ..boundaries import _bilinear_sample, robust_dsm_sample
from ..planes import fit_plane_ransac
from .config import Settings
from .deps import Principal, get_settings, get_supabase, require_principal, verify_sample_access
from .hillshade import load_dsm
from .schemas import CheckCornerRequest, CheckCornerResponse

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Tiny per-process DSM cache
# ---------------------------------------------------------------------------
# Click-time UX hinges on this being fast. Without a cache, each click
# would trigger a Storage download (50-300ms). With a cache, only the
# first click on a project pays that cost; subsequent clicks reuse the
# numpy array. Sized small on purpose — labelers usually work on one
# project at a time, occasionally two; we don't need to remember more.
_DSM_CACHE: "OrderedDict[str, Tuple[np.ndarray, float]]" = OrderedDict()
_DSM_CACHE_MAX = 4


def _get_dsm_and_res(
    supabase: Client, settings: Settings, sample_id: str,
) -> tuple[np.ndarray, float]:
    """Return (dsm_array, meters_per_px) with FIFO caching keyed on sample_id."""
    if sample_id in _DSM_CACHE:
        _DSM_CACHE.move_to_end(sample_id)
        return _DSM_CACHE[sample_id]

    dsm = load_dsm(supabase, settings, sample_id)

    sample = (
        supabase.table("training_samples")
        .select("meters_per_px")
        .eq("id", sample_id)
        .execute()
    )
    res_m = 0.1
    if sample.data:
        try:
            res_m = float(sample.data[0].get("meters_per_px") or 0.1)
        except (TypeError, ValueError):
            res_m = 0.1

    _DSM_CACHE[sample_id] = (dsm, res_m)
    while len(_DSM_CACHE) > _DSM_CACHE_MAX:
        _DSM_CACHE.popitem(last=False)
    return dsm, res_m


def _evict_dsm_cache(sample_id: str) -> None:
    """Drop a cached DSM. Called when labels are saved with a new mask, etc."""
    _DSM_CACHE.pop(sample_id, None)


# ---------------------------------------------------------------------------
# Anomaly thresholds
# ---------------------------------------------------------------------------
# Match the per-save check in labels.py: a corner counts as anomalous when
# its residual against the panel plane exceeds BOTH 0.5 m absolute AND
# 3 * MAD. The absolute floor prevents false positives on very flat roofs
# where MAD is tiny; the MAD term scales with panel noise.
_ABS_THRESHOLD_M = 0.5
_MAD_K = 3.0
_LOCAL_STD_THRESHOLD_M = 0.4   # used only when we have <3 corners and can't fit a plane


def _check_against_plane(
    dsm: np.ndarray, res_m: float, col: float, row: float, panel_corners: list[list[float]],
) -> tuple[float | None, float | None, float | None]:
    """Return (plane_z, residual_m_against_plane, mad_z) or (None, None, None) if can't fit."""
    import cv2

    if len(panel_corners) < 3:
        return None, None, None
    h, w = dsm.shape
    corners_arr = np.asarray(panel_corners, dtype=np.float64)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [corners_arr.astype(np.int32)], 1)
    rs, cs = np.where(mask == 1)
    if rs.size < 12:
        return None, None, None
    zs = dsm[rs, cs]
    good = ~np.isnan(zs)
    if good.sum() < 12:
        return None, None, None
    rs, cs, zs = rs[good], cs[good], zs[good]
    pts = np.stack([cs * res_m, -rs * res_m, zs], axis=1).astype(np.float64)
    try:
        plane = fit_plane_ransac(pts)
    except ValueError:
        return None, None, None

    nx, ny, nz = plane.normal
    if abs(nz) < 1e-9:
        return None, None, None
    plane_z = float((plane.d - nx * (col * res_m) - ny * (-row * res_m)) / nz)

    # MAD over per-corner residuals (so threshold scales with panel noise).
    cor = corners_arr
    cxs = cor[:, 0] * res_m
    cys = -cor[:, 1] * res_m
    cz_raw = robust_dsm_sample(dsm, cor[:, 0], cor[:, 1])
    cz_pred = (plane.d - nx * cxs - ny * cys) / nz
    abs_residuals = np.abs(cz_raw - cz_pred)
    mad = float(np.median(np.abs(abs_residuals - np.median(abs_residuals))))
    return plane_z, abs(robust_dsm_sample(dsm, np.array([col]), np.array([row]))[0] - plane_z), mad


def _local_std(dsm: np.ndarray, col: float, row: float, window: int = 5) -> float:
    """Local DSM std-dev around the click — canopy-edge signature."""
    h, w = dsm.shape
    half = window // 2
    c0 = max(0, int(round(col)) - half)
    c1 = min(w, int(round(col)) + half + 1)
    r0 = max(0, int(round(row)) - half)
    r1 = min(h, int(round(row)) + half + 1)
    patch = dsm[r0:r1, c0:c1]
    valid = patch[~np.isnan(patch)] if patch.size else patch
    if valid.size < 4:
        return 0.0
    return float(np.std(valid))


def _try_nn_predictor(features: dict) -> float | None:
    """Optional XGBoost elevation predictor. Returns None if model not loaded."""
    try:
        from ..elevation_predictor.predict import predict_corner_z, predictor_available
    except Exception:
        return None
    if not predictor_available():
        return None
    try:
        result = predict_corner_z(features)
    except Exception as exc:
        log.warning("elevation_predictor failed: %s", exc)
        return None
    if result is None:
        return None
    z, _confidence = result
    return float(z)


def _do_check(
    sample_id: str,
    body: CheckCornerRequest,
    supabase: Client,
    settings: Settings,
) -> CheckCornerResponse:
    """Synchronous check implementation — runs in a worker thread."""
    dsm, res_m = _get_dsm_and_res(supabase, settings, sample_id)

    col_arr = np.array([body.col], dtype=np.float64)
    row_arr = np.array([body.row], dtype=np.float64)
    dsm_z_bilinear = float(_bilinear_sample(dsm, col_arr, row_arr)[0])
    dsm_z_robust = float(robust_dsm_sample(dsm, col_arr, row_arr)[0])

    plane_z, residual_against_plane, mad = _check_against_plane(
        dsm, res_m, body.col, body.row, body.panel_corners,
    )

    # Optional NN prediction. Built around the panel-plane features the
    # extraction script writes to the training CSV. If the predictor isn't
    # loaded, this returns None and we keep the plane prediction.
    nn_z: float | None = None
    if plane_z is not None:
        local_std_value = _local_std(dsm, body.col, body.row)
        siblings_z = []
        for i, c in enumerate(body.panel_corners):
            if i == body.corner_idx:
                continue
            siblings_z.append(
                float(_bilinear_sample(
                    dsm, np.array([c[0]]), np.array([c[1]]),
                )[0])
            )
        siblings_arr = np.array(siblings_z) if siblings_z else np.array([dsm_z_bilinear])
        features = {
            "col_px": body.col,
            "row_px": body.row,
            "panel_corner_count": len(body.panel_corners),
            "patch_mean": dsm_z_bilinear,  # not perfect but cheap; train script gets the real one
            "patch_std": local_std_value,
            "patch_min": dsm_z_robust,
            "patch_p20": dsm_z_robust,
            "patch_p50": dsm_z_bilinear,
            "patch_p80": dsm_z_bilinear,
            "patch_max": dsm_z_bilinear,
            "dsm_z_bilinear": dsm_z_bilinear,
            "dsm_z_robust": dsm_z_robust,
            "plane_normal_x": 0.0,  # filled below if we can extract
            "plane_normal_y": 0.0,
            "plane_normal_z": 1.0,
            "plane_d": plane_z,
            "plane_rms_residual": 0.0,
            "siblings_z_median": float(np.median(siblings_arr)),
            "siblings_z_std": float(np.std(siblings_arr)),
            "meters_per_px": res_m,
        }
        nn_z = _try_nn_predictor(features)

    # Decide suggested_z + anomaly verdict.
    suggested_z: float
    source: str
    is_anomalous: bool

    if nn_z is not None and plane_z is not None:
        suggested_z = nn_z
        source = "nn"
        is_anomalous = (
            abs(dsm_z_bilinear - suggested_z) > _ABS_THRESHOLD_M
            and (residual_against_plane is None or residual_against_plane > _ABS_THRESHOLD_M)
        )
    elif plane_z is not None and residual_against_plane is not None and mad is not None:
        suggested_z = plane_z
        source = "plane"
        threshold = max(_ABS_THRESHOLD_M, _MAD_K * mad if mad > 1e-6 else _ABS_THRESHOLD_M)
        is_anomalous = residual_against_plane > threshold
    else:
        # No plane fit possible — fall back to local-patch heuristic.
        suggested_z = dsm_z_robust
        source = "robust_sample"
        is_anomalous = (
            _local_std(dsm, body.col, body.row) > _LOCAL_STD_THRESHOLD_M
            and abs(dsm_z_bilinear - dsm_z_robust) > _ABS_THRESHOLD_M
        )

    residual_m = float(abs(dsm_z_bilinear - suggested_z))

    return CheckCornerResponse(
        dsm_z_bilinear=dsm_z_bilinear,
        dsm_z_robust=dsm_z_robust,
        plane_z=plane_z,
        nn_z=nn_z,
        suggested_z=float(suggested_z),
        source=source,
        is_anomalous=bool(is_anomalous),
        residual_m=residual_m,
    )


@router.post("/{sample_id}/check-corner", response_model=CheckCornerResponse)
async def check_corner(
    sample_id: str,
    body: CheckCornerRequest,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
):
    """Click-time DSM-aware corner check (live UX path)."""
    request.state.sample_id = sample_id
    verify_sample_access(principal, sample_id, supabase)
    try:
        return await asyncio.to_thread(_do_check, sample_id, body, supabase, settings)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("check-corner skipped for %s: %s", sample_id, exc)
        # Soft failure: pretend nothing's wrong so the UX doesn't block on infra.
        # Better to miss a flag than to spam errors at every click.
        return CheckCornerResponse(
            dsm_z_bilinear=0.0,
            dsm_z_robust=0.0,
            plane_z=None,
            nn_z=None,
            suggested_z=0.0,
            source="error",
            is_anomalous=False,
            residual_m=0.0,
        )
