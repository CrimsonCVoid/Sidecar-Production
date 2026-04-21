"""Shapely polygon validation with graduated repair (TOPO-10, D-04, D-05, D-06).

Two-pass validation:
  Pass 1 (stage="solver"): Read-only diagnostic. is_valid + is_simple checks only.
    No repair. Failures log at DEBUG. This separates solver quality from densify quality.
  Pass 2 (stage="densify"): Correctness gate. make_valid() if needed. Area change
    tolerance: < 0.1% silent, 0.1-1% WARNING, >= 1% RuntimeError.
"""

from __future__ import annotations

import logging

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
from shapely.validation import explain_validity, make_valid

from ..planes import Plane
from .winding import _project_to_2d, _plane_basis

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AREA_WARN_THRESHOLD = 0.001    # 0.1%
_AREA_FAIL_THRESHOLD = 0.01    # 1.0%
_MULTI_AREA_RATIO_MIN = 0.95   # 95% -- below this, too much geometry lost

# Nearest-neighbor match threshold for 3D reconstruction (metres in 2D plane)
_NN_MATCH_THRESHOLD = 1e-8


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _z_on_plane(x: float, y: float, plane: Plane) -> float:
    """Z-coordinate on ``plane`` at world (x, y). Uses n . p = d."""
    nx, ny, nz = plane.normal
    if abs(nz) < 1e-9:
        return float(plane.centroid[2])
    return (plane.d - nx * x - ny * y) / nz


def _reconstruct_3d(
    repaired_2d: np.ndarray,
    original_2d: np.ndarray,
    original_3d: np.ndarray,
    plane: Plane,
    pid: int,
) -> np.ndarray:
    """Reconstruct 3D coordinates from repaired 2D vertices.

    For each repaired 2D vertex, find the nearest original 2D vertex.
    If within _NN_MATCH_THRESHOLD, reuse the original 3D position (avoids
    floating-point drift). Otherwise, inverse-project through the plane
    to recover 3D coordinates with Z from _z_on_plane.

    Per review notes: if more than 10% of vertices have no close match,
    log WARNING about structural repair.
    """
    K = len(repaired_2d)
    result_3d = np.empty((K, 3))
    no_match_count = 0

    # Precompute inverse projection basis
    u, v = _plane_basis(plane.normal)

    for i, rv in enumerate(repaired_2d):
        # Find nearest original vertex
        diffs = original_2d - rv
        sq_dists = np.einsum("ij,ij->i", diffs, diffs)
        idx = int(np.argmin(sq_dists))

        if sq_dists[idx] < _NN_MATCH_THRESHOLD:
            # Close match: reuse original 3D position
            result_3d[i] = original_3d[idx]
        else:
            # No close match: inverse-project from 2D plane coords to 3D
            no_match_count += 1
            # repaired_2d[i] = (du, dv) in plane-local frame
            # 3D = centroid + du * u + dv * v
            world_3d = plane.centroid + rv[0] * u + rv[1] * v
            # Override Z from plane equation for consistency
            z = _z_on_plane(float(world_3d[0]), float(world_3d[1]), plane)
            result_3d[i] = np.array([world_3d[0], world_3d[1], z])

    if no_match_count > 0 and K > 0 and no_match_count / K > 0.10:
        log.warning(
            "panel %d: make_valid performed structural repair "
            "(%d/%d vertices relocated)",
            pid, no_match_count, K,
        )

    return result_3d


