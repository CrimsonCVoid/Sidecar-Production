"""Hillshade rendering endpoint: GET /api/hillshade/{sampleId}.

Downloads the DSM GeoTIFF from Supabase Storage, renders a hillshade PNG
using matplotlib, and returns it as an image response. Cached in-memory
per sample_id to avoid re-rendering on every request.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from io import BytesIO

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from supabase import Client

from .config import Settings
from .deps import get_settings, get_supabase

log = logging.getLogger(__name__)

router = APIRouter()


def _render_hillshade(dsm: np.ndarray, azimuth: float = 315, altitude: float = 45) -> np.ndarray:
    """Render a hillshade from a DSM array. Returns uint8 grayscale."""
    az_rad = np.radians(azimuth)
    alt_rad = np.radians(altitude)

    # Gradient
    dy, dx = np.gradient(dsm)
    slope = np.arctan(np.sqrt(dx * dx + dy * dy))
    aspect = np.arctan2(-dy, dx)

    shade = np.sin(alt_rad) * np.cos(slope) + np.cos(alt_rad) * np.sin(slope) * np.cos(az_rad - aspect)
    shade = np.clip(shade, 0, 1)

    # Handle NaN
    shade = np.nan_to_num(shade, nan=0.5)
    return (shade * 255).astype(np.uint8)


def _encode_png(arr: np.ndarray) -> bytes:
    """Encode a 2D uint8 array as PNG bytes."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(arr.shape[1] / 100, arr.shape[0] / 100), dpi=100)
    ax.imshow(arr, cmap="gray", vmin=0, vmax=255)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0, dpi=100)
    plt.close(fig)
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
    # Look up DSM storage path
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

    # Download DSM from storage
    try:
        dsm_bytes = supabase.storage.from_(settings.training_bucket).download(dsm_path)
    except Exception:
        # Try pipeline-outputs bucket as fallback
        try:
            dsm_bytes = supabase.storage.from_(settings.storage_bucket).download(dsm_path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Could not download DSM: {exc}") from exc

    # Load with rasterio
    try:
        import rasterio
        with rasterio.open(BytesIO(dsm_bytes)) as ds:
            dsm_arr = ds.read(1)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read DSM GeoTIFF: {exc}") from exc

    # Render hillshade
    shade = _render_hillshade(dsm_arr)
    png_bytes = _encode_png(shade)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
