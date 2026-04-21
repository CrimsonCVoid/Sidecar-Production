"""Shared helpers for the 3DEP-vs-Google-Solar benchmark spike.

This module is imported by the other scripts in ``benchmarks/3dep_vs_google/``.
It deliberately does NOT import from ``roof_pipeline.api`` (which would drag
in FastAPI / Supabase at import time); the pieces we need from the live
pipeline are imported lazily at call sites.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Stable namespace UUID for this benchmark. Changing it would invalidate
# every previously-computed sample_id, so don't. Derived once from a URL
# under NAMESPACE_URL so it's reproducible if you ever need to re-derive it.
_BENCHMARK_NS = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://mymetalroofer.com/benchmarks/3dep-vs-google",
)

# Google Solar DSM ground truth (see recon step in the original GSD brief).
# The rasterizer MUST produce GeoTIFFs that match this format exactly so the
# labeling UI and the plane-fit pipeline can open them unchanged.
GOOGLE_DSM_DTYPE = "float32"
GOOGLE_DSM_BANDS = 1
GOOGLE_RGB_BANDS = 3
GOOGLE_RGB_DTYPE = "uint8"
# Resolution the live Solar ingest requests from Google. Keep this as the
# benchmark default so Google and 3DEP twins have matching pixel grids.
DEFAULT_RESOLUTION_M = 0.1


@dataclass(frozen=True)
class SampleMeta:
    """Metadata persisted alongside a rasterized 3DEP DSM.

    Written as ``metadata.json`` next to ``dsm.tif`` / ``rgb.tif`` / ``mask.tif``
    by fetch_3dep.py and consumed by upload_sample.py.
    """

    sample_id: str
    source: str                # '3dep' or 'google'
    address: str
    formatted_address: str
    lat: float
    lng: float
    capture_date: str          # ISO date or 'unknown'
    ql_level: str              # 'QL0'..'QL3' or 'unknown'
    point_density_per_m2: float
    width_px: int
    height_px: int
    meters_per_px: float
    utm_epsg: int
    tnm_work_unit: str = ""    # 3DEP project / work-unit name, for provenance


def deterministic_sample_id(lat: float, lng: float, capture_date: str,
                            source: str = "3dep") -> str:
    """Return a UUIDv5 derived from (source, lat, lng, capture_date).

    Re-running any benchmark script with the same inputs will recompute the
    same ID, which is what the Storage upsert + ``training_samples`` upsert
    rely on for idempotency.

    Lat/lng are rounded to 6 decimal places (~0.11 m at NC latitudes) so
    float noise between re-runs doesn't perturb the hash.
    """
    name = f"{source}|{round(lat, 6):.6f}|{round(lng, 6):.6f}|{capture_date}"
    return str(uuid.uuid5(_BENCHMARK_NS, name))


def utm_epsg_for_latlng(lat: float, lng: float) -> int:
    """Return the EPSG code of the WGS84 / UTM zone covering ``lat, lng``.

    NC lives in zone 17N → EPSG:32617, matching what Google Solar returns
    for Apex / Raleigh test addresses. The live DSM we inspected uses
    EPSG:32617; this function returns the same for NC coordinates and
    handles other regions cleanly if the benchmark is pointed elsewhere.
    """
    zone = int((lng + 180) / 6) + 1
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone


def slugify(text: str, max_len: int = 60) -> str:
    """Filesystem-safe slug for an address (used in output dir names)."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    return s[:max_len] or "unknown"


def load_project_env() -> None:
    """Load the root ``.env`` file so Supabase + Google keys are available.

    Safe to call more than once. Falls back silently if ``python-dotenv``
    isn't installed — in that case the caller is expected to have exported
    the env vars some other way.
    """
    root = Path(__file__).resolve().parents[2]
    env_file = root / ".env"
    if not env_file.exists():
        log.warning(".env not found at %s — hoping env vars are already set",
                    env_file)
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        log.warning("python-dotenv not installed; skipping .env load. "
                    "Export SUPABASE_* and GOOGLE_SOLAR_API_KEY manually.")
        return
    load_dotenv(env_file, override=False)


def env_required(key: str) -> str:
    """Fetch a required env var or exit with a clear message."""
    val = os.environ.get(key, "")
    if not val:
        raise SystemExit(
            f"Missing required env var {key}. Check the root .env or export "
            f"it before running the benchmark scripts."
        )
    return val


def file_sha256(path: Path) -> str:
    """SHA-256 of a file — used for log-level provenance, not security."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
