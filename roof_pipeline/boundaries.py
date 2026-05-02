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


def robust_dsm_sample(
    dsm: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    window: int = 5,
    std_threshold: float = 0.4,
    percentile: float = 20.0,
) -> np.ndarray:
    """Bilinearly sample DSM, but downshift toward roof when canopy is nearby.

    For each (x, y) we look at a ``window x window`` neighborhood. If that
    patch is smooth (std < std_threshold), the bilinear sample is fine. If
    it's rough -- the canopy-edge signature -- we return the lower
    ``percentile`` of the patch, on the principle that roof is below tree.

    This compensates for DSM canopy bleed at corner clicks; it does not
    replace the plane fit, which still has to be RANSAC for the same
    reason. Both layers are needed.
    """
    h, w = dsm.shape
    bilinear = _bilinear_sample(dsm, xs, ys)

    half = window // 2
    out = np.array(bilinear, dtype=np.float64, copy=True)
    cols = np.round(xs).astype(int)
    rows = np.round(ys).astype(int)
    for i in range(len(xs)):
        c0 = max(0, cols[i] - half)
        c1 = min(w, cols[i] + half + 1)
        r0 = max(0, rows[i] - half)
        r1 = min(h, rows[i] + half + 1)
        patch = dsm[r0:r1, c0:c1]
        valid = patch[~np.isnan(patch)] if patch.size else patch
        if valid.size < 4:
            continue
        if float(np.std(valid)) > std_threshold:
            out[i] = float(np.percentile(valid, percentile))
    return out


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
        ys_m = -rows * res_m  # match planes.py: +y = north for north-up DSMs

        # Vertical projection onto the panel's plane: keep the labeler's
        # exact XY and solve Z from the plane equation n·p = d. Mirrors
        # the frontend /api/pipeline/cutsheet-data endpoint, so shared
        # pixel corners (welded by the labeler's vertex magnet at identical
        # col/row) land at identical XY in plan view instead of drifting
        # apart when each panel's corner is orthogonally projected onto
        # a different plane. Result is still exactly planar (every vertex
        # satisfies n·p = d), so downstream triangulation is unaffected.
        plane = planes[pid]
        nx, ny, nz = plane.normal
        if abs(nz) < 1e-9:
            # Near-vertical plane (shouldn't happen for roofs). Fall back
            # to DSM sample + orthogonal projection so the vertex still
            # lies on the plane. Use the canopy-aware sampler for the same
            # reason we do in extract_panel_polygons.
            zs_m = robust_dsm_sample(dsm, cols, rows)
            verts_3d = np.stack([xs_m, ys_m, zs_m], axis=1)
            verts_proj = _project_onto_plane(verts_3d, plane)
        else:
            zs_on_plane = (plane.d - nx * xs_m - ny * ys_m) / nz
            verts_proj = np.stack([xs_m, ys_m, zs_on_plane], axis=1)

        # Per-corner z overrides from the labeler's Auto Correct path
        # (entry.corner_z_overrides). When set, use the user-confirmed z
        # instead of the plane prediction at that corner. Length is
        # validated to match corners; None entries are no-ops.
        overrides = entry.corner_z_overrides
        if overrides:
            n_override = 0
            for i in range(min(len(overrides), verts_proj.shape[0])):
                v = overrides[i]
                if v is not None:
                    verts_proj[i, 2] = float(v)
                    n_override += 1
            if n_override:
                log.info(
                    "panel %d: applied %d corner_z_overrides from labeler",
                    pid, n_override,
                )

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
        ys_m = -rows * res_m  # match planes.py: +y = north for north-up DSMs
        # Robust sample: downshift toward roof level if the patch around the
        # vertex is rough (canopy edge), otherwise straight bilinear.
        zs_m = robust_dsm_sample(dsm, cols, rows)

        verts_3d = np.stack([xs_m, ys_m, zs_m], axis=1)
        verts_proj = _project_onto_plane(verts_3d, plane)

        polygons[pid] = verts_proj
        log.info("panel %d: %d boundary vertices after RDP", pid, verts_proj.shape[0])

    return polygons