def _extract_largest_polygon(geom, pid: int) -> Polygon | None:
    """Extract the largest Polygon from a geometry result.

    Handles MultiPolygon, GeometryCollection, and plain Polygon.
    Applies D-06 ratio check for MultiPolygon cases. Returns None when
    the input degraded to a non-polygon type (LineString / Point) --
    caller should fall back to the pre-repair polygon.
    """
    if isinstance(geom, Polygon):
        return geom

    # Extract polygon pieces from MultiPolygon or GeometryCollection
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        polys = [
            g for g in geom.geoms
            if isinstance(g, Polygon) and g.area > 0
        ]
        if not polys:
            raise RuntimeError(
                f"panel {pid}: make_valid produced no valid polygons"
            )

        if len(polys) == 1:
            return polys[0]

        largest = max(polys, key=lambda g: g.area)
        total_poly_area = sum(p.area for p in polys)

        if total_poly_area > 0:
            ratio = largest.area / total_poly_area
        else:
            ratio = 0.0

        if ratio < _MULTI_AREA_RATIO_MIN:
            raise RuntimeError(
                f"panel {pid}: make_valid produced MultiPolygon with "
                f"largest piece ratio {ratio:.3f} < 0.95 -- "
                f"too much geometry lost"
            )

        log.warning(
            "panel %d: MultiPolygon from make_valid, keeping largest "
            "piece (ratio=%.3f)",
            pid, ratio,
        )
        return largest

    # LineString / Point / empty -- the source polygon had fewer than 3
    # distinct vertices, so make_valid correctly degraded it. Nothing
    # polygon-like to recover; signal to the caller by returning None so
    # it can fall back to the pre-repair polygon instead of crashing the
    # whole pipeline on a single bad panel.
    log.warning(
        "panel %d: make_valid returned %s (degenerate geometry); "
        "keeping pre-repair polygon and continuing",
        pid, type(geom).__name__,
    )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_polygons(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    stage: str = "solver",
    repair: bool = False,
) -> dict[int, np.ndarray]:
    """Validate (and optionally repair) polygon geometry via Shapely.

    Args:
        polygons: Panel ID to (K, 3) vertices.
        planes: Panel ID to fitted Plane.
        stage: "solver" or "densify" -- used in log messages per D-04.
        repair: If True, attempt make_valid() on invalid polygons (pass 2 only).

    Returns:
        Copy of polygons, possibly with repaired geometry if repair=True.
    """
    # ------------------------------------------------------------------
    # 1. Copy-on-write per established pipeline convention.
    # ------------------------------------------------------------------
    out = {pid: poly.copy() for pid, poly in polygons.items()}

    repaired_count = 0
    valid_count = 0

    for pid, poly in out.items():
        plane = planes[pid]

        # ------------------------------------------------------------------
        # 2. Project to 2D in the plane's local frame.
        # ------------------------------------------------------------------
        verts_2d = _project_to_2d(poly, plane)
        shp = Polygon(verts_2d)

        # ------------------------------------------------------------------
        # 3. Check validity.
        # ------------------------------------------------------------------
        if shp.is_valid and shp.is_simple:
            valid_count += 1
            continue

        # ------------------------------------------------------------------
        # 4. Invalid polygon handling.
        # ------------------------------------------------------------------
        if not repair:
            # Pass 1 (stage="solver"): read-only diagnostic
            log.debug(
                "panel %d invalid after %s: %s",
                pid, stage, explain_validity(shp),
            )
            continue

        # Pass 2 (stage="densify"): repair gate
        log.warning(
            "panel %d invalid after %s, repairing: %s",
            pid, stage, explain_validity(shp),
        )

        repaired_geom = make_valid(shp)

        # ------------------------------------------------------------------
        # 5. D-06: Handle MultiPolygon / GeometryCollection.
        # ------------------------------------------------------------------
        repaired_poly = _extract_largest_polygon(repaired_geom, pid)

        # Panel collapsed to a non-polygon (LineString / Point) -- the
        # pre-repair coords are already in `out[pid]`; leave them alone
        # and skip the rest of the repair work for this panel. The
        # downstream mesh builder may drop the panel if it's degenerate,
        # but the rest of the roof still renders.
        if repaired_poly is None:
            continue

        # ------------------------------------------------------------------
        # 6. D-05: Area change check.
        # ------------------------------------------------------------------
        original_area = abs(shp.area)
        repaired_area = repaired_poly.area

        if original_area > 0:
            delta_pct = abs(repaired_area - original_area) / original_area

            if delta_pct >= _AREA_FAIL_THRESHOLD:
                raise RuntimeError(
                    f"panel {pid}: repair changed polygon area by "
                    f"{delta_pct * 100:.2f}% (old={original_area:.6f}, "
                    f"new={repaired_area:.6f}) -- likely cause: solver "
                    f"produced vertex outside original hull, or densify "
                    f"inserted vertex on wrong side of edge. Re-label "
                    f"panel boundary or reduce --snap-tol."
                )

            if delta_pct >= _AREA_WARN_THRESHOLD:
                log.warning(
                    "panel %d: repair changed area by %.3f%% "
                    "(old=%.6f, new=%.6f)",
                    pid, delta_pct * 100, original_area, repaired_area,
                )

        # ------------------------------------------------------------------
        # 7. Write back repaired coordinates with 3D reconstruction.
        # ------------------------------------------------------------------
        repaired_2d = np.array(repaired_poly.exterior.coords[:-1])
        out[pid] = _reconstruct_3d(
            repaired_2d, verts_2d, poly, plane, pid,
        )
        repaired_count += 1

    log.info(
        "validate_%s: %d valid, %d repaired out of %d panels",
        stage, valid_count, repaired_count, len(out),
    )

    return out
