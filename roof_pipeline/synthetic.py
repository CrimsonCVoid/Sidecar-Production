"""Synthetic DSM + segmentation mask for end-to-end pipeline testing."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class SyntheticRoof:
    dsm: np.ndarray          # (H, W) float32 elevations in meters
    mask: np.ndarray         # (H, W) uint8 panel IDs (0 = background)
    res_m: float             # ground sampling distance in meters/pixel


def make_synthetic_gable(
    width_px: int = 400,
    height_px: int = 300,
    res_m: float = 0.05,
    pitch: float = 6.0 / 12.0,
    eave_height: float = 2.5,
    margin_px: int = 30,
    noise_std: float = 0.01,
    seed: int = 0,
) -> SyntheticRoof:
    """Build a 2-panel gable roof DSM and matching panel mask.

    Geometry: rectangular footprint inset by ``margin_px`` on every side; the
    ridge runs along the horizontal midline (constant y). The south face
    (smaller y) is panel 1, the north face (larger y) is panel 2. Elevation
    rises linearly from each eave up to the ridge with the given pitch.

    DSM uses raster convention with the origin at pixel (0, 0):
    world x = col * res_m, world y = row * res_m.
    """
    rng = np.random.default_rng(seed)

    dsm = np.zeros((height_px, width_px), dtype=np.float32)
    mask = np.zeros((height_px, width_px), dtype=np.uint8)

    rows = np.arange(height_px)[:, None]  # column vector for broadcasting
    ridge_row = height_px // 2

    # Footprint rectangle in pixel space
    r0, r1 = margin_px, height_px - margin_px
    c0, c1 = margin_px, width_px - margin_px

    south_rect = np.zeros_like(mask, dtype=bool)
    south_rect[r0:ridge_row + 1, c0:c1 + 1] = True
    north_rect = np.zeros_like(mask, dtype=bool)
    north_rect[ridge_row:r1 + 1, c0:c1 + 1] = True

    # Elevation: linear ramp from eave (low) to ridge (high) on each face.
    # Distance from ridge in world meters along the pitch direction:
    dist_from_ridge_m = np.abs(rows - ridge_row) * res_m
    eave_dist_m = (ridge_row - r0) * res_m
    z_profile = eave_height + (eave_dist_m - dist_from_ridge_m) * pitch  # (H, 1)
    z = np.broadcast_to(z_profile, dsm.shape).astype(np.float32)

    dsm[south_rect] = z[south_rect]
    dsm[north_rect] = z[north_rect]
    mask[south_rect] = 1
    mask[north_rect] = 2

    # Ridge belongs to both faces -- assign to panel 1 deterministically so
    # each pixel has exactly one ID. The mesh ridge is reconstructed by snap.
    mask[ridge_row, c0:c1 + 1] = 1

    # Sensor noise on the elevation only inside the roof footprint
    noise = rng.normal(0.0, noise_std, size=dsm.shape).astype(np.float32)
    dsm[mask > 0] += noise[mask > 0]

    log.info(
        "synthetic gable: %dx%d px @ %.3f m/px, pitch=%.3f, eave=%.2f m, noise=%.3f m",
        width_px, height_px, res_m, pitch, eave_height, noise_std,
    )
    return SyntheticRoof(dsm=dsm, mask=mask, res_m=res_m)
