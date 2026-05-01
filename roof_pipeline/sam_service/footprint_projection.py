"""WGS84 lat/lng -> image-pixel projection for SAM auto-panels.

Ported from lib/footprint-projection.ts so the SAM service and the
labeler frontend agree pixel-for-pixel on which pixels are "inside the
footprint". If this math drifts from the TS file, the >=80% in-footprint
filter will accept polygons the user can see are outside the outline.

Equirectangular projection from the snapshot's recorded center
(lat, lng, meters_per_px). Sub-pixel accurate over a single-building
extent (~30-50m).
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

EARTH_RADIUS_M = 6_378_137.0
DEG2RAD = math.pi / 180.0


def _meters_between(
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
) -> tuple[float, float]:
    mean_lat = ((from_lat + to_lat) / 2.0) * DEG2RAD
    d_lat = (to_lat - from_lat) * DEG2RAD
    d_lng = (to_lng - from_lng) * DEG2RAD
    dx_m = d_lng * math.cos(mean_lat) * EARTH_RADIUS_M
    # Latitude increases northward, image rows increase downward — flip
    # so the polygon doesn't end up mirrored vertically.
    dy_m = -d_lat * EARTH_RADIUS_M
    return dx_m, dy_m


def project_polygon(
    geojson_polygon: dict,
    center_lat: float,
    center_lng: float,
    meters_per_px: float,
    image_width: int,
    image_height: int,
) -> list[np.ndarray]:
    """Project a GeoJSON Polygon (in WGS84) into image-pixel rings.

    Returns one ndarray per ring (outer + holes), each of shape (N, 2)
    with columns (x_px, y_px). Returns [] on bad input — caller should
    treat that as "no footprint constraint" and skip filtering, OR fall
    back to reporting auto_panels=null.
    """
    if not geojson_polygon or geojson_polygon.get("type") != "Polygon":
        return []
    if not (
        math.isfinite(meters_per_px)
        and meters_per_px > 0
        and math.isfinite(center_lat)
        and math.isfinite(center_lng)
        and image_width > 0
        and image_height > 0
    ):
        return []

    cx_px = image_width / 2.0
    cy_px = image_height / 2.0
    rings: list[np.ndarray] = []
    for ring in geojson_polygon.get("coordinates", []):
        pts: list[tuple[float, float]] = []
        for coord in ring:
            # GeoJSON is (lng, lat); footprint-projection.ts uses the
            # same destructuring.
            lng = float(coord[0])
            lat = float(coord[1])
            dx_m, dy_m = _meters_between(center_lat, center_lng, lat, lng)
            pts.append((cx_px + dx_m / meters_per_px, cy_px + dy_m / meters_per_px))
        if pts:
            rings.append(np.asarray(pts, dtype=np.float64))
    return rings


def polygon_pixel_bounds(
    rings: Sequence[np.ndarray],
    image_width: int,
    image_height: int,
    margin_px: int = 16,
) -> tuple[int, int, int, int] | None:
    """Tight bounding box around the projected polygon, clamped to the
    image and inflated by margin_px so SAM has a few pixels of context
    at the edge of the building. Returns (x0, y0, x1, y1) or None if no
    rings.
    """
    if not rings:
        return None
    all_xy = np.concatenate(rings, axis=0)
    x0 = max(0, int(math.floor(all_xy[:, 0].min() - margin_px)))
    y0 = max(0, int(math.floor(all_xy[:, 1].min() - margin_px)))
    x1 = min(image_width, int(math.ceil(all_xy[:, 0].max() + margin_px)))
    y1 = min(image_height, int(math.ceil(all_xy[:, 1].max() + margin_px)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1
