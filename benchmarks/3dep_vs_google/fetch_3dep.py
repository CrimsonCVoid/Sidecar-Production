"""Phase 1 — Fetch a USGS 3DEP LiDAR DSM for one lat/lng.

Produces a ``{dsm,rgb,mask}.tif`` triple whose GeoTIFF format (CRS, affine,
dtype, band count) matches what Google Solar returns, so the exact same
labeling UI + plane fit pipeline can consume it unchanged.

CLI:
    python benchmarks/3dep_vs_google/fetch_3dep.py \\
        --address "123 Main St, Apex NC" --radius 75 --resolution 0.1

    # Or skip geocoding:
    python benchmarks/3dep_vs_google/fetch_3dep.py \\
        --latlng 35.7327,-78.8503 --radius 75 --resolution 0.1

The rasterizer goes LAZ → max-z grid → GeoTIFF. We chose laspy over PDAL
deliberately so the benchmark has no C-library system dependency — any
machine that can ``pip install`` the rest of roof_pipeline can run this
straight away.

What "hard fail" means in this script: print a clear error line starting
with ``ERROR:`` and exit with code 1. The upload step downstream refuses
to touch Supabase unless Phase 1 produced a complete output dir with
metadata.json present, so partial failures here can't silently poison
training_samples.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from common import (
    DEFAULT_RESOLUTION_M,
    GOOGLE_DSM_DTYPE,
    GOOGLE_RGB_DTYPE,
    SampleMeta,
    deterministic_sample_id,
    load_project_env,
    slugify,
    utm_epsg_for_latlng,
)

log = logging.getLogger("bench.3dep")


# ---------------------------------------------------------------------------
# Address / coordinate resolution
# ---------------------------------------------------------------------------

def resolve_location(address: str | None, latlng: str | None) -> tuple[float, float, str]:
    """Return (lat, lng, formatted_address) for either an address or a raw pair.

    For addresses we reuse the production ``_geocode`` helper so the benchmark
    sees the exact same lat/lng the live ingest would resolve to — no drift
    between how Google Solar and 3DEP locate a house.
    """
    if latlng:
        try:
            lat_s, lng_s = latlng.split(",")
            lat, lng = float(lat_s.strip()), float(lng_s.strip())
        except ValueError:
            raise SystemExit(f"ERROR: --latlng must be 'lat,lng'; got {latlng!r}")
        return lat, lng, f"{lat:.6f},{lng:.6f}"

    if not address:
        raise SystemExit("ERROR: supply --address or --latlng")

    # Reuse the production geocoder verbatim — importing a function, not
    # modifying pipeline code.
    from roof_pipeline.api.solar import _geocode  # type: ignore

    api_key = _require_google_key()
    geo = _geocode(address, api_key)
    return geo["lat"], geo["lng"], geo["formatted_address"]


def _require_google_key() -> str:
    import os
    key = os.environ.get("GOOGLE_SOLAR_API_KEY", "")
    if not key:
        raise SystemExit(
            "ERROR: GOOGLE_SOLAR_API_KEY missing. Needed to reuse the "
            "production geocoder. Export it or add it to .env."
        )
    return key


# ---------------------------------------------------------------------------
# TNM (The National Map) discovery
# ---------------------------------------------------------------------------

TNM_ENDPOINT = "https://tnmaccess.nationalmap.gov/api/v1/products"
TNM_DATASET = "Lidar Point Cloud (LPC)"
MAX_AGE_YEARS = 5
MIN_QL_RANK = 2  # QL2 or better. Smaller number = higher quality.


def _ql_rank(text: str) -> int | None:
    """Extract a QL rank from a project/work-unit string.

    USGS names projects like "USGS Lidar Point Cloud NC_Phase5_2017 QL2 LAS
    2018". We parse out ``QL0``..``QL3`` (lower = better). Returns None when
    no QL marker is present — those get deprioritised but not rejected
    outright, because older coverage is sometimes ungraded.
    """
    import re as _re
    m = _re.search(r"QL\s*([0-3])", text or "", flags=_re.IGNORECASE)
    return int(m.group(1)) if m else None


def query_tnm(lat: float, lng: float, bbox_m: float) -> list[dict]:
    """Hit the TNM products endpoint and return LiDAR LAZ/LAS items.

    ``bbox_m`` is the half-size of the query box in meters (so radius 75 →
    a 150 m × 150 m bbox around the target). TNM expects a WGS84 degree
    bbox, so we convert naively using 111 km / degree — good enough at the
    residential scale we care about.
    """
    import urllib.parse
    import urllib.request

    # Degree bbox around the target. Naive spherical conversion is fine at
    # this scale — 75 m is well under 0.001° and error is sub-meter.
    deg_lat = bbox_m / 111_320.0
    deg_lng = bbox_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    params = {
        "datasets": TNM_DATASET,
        "bbox": f"{lng - deg_lng},{lat - deg_lat},{lng + deg_lng},{lat + deg_lat}",
        "prodFormats": "LAS,LAZ",
        "outputFormat": "JSON",
        "max": "50",
    }
    url = f"{TNM_ENDPOINT}?{urllib.parse.urlencode(params)}"
    log.info("TNM query: %s", url)

    req = urllib.request.Request(url, headers={"User-Agent": "mmr-benchmark/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
    except Exception as e:
        raise SystemExit(f"ERROR: TNM API call failed: {e}") from None

    items = payload.get("items") or []
    log.info("TNM returned %d candidate items", len(items))
    return items


def pick_best_tile(items: list[dict]) -> dict:
    """Rank TNM items and pick the best one (or fail if nothing qualifies).

    Scoring favours recent, high-QL data. We reject tiles older than 5
    years and QL worse than 2 — per the GSD brief's hard-fail criteria.
    """
    if not items:
        raise SystemExit(
            "ERROR: no 3DEP LiDAR coverage at this location per TNM."
        )

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    ranked: list[tuple[int, dict, dict]] = []
    for it in items:
        dl = it.get("downloadURL") or it.get("downloadLazURL") or ""
        if not dl.lower().endswith((".laz", ".las")):
            continue
        title = it.get("title") or ""
        ql = _ql_rank(title) or _ql_rank(it.get("metaUrl", ""))
        pub = it.get("publicationDate") or it.get("dateCreated") or ""
        try:
            pub_dt = dt.datetime.strptime(pub[:10], "%Y-%m-%d")
            age_years = (now - pub_dt).days / 365.25
        except Exception:
            pub_dt = None
            age_years = 99.0

        meta = {
            "title": title,
            "publicationDate": pub,
            "qualityLevel": f"QL{ql}" if ql is not None else "unknown",
            "downloadURL": dl,
            "sizeInBytes": it.get("sizeInBytes"),
            "age_years": age_years,
        }
        # Score: lower is better. Penalise missing QL and excessive age.
        score = 0
        score += (ql if ql is not None else 9) * 100
        score += int(min(age_years, 99) * 10)
        ranked.append((score, it, meta))

    if not ranked:
        raise SystemExit("ERROR: TNM returned items but none in LAZ/LAS format.")

    ranked.sort(key=lambda x: x[0])
    best_score, _, best_meta = ranked[0]

    # Enforce hard-fail criteria against the *best* candidate.
    if best_meta["age_years"] > MAX_AGE_YEARS:
        raise SystemExit(
            f"ERROR: best 3DEP tile is {best_meta['age_years']:.1f} years old "
            f"(>{MAX_AGE_YEARS}). Refusing to produce a stale benchmark."
        )
    ql_num = _ql_rank(best_meta["qualityLevel"])
    if ql_num is None:
        log.warning("best tile has no QL tag; continuing with caveat")
    elif ql_num > MIN_QL_RANK:
        raise SystemExit(
            f"ERROR: best 3DEP tile is QL{ql_num} (worse than QL{MIN_QL_RANK})."
        )

    log.info("chose tile: %s  (score=%d, QL=%s, age=%.1fy)",
             best_meta["title"], best_score, best_meta["qualityLevel"],
             best_meta["age_years"])
    return best_meta


# ---------------------------------------------------------------------------
# LAZ download + raster construction
# ---------------------------------------------------------------------------

MAX_LAZ_MB = 800


def download_laz(url: str, dest: Path) -> Path:
    """Stream a LAZ tile to disk with a size cap and a progress bar."""
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1024:
        log.info("reusing cached LAZ at %s (%.1f MB)",
                 dest, dest.stat().st_size / 1e6)
        return dest

    log.info("downloading LAZ %s", url)
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    req = urllib.request.Request(url, headers={"User-Agent": "mmr-benchmark/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length", 0))
        total_mb = total / 1e6 if total else 0
        if total_mb > MAX_LAZ_MB:
            raise SystemExit(
                f"ERROR: LAZ tile is {total_mb:.0f} MB (>{MAX_LAZ_MB} MB cap). "
                "Bounding-box-aware download not implemented yet."
            )
        bar = tqdm(total=total, unit="B", unit_scale=True, desc="LAZ") if tqdm else None
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                if bar:
                    bar.update(len(chunk))
        if bar:
            bar.close()
    return dest


def rasterize_laz_to_dsm(
    laz_paths: list[Path],
    centre_lat: float,
    centre_lng: float,
    radius_m: float,
    resolution_m: float,
    target_epsg: int,
) -> tuple[np.ndarray, rasterio.Affine, dict]:
    """Read LAZ tile(s), crop to the bbox, and rasterize to a max-Z GeoTIFF grid.

    Returns (grid, affine, stats). The grid is float32 with NaN nodata,
    matching the format Google Solar returns.
    """
    import laspy
    from pyproj import Transformer

    # Target bbox in UTM meters — same convention Google's affine uses:
    # top-left origin, positive X east, negative Y north.
    to_utm = Transformer.from_crs(4326, target_epsg, always_xy=True)
    cx, cy = to_utm.transform(centre_lng, centre_lat)
    xmin, xmax = cx - radius_m, cx + radius_m
    ymin, ymax = cy - radius_m, cy + radius_m

    width = int(round((xmax - xmin) / resolution_m))
    height = int(round((ymax - ymin) / resolution_m))
    affine = from_origin(xmin, ymax, resolution_m, resolution_m)

    # Max-Z accumulator. Start at -inf so any real point beats it.
    grid = np.full((height, width), -np.inf, dtype=np.float32)

    total_in = 0
    total_kept = 0

    for p in laz_paths:
        log.info("reading %s", p)
        with laspy.open(str(p)) as reader:
            src_crs = reader.header.parse_crs()
            # Fallback: many 3DEP LAZ files omit the EPSG but carry a WKT.
            # If parse_crs fails we can't do a safe reprojection and abort.
            if src_crs is None:
                raise SystemExit(
                    f"ERROR: LAZ at {p} has no CRS in its header VLRs. "
                    "Can't safely reproject to UTM — aborting rather than "
                    "producing a silently misaligned DSM."
                )
            src_epsg = src_crs.to_epsg() or 0
            log.info("  source CRS: %s (EPSG %s)", src_crs, src_epsg)

            reproj = Transformer.from_crs(src_crs, target_epsg, always_xy=True)

            # Stream in chunks so a 500 MB tile doesn't blow up memory.
            for chunk in reader.chunk_iterator(2_000_000):
                total_in += len(chunk)
                # 3DEP chunks are unclassified returns; prefer first-return
                # surface points. We keep classification 1 (unassigned) and
                # 2 (ground) and explicitly drop 7 (noise) and 18 (high noise).
                cls = np.asarray(chunk.classification)
                keep = (cls != 7) & (cls != 18)
                if not keep.any():
                    continue
                x = np.asarray(chunk.x)[keep]
                y = np.asarray(chunk.y)[keep]
                z = np.asarray(chunk.z)[keep]

                xu, yu = reproj.transform(x, y)
                # Bbox prefilter (saves the divide/floor work on far points).
                m = (xu >= xmin) & (xu < xmax) & (yu >= ymin) & (yu < ymax)
                if not m.any():
                    continue
                xu, yu, z = xu[m], yu[m], z[m].astype(np.float32)

                cols = np.floor((xu - xmin) / resolution_m).astype(np.int32)
                # Row axis is inverted because the affine points DOWN (negative Y).
                rows = np.floor((ymax - yu) / resolution_m).astype(np.int32)
                np.maximum.at(grid, (rows, cols), z)
                total_kept += len(z)

    if total_kept == 0:
        raise SystemExit(
            "ERROR: LAZ tile(s) contained zero points inside the requested "
            "bbox after reprojection. Likely a CRS or unit mismatch."
        )

    # Fill -inf (empty cells) with NaN so downstream rasterio code sees
    # nodata via the usual `np.isnan` path.
    empty = ~np.isfinite(grid)
    grid[empty] = np.nan

    stats = {
        "points_read": total_in,
        "points_kept": total_kept,
        "empty_cells_before_fill": int(empty.sum()),
        "width": width,
        "height": height,
        "point_density_per_m2": total_kept / max(1.0, (2 * radius_m) ** 2),
    }
    return grid, affine, stats


def fill_small_gaps(grid: np.ndarray, max_gap_px: int = 2) -> np.ndarray:
    """Nearest-neighbour fill for gaps ≤ ``max_gap_px``, leave larger holes NaN.

    Single-pixel LAZ dropouts are common at scan-line edges; our downstream
    plane fit already handles NaN via ``fit_plane`` + NaN-drop, so we only
    need to patch tiny holes that would otherwise drain erosion too aggressively.
    """
    from scipy.ndimage import distance_transform_edt

    nan_mask = ~np.isfinite(grid)
    if not nan_mask.any():
        return grid

    # ``distance_transform_edt`` with return_indices gives, for each pixel,
    # the index of the nearest non-NaN cell. We sample from those indices
    # only where the distance is within max_gap_px.
    dist, (ri, ci) = distance_transform_edt(
        nan_mask, return_distances=True, return_indices=True,
    )
    out = grid.copy()
    close = (dist <= max_gap_px) & nan_mask
    out[close] = grid[ri[close], ci[close]]
    return out


# ---------------------------------------------------------------------------
# Companion RGB + mask
# ---------------------------------------------------------------------------

def hillshade_rgb(dsm: np.ndarray, resolution_m: float) -> np.ndarray:
    """Return a (H, W, 3) uint8 hillshade usable as a placeholder RGB.

    The labeling UI expects a 3-band uint8 companion raster. We don't have a
    real ortho for the spike, so we render a Lambertian hillshade off the
    DSM itself. Visually distinct enough that you can still label panels,
    and the plane fit ignores the RGB completely.
    """
    # Standard sun azimuth 315° / altitude 45°.
    az, alt = math.radians(315), math.radians(45)
    dzdy, dzdx = np.gradient(np.nan_to_num(dsm, nan=float(np.nanmin(dsm))),
                             resolution_m, resolution_m)
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(-dzdx, dzdy)
    shade = (np.sin(alt) * np.cos(slope)
             + np.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    shade = np.clip(shade, 0.0, 1.0)
    shade_u8 = (shade * 255).astype(np.uint8)
    # 3-band grayscale so the GeoTIFF format matches the Google RGB exactly.
    return np.stack([shade_u8] * 3, axis=0)


def write_dsm_tif(dest: Path, dsm: np.ndarray, affine: rasterio.Affine,
                  epsg: int) -> None:
    """Write a float32 single-band GeoTIFF matching Google Solar's format."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        dest, "w",
        driver="GTiff",
        width=dsm.shape[1],
        height=dsm.shape[0],
        count=1,
        dtype=GOOGLE_DSM_DTYPE,
        crs=f"EPSG:{epsg}",
        transform=affine,
        nodata=float("nan"),
        compress="lzw",
        tiled=True,
    ) as dst:
        dst.write(dsm.astype(GOOGLE_DSM_DTYPE), 1)


