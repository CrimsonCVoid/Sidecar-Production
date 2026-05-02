"""Per-panel plane fitting via SVD with optional RANSAC outer loop.

DSM is a Digital *Surface* Model — it includes vegetation. When a labeler's
polygon clips a tree at a corner, mask pixels under the canopy report
canopy height instead of roof height, and a least-squares SVD fit gets
pulled toward those outliers. RANSAC over the same mask pixels lets the
roof majority outvote the canopy minority, so the fitted plane stays on
the roof. Plain SVD remains the inner fitter and the small-N fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Plane:
    normal: np.ndarray       # (3,) unit normal, oriented n_z >= 0
    centroid: np.ndarray     # (3,) point on the plane (mean of input points)
    rms_residual: float      # RMS of orthogonal distances from inliers to plane
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


def fit_plane_ransac(
    points_xyz: np.ndarray,
    dist_threshold: float = 0.15,
    max_iters: int = 100,
    min_inlier_frac: float = 0.5,
    seed: int = 0,
) -> Plane:
    """Robust plane fit. Returns SVD over the largest inlier consensus set.

    Falls back to plain `fit_plane(points_xyz)` if the inputs are too small
    for sampling to make sense, or if no candidate plane reaches
    ``min_inlier_frac`` of the points within ``dist_threshold``.

    `dist_threshold` defaults to 0.15 m, matching the default snap tolerance
    in main.py — the same scale at which we already consider edges "shared."
    """
    if points_xyz.ndim != 2 or points_xyz.shape[1] != 3:
        raise ValueError(f"need (N, 3) points, got {points_xyz.shape}")

    n = points_xyz.shape[0]
    if n < 12:
        # Too few points for a meaningful consensus loop. Just do plain SVD.
        return fit_plane(points_xyz)

    rng = np.random.default_rng(seed)
    best_inliers: np.ndarray | None = None
    best_count = 0

    for _ in range(max_iters):
        idx = rng.choice(n, size=3, replace=False)
        sample = points_xyz[idx]
        v1 = sample[1] - sample[0]
        v2 = sample[2] - sample[0]
        normal = np.cross(v1, v2)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            # Collinear sample — skip
            continue
        normal = normal / norm
        d = float(normal @ sample[0])
        residuals = np.abs(points_xyz @ normal - d)
        inliers = residuals < dist_threshold
        count = int(inliers.sum())
        if count > best_count:
            best_count = count
            best_inliers = inliers

    if best_inliers is None or best_count < max(3, int(min_inlier_frac * n)):
        # No good consensus — fall back to plain SVD over everything.
        log.info("ransac: no consensus (best %d/%d), falling back to SVD",
                 best_count, n)
        return fit_plane(points_xyz)

    # Refit with all inliers via SVD (more accurate than the 3-point sample).
    return fit_plane(points_xyz[best_inliers])


def fit_all_panels(
    dsm: np.ndarray,
    mask: np.ndarray,
    res_m: float,
    use_ransac: bool = True,
    buffer_m: float = 0.30,
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
        # Erode each panel inward by buffer_m before selecting pixels for
        # the plane fit. Cuts out ridge-cap, gutter, and adjacent-face
        # bleed at the boundary that would otherwise tilt the RANSAC
        # normal. Falls back to the un-eroded mask when the panel is
        # so small that erosion wipes it out.
        panel_mask = (mask == pid).astype(np.uint8)
        if buffer_m > 0.0 and res_m > 0.0:
            try:
                import cv2
                buffer_px = max(1, int(round(buffer_m / res_m)))
                kernel = np.ones((3, 3), np.uint8)
                eroded = cv2.erode(panel_mask, kernel, iterations=buffer_px)
                if int(eroded.sum()) >= 12:
                    panel_mask = eroded
            except Exception as exc:
                log.warning("panel %d: buffer-erosion failed (%s)", pid, exc)
        rows, cols = np.where(panel_mask == 1)
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
        plane = fit_plane_ransac(pts) if use_ransac else fit_plane(pts)
        planes[pid] = plane
        log.info(
            "panel %d: %d pts, normal=(%.3f, %.3f, %.3f), residual_rms=%.4f m",
            pid, pts.shape[0], *plane.normal, plane.rms_residual,
        )

    return planes
