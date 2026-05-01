"""SAM inference service — model load + per-sample auto-panel generation.

Module-scope model cache: the FastAPI app holds exactly one SAM ViT-H
instance for the life of the process. ~2.4 GB checkpoint, ~24 GB GPU
resident at inference time. Don't share with the existing mmr-api
process — that's enforced by the systemd unit.

Pipeline:
  1. Pull training_samples row (footprint, RGB path, image meta).
  2. Project footprint -> pixel space (footprint_projection.py).
  3. Crop image to footprint bbox + margin so SAM doesn't waste
     compute on the lawn.
  4. SamAutomaticMaskGenerator on the crop.
  5. Filter masks: drop tiny, drop ones with <80% area inside footprint.
  6. cv2.findContours + approxPolyDP(epsilon=2) per mask -> polygon.
  7. Translate crop-local pixel coords back to full-image coords.
  8. Write the resulting list to training_samples.auto_panels and
     update the timestamp / model_version columns.

Telemetry: auto_panels.generated on success, auto_panels.fallback when
the run is short-circuited (no footprint, missing RGB, model load
failed). Always uses the existing roof_pipeline.telemetry helper so
events land in pipeline_events alongside Phase 1's footprint events.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
from PIL import Image
from supabase import create_client

from roof_pipeline import telemetry

from .footprint_projection import polygon_pixel_bounds, project_polygon

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables — env-overridable so we can sweep without redeploying.
# ---------------------------------------------------------------------------
MODEL_TYPE = os.environ.get("SAM_MODEL_TYPE", "vit_h")
MODEL_CHECKPOINT = os.environ.get(
    "SAM_CHECKPOINT_PATH", "/opt/mmr-sam/weights/sam_vit_h_4b8939.pth"
)
MODEL_VERSION = os.environ.get("SAM_MODEL_VERSION", "sam_vit_h_4b8939")
POINTS_PER_SIDE = int(os.environ.get("SAM_POINTS_PER_SIDE", "32"))
# Roof panels at the Solar API's ~0.1 m/px are rarely smaller than ~5 m^2
# = 50 000 px^2. Default 5000 is a soft floor that still keeps small
# panels and rejects most dormer-sized masks.
MIN_MASK_REGION_AREA = int(os.environ.get("SAM_MIN_MASK_REGION_AREA", "5000"))
IN_FOOTPRINT_THRESHOLD = float(os.environ.get("SAM_IN_FOOTPRINT_THRESHOLD", "0.80"))
APPROX_EPSILON_PX = float(os.environ.get("SAM_APPROX_EPSILON_PX", "2.0"))
CROP_MARGIN_PX = int(os.environ.get("SAM_CROP_MARGIN_PX", "16"))


# ---------------------------------------------------------------------------
# Lazy singletons (model + supabase). Importing this module must not fail
# without a GPU or a populated .env — the systemd unit imports it on app
# startup, but tests, lint, and CI may import it without either.
# ---------------------------------------------------------------------------
_model_lock = threading.Lock()
_mask_generator: Any | None = None
_supabase_client: Any | None = None
_supabase_init_attempted = False


def _get_supabase():
    global _supabase_client, _supabase_init_attempted
    if _supabase_client is not None or _supabase_init_attempted:
        return _supabase_client
    _supabase_init_attempted = True
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.warning("sam_service: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return None
    try:
        _supabase_client = create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        log.error("sam_service: failed to build supabase client: %s", exc)
        _supabase_client = None
    return _supabase_client


def _get_mask_generator():
    """Build the SamAutomaticMaskGenerator once, lazily.

    Imports torch + segment_anything inside the function so the module
    can be imported on a machine without those packages — useful for
    unit-testing the pure-Python helpers without the full GPU stack.
    """
    global _mask_generator
    if _mask_generator is not None:
        return _mask_generator
    with _model_lock:
        if _mask_generator is not None:
            return _mask_generator
        # Imports deferred here on purpose.
        import torch  # noqa: PLC0415
        from segment_anything import (  # noqa: PLC0415
            SamAutomaticMaskGenerator,
            sam_model_registry,
        )

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            log.warning(
                "sam_service: CUDA unavailable — falling back to CPU. "
                "Inference will be ~10x slower."
            )
        log.info(
            "sam_service: loading SAM (%s) from %s onto %s",
            MODEL_TYPE,
            MODEL_CHECKPOINT,
            device,
        )
        sam = sam_model_registry[MODEL_TYPE](checkpoint=MODEL_CHECKPOINT)
        sam.to(device=device)
        _mask_generator = SamAutomaticMaskGenerator(
            model=sam,
            points_per_side=POINTS_PER_SIDE,
            min_mask_region_area=MIN_MASK_REGION_AREA,
        )
        log.info("sam_service: SAM ready")
    return _mask_generator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _download_rgb(supabase: Any, storage_path: str) -> np.ndarray | None:
    """Pull the RGB image from Supabase storage. Returns an HxWx3 uint8
    array or None on failure."""
    if not storage_path:
        return None
    # Storage paths look like "<bucket>/<key>" or just "<key>" within
    # the canonical bucket. Phase 1 stored them under training-data.
    bucket = "training-data"
    key = storage_path
    if "/" in storage_path:
        # If a bucket prefix was already encoded into the path, peel it.
        head, tail = storage_path.split("/", 1)
        if head in {"training-data", "pipeline-outputs"}:
            bucket, key = head, tail
    try:
        blob = supabase.storage.from_(bucket).download(key)
    except Exception as exc:  # noqa: BLE001
        log.error("sam_service: storage download failed (%s/%s): %s", bucket, key, exc)
        return None
    try:
        img = Image.open(io.BytesIO(blob)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        log.error("sam_service: PIL decode failed: %s", exc)
        return None
    return np.asarray(img)


def _rasterize_polygon(
    rings: list[np.ndarray], shape_hw: tuple[int, int]
) -> np.ndarray:
    """Rasterize a polygon's outer ring + holes onto a uint8 mask of
    shape (H, W). 1 = inside footprint, 0 = outside."""
    h, w = shape_hw
    mask = np.zeros((h, w), dtype=np.uint8)
    if not rings:
        return mask
    outer = rings[0].astype(np.int32)
    cv2.fillPoly(mask, [outer], 1)
    for hole in rings[1:]:
        cv2.fillPoly(mask, [hole.astype(np.int32)], 0)
    return mask


def _polygon_from_mask(
    mask: np.ndarray, epsilon_px: float
) -> np.ndarray | None:
    """Largest connected contour in `mask` -> approxPolyDP polygon.
    Returns (K, 2) float64 or None if nothing salient."""
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) <= 0:
        return None
    approx = cv2.approxPolyDP(largest, epsilon_px, True)
    pts = approx.reshape(-1, 2).astype(np.float64)
    if len(pts) < 3:
        return None
    return pts


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_auto_panels(sample_id: str) -> dict[str, Any]:
    """Run the full pipeline for one sample and persist the result.

    Returns a small status dict — caller treats it as opaque other than
    `status` ("ok" | "skipped" | "error") for logging. The real output
    is the side-effect write to training_samples.auto_panels.
    """
    started = datetime.now(timezone.utc)
    sb = _get_supabase()
    if sb is None:
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "supabase_unconfigured"},
        )
        return {"status": "skipped", "reason": "supabase_unconfigured"}

    # ---- 1. Pull training_samples row ---------------------------------
    try:
        resp = (
            sb.table("training_samples")
            .select(
                "id, rgb_storage_path, building_footprint_geojson, "
                "lat, lng, meters_per_px, width_px, height_px"
            )
            .eq("id", sample_id)
            .maybe_single()
            .execute()
        )
        row = resp.data
    except Exception as exc:  # noqa: BLE001
        log.error("sam_service: supabase select failed for %s: %s", sample_id, exc)
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "supabase_select_error"},
        )
        return {"status": "error", "reason": "supabase_select_error"}

    if not row:
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "sample_not_found"},
        )
        return {"status": "skipped", "reason": "sample_not_found"}

    footprint = row.get("building_footprint_geojson")
    if not footprint:
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "no_footprint"},
        )
        return {"status": "skipped", "reason": "no_footprint"}

    rgb = _download_rgb(sb, row.get("rgb_storage_path") or "")
    if rgb is None:
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "rgb_unreadable"},
        )
        return {"status": "skipped", "reason": "rgb_unreadable"}

    h, w = rgb.shape[:2]
    image_width = int(row.get("width_px") or w)
    image_height = int(row.get("height_px") or h)
    if (image_width, image_height) != (w, h):
        # Snapshot dimensions disagree with the actual image bytes — trust the
        # bytes since SAM operates on the array we hand it. The footprint
        # projection is calibrated against the snapshot dimensions, so we use
        # those for the projection but operate in the image's natural space.
        log.warning(
            "sam_service: snapshot dims %sx%s != rgb dims %sx%s for %s — using rgb",
            image_width,
            image_height,
            w,
            h,
            sample_id,
        )
        image_width, image_height = w, h

    # ---- 2. Project footprint to pixel space --------------------------
    rings = project_polygon(
        footprint,
        center_lat=float(row["lat"]),
        center_lng=float(row["lng"]),
        meters_per_px=float(row["meters_per_px"]),
        image_width=image_width,
        image_height=image_height,
    )
    if not rings:
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "footprint_projection_failed"},
        )
        return {"status": "skipped", "reason": "footprint_projection_failed"}

    bbox = polygon_pixel_bounds(
        rings, image_width=image_width, image_height=image_height, margin_px=CROP_MARGIN_PX
    )
    if bbox is None:
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "footprint_outside_image"},
        )
        return {"status": "skipped", "reason": "footprint_outside_image"}

    x0, y0, x1, y1 = bbox
    crop = rgb[y0:y1, x0:x1]
    crop_h, crop_w = crop.shape[:2]
    if crop_h <= 0 or crop_w <= 0:
        return {"status": "skipped", "reason": "empty_crop"}

    # Footprint mask in CROP-LOCAL coordinates so the in-footprint area
    # filter compares apples to apples with the SAM mask shape.
    rings_local = [r - np.array([x0, y0], dtype=np.float64) for r in rings]
    footprint_mask = _rasterize_polygon(rings_local, (crop_h, crop_w))
    footprint_area = int(footprint_mask.sum())
    if footprint_area <= 0:
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "footprint_area_zero"},
        )
        return {"status": "skipped", "reason": "footprint_area_zero"}

    # ---- 3-5. SAM + filter --------------------------------------------
    try:
        gen = _get_mask_generator()
    except Exception as exc:  # noqa: BLE001
        log.error("sam_service: model load failed: %s", exc)
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            metadata={"reason": "model_load_failed"},
        )
        return {"status": "error", "reason": "model_load_failed"}

    masks = gen.generate(crop)
    log.info("sam_service: SAM produced %d candidate masks for %s", len(masks), sample_id)

    auto_panels: list[dict[str, Any]] = []
    for m in masks:
        seg = m["segmentation"]  # bool HxW
        mask_area = int(seg.sum())
        if mask_area <= 0:
            continue
        inside = int(np.logical_and(seg, footprint_mask.astype(bool)).sum())
        ratio = inside / mask_area
        if ratio < IN_FOOTPRINT_THRESHOLD:
            continue
        polygon_local = _polygon_from_mask(seg, APPROX_EPSILON_PX)
        if polygon_local is None:
            continue
        # Translate from crop-local back to full image space.
        polygon_full = polygon_local + np.array([x0, y0], dtype=np.float64)
        auto_panels.append(
            {
                "polygon_id": str(uuid.uuid4()),
                "corners_pix": polygon_full.tolist(),
                "mask_quality_score": float(m.get("predicted_iou", ratio)),
                "in_footprint_ratio": float(ratio),
            }
        )

    # ---- 6-7. Persist --------------------------------------------------
    duration_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
    try:
        sb.table("training_samples").update(
            {
                "auto_panels": auto_panels,
                "auto_panels_generated_at": datetime.now(timezone.utc).isoformat(),
                "auto_panels_model_version": MODEL_VERSION,
            }
        ).eq("id", sample_id).execute()
    except Exception as exc:  # noqa: BLE001
        log.error("sam_service: supabase update failed for %s: %s", sample_id, exc)
        telemetry.track(
            "auto_panels.fallback",
            sample_id=sample_id,
            duration_ms=duration_ms,
            metadata={"reason": "supabase_update_error"},
        )
        return {"status": "error", "reason": "supabase_update_error"}

    telemetry.track(
        "auto_panels.generated",
        sample_id=sample_id,
        duration_ms=duration_ms,
        metadata={
            "panel_count": len(auto_panels),
            "candidate_count": len(masks),
            "model_version": MODEL_VERSION,
        },
    )
    return {
        "status": "ok",
        "panel_count": len(auto_panels),
        "candidate_count": len(masks),
        "duration_ms": int(duration_ms),
    }