def write_rgb_tif(dest: Path, rgb: np.ndarray, affine: rasterio.Affine,
                  epsg: int) -> None:
    """Write a 3-band uint8 RGB GeoTIFF matching Google Solar's companion."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        dest, "w",
        driver="GTiff",
        width=rgb.shape[2],
        height=rgb.shape[1],
        count=3,
        dtype=GOOGLE_RGB_DTYPE,
        crs=f"EPSG:{epsg}",
        transform=affine,
        compress="lzw",
        tiled=True,
    ) as dst:
        dst.write(rgb.astype(GOOGLE_RGB_DTYPE))


def write_mask_tif(dest: Path, shape: tuple[int, int], affine: rasterio.Affine,
                   epsg: int) -> None:
    """Write an all-ones uint8 mask — the pipeline treats user polygons as truth."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        dest, "w",
        driver="GTiff",
        width=shape[1],
        height=shape[0],
        count=1,
        dtype="uint8",
        crs=f"EPSG:{epsg}",
        transform=affine,
        compress="lzw",
        tiled=True,
    ) as dst:
        dst.write(np.ones(shape, dtype=np.uint8), 1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch a USGS 3DEP LiDAR DSM")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--address", help='e.g. "123 Main St, Apex NC"')
    src.add_argument("--latlng", help="e.g. 35.7327,-78.8503")
    parser.add_argument("--radius", type=float, default=75.0,
                        help="half-size of the DSM bbox in meters (default 75)")
    parser.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION_M,
                        help=f"pixel size in meters (default {DEFAULT_RESOLUTION_M})")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).parent / "output")
    parser.add_argument("--cache-dir", type=Path,
                        default=Path(__file__).parent / "output" / "_laz_cache",
                        help="where downloaded LAZ tiles are cached")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_project_env()

    # 1. Resolve address → lat/lng
    lat, lng, formatted = resolve_location(args.address, args.latlng)
    log.info("target: %s  (%.6f, %.6f)", formatted, lat, lng)
    epsg = utm_epsg_for_latlng(lat, lng)
    log.info("target UTM zone: EPSG:%d", epsg)

    # 2. Discover the best 3DEP tile at this location
    items = query_tnm(lat, lng, args.radius)
    best = pick_best_tile(items)

    # 3. Download LAZ (cached across re-runs)
    laz_name = Path(best["downloadURL"]).name or "tile.laz"
    laz_path = download_laz(best["downloadURL"], args.cache_dir / laz_name)

    # 4. Rasterize to a Google-shaped DSM
    dsm, affine, stats = rasterize_laz_to_dsm(
        [laz_path], lat, lng, args.radius, args.resolution, epsg,
    )
    log.info("raw raster stats: %s", stats)

    dsm = fill_small_gaps(dsm, max_gap_px=2)
    empty_after = int((~np.isfinite(dsm)).sum())
    log.info("empty cells after gap-fill: %d / %d",
             empty_after, dsm.size)

    # 5. Build the output directory using the capture date for stability
    capture = (best.get("publicationDate") or "unknown")[:10] or "unknown"
    sample_id = deterministic_sample_id(lat, lng, capture, source="3dep")
    slug = f"{lat:.4f}_{lng:.4f}_{capture.replace('-', '')}"
    out_dir = args.output_dir / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    write_dsm_tif(out_dir / "dsm.tif", dsm, affine, epsg)
    write_rgb_tif(out_dir / "rgb.tif",
                  hillshade_rgb(dsm, args.resolution), affine, epsg)
    write_mask_tif(out_dir / "mask.tif", dsm.shape, affine, epsg)

    # 6. Metadata sidecar consumed by upload_sample.py
    meta = SampleMeta(
        sample_id=sample_id,
        source="3dep",
        address=args.address or args.latlng or "",
        formatted_address=formatted,
        lat=lat,
        lng=lng,
        capture_date=capture,
        ql_level=best.get("qualityLevel", "unknown"),
        point_density_per_m2=stats["point_density_per_m2"],
        width_px=dsm.shape[1],
        height_px=dsm.shape[0],
        meters_per_px=args.resolution,
        utm_epsg=epsg,
        tnm_work_unit=best.get("title", ""),
    )
    (out_dir / "metadata.json").write_text(json.dumps(asdict(meta), indent=2))

    print(
        "\n3DEP fetch complete\n"
        f"  Address:      {formatted}\n"
        f"  Lat/lng:      {lat:.6f}, {lng:.6f}\n"
        f"  Capture date: {capture}\n"
        f"  QL level:     {best.get('qualityLevel', 'unknown')}\n"
        f"  Point density: {stats['point_density_per_m2']:.1f} pts/m²\n"
        f"  Output files:\n"
        f"    - {out_dir / 'dsm.tif'}\n"
        f"    - {out_dir / 'rgb.tif'}\n"
        f"    - {out_dir / 'mask.tif'}\n"
        f"  Sample ID (deterministic): {sample_id}\n"
        f"\nNext: python benchmarks/3dep_vs_google/upload_sample.py "
        f"--input-dir {out_dir}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
