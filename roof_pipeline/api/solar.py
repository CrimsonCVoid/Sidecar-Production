"""Google Solar API ingest: geocode address, download DSM/RGB/mask, create training_sample.

Accepts an address string, calls Google Geocoding + Solar dataLayers APIs,
downloads the GeoTIFF files, uploads them to Supabase Storage, and inserts
a training_samples row. Returns the sample ID so the frontend can redirect
to /labeling/[sampleId].
"""

from __future__ import annotations

import logging
import uuid
from io import BytesIO

import httpx
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from supabase import Client

from .config import Settings
from .deps import get_settings, get_supabase

log = logging.getLogger(__name__)

router = APIRouter()

SOLAR_BASE = "https://solar.googleapis.com/v1"
GEOCODE_BASE = "https://maps.googleapis.com/maps/api/geocode/json"


class IngestRequest(BaseModel):
    """Address to look up via Google Solar API."""

    address: str


class IngestResponse(BaseModel):
    """Result of ingesting a new address."""

    sample_id: str
    address: str
    formatted_address: str
    lat: float
    lng: float


def _geocode(address: str, api_key: str) -> dict:
    """Geocode an address string to lat/lng using Google Geocoding API."""
    r = httpx.get(
        GEOCODE_BASE,
        params={"address": address, "key": api_key},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data["status"] != "OK" or not data.get("results"):
        raise ValueError(f"Geocoding failed for '{address}': {data.get('status')}")
    result = data["results"][0]
    loc = result["geometry"]["location"]
    return {
        "lat": loc["lat"],
        "lng": loc["lng"],
        "formatted_address": result["formatted_address"],
    }


def _get_data_layers(lat: float, lng: float, api_key: str) -> dict:
    """Call Google Solar dataLayers:get to get GeoTIFF download URLs."""
    r = httpx.get(
        f"{SOLAR_BASE}/dataLayers:get",
        params={
            "location.latitude": lat,
            "location.longitude": lng,
            "radiusMeters": 100,
            "view": "FULL_LAYERS",
            "requiredQuality": "HIGH",
            "pixelSizeMeters": 0.1,
            "key": api_key,
        },
        timeout=30,
    )
    if r.status_code == 404:
        raise ValueError("No solar data available for this location")
    r.raise_for_status()
    return r.json()


def _download_geotiff(url: str, api_key: str) -> bytes:
    """Download a GeoTIFF from a Solar API URL."""
    r = httpx.get(url, params={"key": api_key}, timeout=60)
    r.raise_for_status()
    return r.content


def _upload_to_storage(
    supabase: Client,
    bucket: str,
    path: str,
    data: bytes,
    content_type: str = "image/tiff",
) -> str:
    """Upload bytes to Supabase Storage, return the storage path."""
    supabase.storage.from_(bucket).upload(
        path,
        data,
        {"content-type": content_type, "upsert": "true"},
    )
    return path


def _make_empty_mask(width: int, height: int) -> bytes:
    """Create an empty uint8 mask as .npy bytes."""
    mask = np.zeros((height, width), dtype=np.uint8)
    buf = BytesIO()
    np.save(buf, mask)
    return buf.getvalue()


@router.post("/ingest", response_model=IngestResponse)
async def ingest_address(
    body: IngestRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    """Geocode an address, download Solar API data, create a training sample.

    1. Geocode address -> lat/lng
    2. Call dataLayers:get -> DSM, RGB, mask GeoTIFF URLs
    3. Download GeoTIFFs
    4. Upload to Supabase Storage
    5. Insert training_samples row
    6. Return sample_id for redirect to labeler
    """
    api_key = settings.google_solar_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_SOLAR_API_KEY not configured")

    # 1. Geocode
    geo = _geocode(body.address, api_key)
    lat, lng = geo["lat"], geo["lng"]
    formatted = geo["formatted_address"]
    log.info("geocoded '%s' -> %s (%.6f, %.6f)", body.address, formatted, lat, lng)

    # 2. Get data layers
    layers = _get_data_layers(lat, lng, api_key)

    dsm_url = layers.get("dsmUrl")
    rgb_url = layers.get("rgbUrl")
    mask_url = layers.get("maskUrl")

    if not dsm_url:
        raise HTTPException(status_code=404, detail="No DSM data available for this location")

    # 3. Download GeoTIFFs
    dsm_bytes = _download_geotiff(dsm_url, api_key)
    rgb_bytes = _download_geotiff(rgb_url, api_key) if rgb_url else None
    mask_bytes = _download_geotiff(mask_url, api_key) if mask_url else None

    # Extract rough dimensions from DSM for metadata (via rasterio if available)
    width_px, height_px, meters_per_px = 0, 0, 0.1
    try:
        import rasterio
        from io import BytesIO as _BIO

        with rasterio.open(_BIO(dsm_bytes)) as ds:
            width_px = ds.width
            height_px = ds.height
            if ds.res:
                meters_per_px = abs(ds.res[0])
    except Exception:
        width_px, height_px, meters_per_px = 512, 512, 0.1

    # 4. Upload to Supabase Storage
    sample_id = str(uuid.uuid4())
    prefix = f"samples/{sample_id}"
    bucket = settings.training_bucket

    dsm_path = _upload_to_storage(supabase, bucket, f"{prefix}/dsm.tif", dsm_bytes)

    if rgb_bytes:
        rgb_path = _upload_to_storage(supabase, bucket, f"{prefix}/rgb.tif", rgb_bytes)
    else:
        # Use DSM as fallback RGB
        rgb_path = dsm_path

    if mask_bytes:
        mask_path = _upload_to_storage(
            supabase, bucket, f"{prefix}/mask.tif", mask_bytes,
        )
    else:
        # Create empty mask
        empty = _make_empty_mask(width_px, height_px)
        mask_path = _upload_to_storage(
            supabase, bucket, f"{prefix}/mask.npy", empty,
            content_type="application/octet-stream",
        )

    # 5. Insert training_samples row
    building_insights = layers.get("imageryDate")
    supabase.table("training_samples").insert({
        "id": sample_id,
        "source_address": body.address,
        "formatted_address": formatted,
        "lat": lat,
        "lng": lng,
        "width_px": width_px,
        "height_px": height_px,
        "meters_per_px": meters_per_px,
        "rgb_storage_path": rgb_path,
        "dsm_storage_path": dsm_path,
        "mask_storage_path": mask_path,
        "building_insights": layers.get("imageryDate"),
    }).execute()

    log.info("created training_sample %s for %s", sample_id, formatted)

    return IngestResponse(
        sample_id=sample_id,
        address=body.address,
        formatted_address=formatted,
        lat=lat,
        lng=lng,
    )
