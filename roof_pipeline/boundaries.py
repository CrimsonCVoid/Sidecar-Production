"""Per-panel boundary extraction, 3D lift, and projection onto fitted planes."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

from .panel_snap_v2.schema import PanelsInput
from .planes import Plane

log = logging.getLogger(__name__)


def _bilinear_sample(grid: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinearly sample ``grid`` at fractional pixel coords (xs=col, ys=row)."""
    h, w = grid.shape
    x0 = np.clip(np.floor(xs).astype(int), 0, w - 1)
    y0 = np.clip(np.floor(ys).astype(int), 0, h - 1)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    fx = xs - x0
    fy = ys - y0
    g00 = grid[y0, x0]
    g10 = grid[y0, x1]
    g01 = grid[y1, x0]
    g11 = grid[y1, x1]
    return (
        g00 * (1 - fx) * (1 - fy)
        + g10 * fx * (1 - fy)
        + g01 * (1 - fx) * fy
        + g11 * fx * fy
    )


def _project_onto_plane(points_3d: np.ndarray, plane: Plane) -> np.ndarray:
    """Orthogonally project (N, 3) points onto the plane.

    For a point p, the closest point on the plane is
        p_proj = p - ((p - c) . n) * n
    where c is any point on the plane (we use the centroid) and n is the
    unit normal. After this, every vertex satisfies n . p = d exactly.
    """
    delta = points_3d - plane.centroid
    signed_dist = delta @ plane.normal
    return points_3d - signed_dist[:, None] * plane.normal


def polygons_from_clicks(
    panels_json_path: str | Path,
    dsm: np.ndarray,
    res_m: float,
    planes: dict[int, Plane],
) -> dict[int, np.ndarray]:
    """Build per-panel polygons from the labeler's saved click coordinates.

    This is the preferred path: the user clicked exactly N corners, so the
    output polygon has exactly N vertices and perfectly straight edges.
    Compare with extract_panel_polygons() which re-traces the rasterized
    mask and produces stairstepped contours that need RDP cleanup.

    Pipeline per panel:
      1. Read clicked (col_px, row_px) corners from the JSON sidecar.
      2. Convert pixel -> world meters.
      3. Bilinearly sample DSM elevation at each clicked corner.
      4. Project the 3D vertex onto the panel's fitted plane so the polygon
         is perfectly planar (necessary for triangulation).
    """
    path = Path(panels_json_path)
    with open(path) as f:
        raw = json.load(f)

    # Pydantic validation at the input boundary (VALID-01, D-07)
    validated = PanelsInput.model_validate(raw)

    polygons: dict[int, np.ndarray] = {}
    for entry in validated.panels:
        pid = entry.id
        if pid not in planes:
            log.warning("panel %d in clicks but missing plane fit, skipping", pid)
            continue
        corners_pix = np.asarray(entry.corners_pix, dtype=np.float64)
        if corners_pix.shape[0] < 3:
            log.warning("panel %d has %d corners, skipping", pid, corners_pix.shape[0])
            continue

        cols = corners_pix[:, 0]
        rows = corners_pix[:, 1]
        xs_m = cols * res_m
        ys_m = rows * res_m
        zs_m = _bilinear_sample(dsm, cols, rows)

        verts_3d = np.stack([xs_m, ys_m, zs_m], axis=1)
        verts_proj = _project_onto_plane(verts_3d, planes[pid])

        polygons[pid] = verts_proj
        log.info("panel %d: %d clicked corners (no contour re-trace)",
                 pid, verts_proj.shape[0])
    return polygons


def extract_panel_polygons(
    mask: np.ndarray,
    dsm: np.ndarray,
    res_m: float,
    planes: dict[int, Plane],
    rdp_epsilon_px: float = 0.5,
) -> dict[int, np.ndarray]:
    """Return per-panel ordered (K, 3) boundary vertices on each panel's plane.

    Pipeline per panel:
      1. Binary mask -> external contour via OpenCV.
      2. Ramer-Douglas-Peucker simplification to collapse rasterization
         stairsteps. Without this, a 100-pixel-long ridge edge becomes ~50
         tiny near-collinear segments that defeat pairwise edge snapping.
      3. Pixel coords -> world meters; sample DSM elevation at each vertex.
      4. Project each 3D vertex onto the panel's fitted plane so the polygon
         is perfectly planar (later triangulation requires this).
    """
    polygons: dict[int, np.ndarray] = {}
    for pid, plane in planes.items():
        binary = (mask == pid).astype(np.uint8) * 255
        contours, _ = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            log.warning("panel %d: no contour found", pid)
            continue
        # Largest contour by area -- ignores any holes/spurs from labeling noise
        contour = max(contours, key=cv2.contourArea)
        simplified = cv2.approxPolyDP(contour, rdp_epsilon_px, closed=True)
        pix = simplified.reshape(-1, 2).astype(np.float64)  # (K, 2) as (col, row)

        cols = pix[:, 0]
        rows = pix[:, 1]
        xs_m = cols * res_m
        ys_m = rows * res_m
        zs_m = _bilinear_sample(dsm, cols, rows)

        verts_3d = np.stack([xs_m, ys_m, zs_m], axis=1)
        verts_proj = _project_onto_plane(verts_3d, plane)

        polygons[pid] = verts_proj
        log.info("panel %d: %d boundary vertices after RDP", pid, verts_proj.shape[0])

    return polygons
