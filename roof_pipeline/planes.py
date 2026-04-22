"""Per-panel plane fitting via SVD (no RANSAC -- mask already constrains region)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Plane:
    normal: np.ndarray       # (3,) unit normal, oriented n_z >= 0
    centroid: np.ndarray     # (3,) point on the plane (mean of input points)
    rms_residual: float      # RMS of orthogonal distances from points to plane
    d: float                 # plane offset so n . x = d for any x on the plane


def fit_plane(points_xyz: np.ndarray) -> Plane:
    """Fit a plane to (N, 3) points using centered SVD.

    The smallest right singular vector is the direction of least variance --
    that's the plane normal. SVD gives us orthogonal residuals directly,
    which is what we want for a tilted-plane fit (a z = ax+by+c least squares
    only minimizes vertical residuals, biased on steep planes).
    """
    if points_xyz.ndim != 2 or points_xyz.shape[1] != 3 or points_xyz.shape[0] < 3:
        raise ValueError(f"need (N>=3, 3) points, got {points_xyz.shape}")

    centroid = points_xyz.mean(axis=0)
    centered = points_xyz - centroid
    # SVD: centered = U S Vt; normal = last row of Vt (smallest singular value)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    normal = vt[-1]
    normal = normal / np.linalg.norm(normal)

    # Orient so normal points up (positive z). Any roof panel's "outside"
    # face points skyward, so we standardize on n_z > 0 for downstream math.
    if normal[2] < 0:
        normal = -normal

    # Orthogonal residuals: signed distance of each point to the plane
    distances = centered @ normal
    rms = float(np.sqrt(np.mean(distances ** 2)))
    d = float(normal @ centroid)

    return Plane(normal=normal, centroid=centroid, rms_residual=rms, d=d)


def fit_all_panels(
    dsm: np.ndarray,
    mask: np.ndarray,
    res_m: float,
) -> dict[int, Plane]:
    """Fit one plane per nonzero panel ID in the mask.

    Pixel (row, col) -> world (x = col*res_m, y = -row*res_m, z = dsm[row, col]).

    The y-axis sign makes +y point north for a standard north-up DSM (where
    row 0 is the northern edge): growing rows move south, so y = -row*res
    puts north at +y. This is the right-handed convention every downstream
    consumer (PDF drawings, azimuth_degrees, mesh viewers) already assumes.
    """
    if dsm.shape != mask.shape:
        raise ValueError(f"dsm {dsm.shape} != mask {mask.shape}")

    planes: dict[int, Plane] = {}
    panel_ids = [int(i) for i in np.unique(mask) if i != 0]

    for pid in panel_ids:
        rows, cols = np.where(mask == pid)
        if rows.size < 3:
            log.warning("panel %d has %d pixels, skipping", pid, rows.size)
            continue
        z = dsm[rows, cols]
        # Drop NaN samples (real DSMs have nodata holes)
        good = ~np.isnan(z)
        if good.sum() < 3:
            log.warning("panel %d has %d valid pixels after NaN drop, skipping",
                        pid, int(good.sum()))
            continue
        rows, cols, z = rows[good], cols[good], z[good]
        x = cols * res_m
        y = -rows * res_m
        pts = np.stack([x, y, z], axis=1).astype(np.float64)
        plane = fit_plane(pts)
        planes[pid] = plane
        log.info(
            "panel %d: %d pts, normal=(%.3f, %.3f, %.3f), residual_rms=%.4f m",
            pid, pts.shape[0], *plane.normal, plane.rms_residual,
        )

    return planes
