"""Hillshade and heatmap rendering: GET /api/hillshade/{sampleId}, GET /api/hillshade/{sampleId}/heatmap.

Downloads the DSM GeoTIFF from Supabase Storage, renders as hillshade or
elevation heatmap PNG, returns as image response.
"""

from __future__ import annotations

import logging
from io import BytesIO

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image
from supabase import Client

from .config import Settings
from .deps import get_settings, get_supabase

log = logging.getLogger(__name__)

router = APIRouter()


def _load_dsm(supabase: Client, settings: Settings, sample_id: str) -> np.ndarray:
    """Look up and download DSM for a sample, return as numpy array."""
    result = (
        supabase.table("training_samples")
        .select("dsm_storage_path")
        .eq("id", sample_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Sample {sample_id} not found")

    dsm_path = result.data[0].get("dsm_storage_path")
    if not dsm_path:
        raise HTTPException(status_code=404, detail="No DSM available for this sample")

    # Download from storage (try training bucket first, then pipeline bucket)
    dsm_bytes = None
    for bucket in [settings.training_bucket, settings.storage_bucket]:
        try:
            dsm_bytes = supabase.storage.from_(bucket).download(dsm_path)
            break
        except Exception:
            continue
    if dsm_bytes is None:
        raise HTTPException(status_code=404, detail=f"Could not download DSM from storage")

    import rasterio

    with rasterio.open(BytesIO(dsm_bytes)) as ds:
        return ds.read(1)


def _render_hillshade(dsm: np.ndarray, azimuth: float = 315, altitude: float = 45) -> np.ndarray:
    """Render a hillshade from a DSM array. Returns uint8 grayscale."""
    az_rad = np.radians(azimuth)
    alt_rad = np.radians(altitude)

    dy, dx = np.gradient(dsm)
    slope = np.arctan(np.sqrt(dx * dx + dy * dy))
    aspect = np.arctan2(-dy, dx)

    shade = np.sin(alt_rad) * np.cos(slope) + np.cos(alt_rad) * np.sin(slope) * np.cos(az_rad - aspect)
    shade = np.clip(shade, 0, 1)
    shade = np.nan_to_num(shade, nan=0.5)
    return (shade * 255).astype(np.uint8)


def _render_heatmap(dsm: np.ndarray) -> np.ndarray:
    """Render DSM elevation as RGBA heatmap. Returns (H, W, 4) uint8."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.cm as cm

    arr = dsm.copy().astype(np.float64)
    valid = ~np.isnan(arr)
    if valid.any():
        vmin, vmax = np.nanmin(arr), np.nanmax(arr)
        if vmax > vmin:
            arr = (arr - vmin) / (vmax - vmin)
        else:
            arr[:] = 0.5
    else:
        arr[:] = 0.0

    arr = np.nan_to_num(arr, nan=0.0)
    colored = cm.inferno(arr)  # returns (H, W, 4) float [0,1]
    return (colored * 255).astype(np.uint8)


def _to_png(arr: np.ndarray) -> bytes:
    """Encode numpy array as PNG bytes via Pillow. No matplotlib axis chrome."""
    if arr.ndim == 2:
        img = Image.fromarray(arr, mode="L")
    else:
        img = Image.fromarray(arr, mode="RGBA")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


@router.get("/{sample_id}")
async def get_hillshade(
    sample_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    """Render and return a hillshade PNG for a training sample's DSM."""
    dsm_arr = _load_dsm(supabase, settings, sample_id)
    shade = _render_hillshade(dsm_arr)
    png_bytes = _to_png(shade)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{sample_id}/rgb")
async def get_rgb(
    sample_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    """Return the satellite RGB image as PNG for a training sample."""
    result = (
        supabase.table("training_samples")
        .select("rgb_storage_path")
        .eq("id", sample_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Sample {sample_id} not found")

    rgb_path = result.data[0].get("rgb_storage_path")
    if not rgb_path:
        raise HTTPException(status_code=404, detail="No RGB image available")

    rgb_bytes = None
    for bucket in [settings.training_bucket, settings.storage_bucket]:
        try:
            rgb_bytes = supabase.storage.from_(bucket).download(rgb_path)
            break
        except Exception:
            continue
    if rgb_bytes is None:
        raise HTTPException(status_code=404, detail="Could not download RGB from storage")

    # Convert GeoTIFF to PNG
    import rasterio

    with rasterio.open(BytesIO(rgb_bytes)) as ds:
        if ds.count >= 3:
            r, g, b = ds.read(1), ds.read(2), ds.read(3)
            rgb_arr = np.stack([r, g, b], axis=-1)
        else:
            band = ds.read(1)
            rgb_arr = np.stack([band, band, band], axis=-1)

    img = Image.fromarray(rgb_arr.astype(np.uint8), mode="RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{sample_id}/heatmap")
async def get_heatmap(
    sample_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    """Render and return a DSM elevation heatmap PNG (inferno colormap, RGBA)."""
    dsm_arr = _load_dsm(supabase, settings, sample_id)
    heatmap = _render_heatmap(dsm_arr)
    png_bytes = _to_png(heatmap)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
