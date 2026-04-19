"""Shared test helpers for panel_snap_v2 tests."""

from __future__ import annotations

import numpy as np

from roof_pipeline.planes import Plane


def _make_plane(normal=(0, 0, 1), centroid=(0, 0, 5)):
    """Helper: build a Plane from normal and centroid."""
    n = np.array(normal, dtype=float)
    n /= np.linalg.norm(n)
    if n[2] < 0:
        n = -n
    c = np.array(centroid, dtype=float)
    return Plane(normal=n, centroid=c, rms_residual=0.01, d=float(n @ c))
