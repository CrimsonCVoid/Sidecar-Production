"""Per-panel winding normalization to consistent CCW order.

Projects each panel's 3D boundary vertices into the plane's local 2D frame
(using the panel's fitted normal via an orthonormal basis), passes the result
to Shapely's orient() for CCW enforcement, then applies the resulting vertex
permutation back to the original 3D array. This avoids round-trip floating-
point drift from 2D -> 3D reconstruction (D-10) and handles non-convex
(L-shaped) panels correctly (D-08, D-09).

Self-intersecting (bowtie) polygons raise TopologicalError with the panel ID
in the message so callers can identify the offending panel (D-11).
"""

from __future__ import annotations

import logging

import numpy as np
from shapely.errors import TopologicalError
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from ..planes import Plane

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two orthonormal in-plane vectors (u, v) given a unit normal.

    Replicates the algorithm from mesh.py _plane_basis (lines 17-32).
    Pick an arbitrary world axis least aligned with the normal, project it
    into the plane to get u, then v = n x u. This avoids the degenerate case
    where the seed vector is parallel to the normal (D-09).
    """
    # Choose world axis least aligned with normal
    if abs(normal[0]) < 0.9:
        seed = np.array([1.0, 0.0, 0.0])
    else:
        seed = np.array([0.0, 1.0, 0.0])
    u = seed - (seed @ normal) * normal
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    return u, v


def _project_to_2d(verts_3d: np.ndarray, plane: Plane) -> np.ndarray:
    """Project (K, 3) 3D vertices onto the plane's local 2D coordinate frame.

    Uses the orthonormal basis (u, v) derived from the plane normal. Returns
    a (K, 2) array of local coordinates. Does NOT use naive XY-drop, which
    fails on steep-pitch panels whose polygon projects to a near-degenerate
    line in the XY plane (D-09).
    """
    u, v = _plane_basis(plane.normal)
    delta = verts_3d - plane.centroid
    return np.column_stack([delta @ u, delta @ v])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_winding(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
) -> dict[int, np.ndarray]:
    """Normalize all panel polygons to consistent CCW vertex order.

    For each panel, projects the 3D boundary into the panel's local 2D plane
    frame, uses Shapely orient(sign=1.0) to enforce CCW ordering, then maps
    the resulting vertex permutation back to the original 3D array.

    Copy-on-write: the input `polygons` dict is never mutated.

    Raises:
        ValueError: if any polygon has invalid shape (not (K>=3, 3)).
        TopologicalError: if any polygon is self-intersecting (e.g., bowtie).
            The error message includes the panel ID for diagnosis (D-11).
    """
    # Copy-on-write per established pipeline convention
    out: dict[int, np.ndarray] = {pid: poly.copy() for pid, poly in polygons.items()}

    for pid, poly in out.items():
        # --- Input validation (T-01-01) ---
        if poly.ndim != 2 or poly.shape[1] != 3 or poly.shape[0] < 3:
            raise ValueError(
                f"panel {pid}: need (K>=3, 3) vertices, got shape {poly.shape}"
            )

        plane = planes[pid]

        # --- Project to 2D in the plane's local frame (D-09) ---
        verts_2d = _project_to_2d(poly, plane)

        # --- Build Shapely polygon and check validity (D-11) ---
        shp = Polygon(verts_2d)

        if not shp.is_simple:
            raise TopologicalError(
                f"panel {pid}: self-intersecting polygon cannot be oriented"
            )

        # Orient CCW: sign=1.0 means positive (CCW) orientation in Shapely
        try:
            oriented = orient(shp, sign=1.0)
        except (TopologicalError, Exception) as e:
            raise TopologicalError(
                f"panel {pid}: self-intersecting polygon cannot be oriented"
            ) from e

        # --- Extract oriented 2D coordinates (drop closing duplicate) ---
        oriented_2d = np.array(oriented.exterior.coords[:-1])

        # --- Recover permutation: match oriented_2d rows back to verts_2d (D-10) ---
        # For each oriented vertex, find the nearest original vertex by L2 distance.
        # This avoids 2D -> 3D round-trip floating-point drift.
        K = len(verts_2d)
        perm = np.empty(K, dtype=int)
        for i, ov in enumerate(oriented_2d):
            diffs = verts_2d - ov  # (K, 2)
            dists = np.einsum("ij,ij->i", diffs, diffs)  # squared distances
            idx = int(np.argmin(dists))
            assert dists[idx] < 1e-16, (
                f"panel {pid}: oriented vertex {i} has no matching original vertex "
                f"(min_sq_dist={dists[idx]:.2e})"
            )
            perm[i] = idx

        # --- Canonicalize starting vertex to ensure deterministic output (D-10) ---
        # Two CCW rings of the same polygon may start at different vertices depending
        # on whether the input was already CCW or was reversed from CW. Choose the
        # canonical starting vertex by lexicographic minimum of the 2D projected
        # coordinates (not by original input indices, which differ between CW/CCW
        # inputs). This guarantees identical output for both orderings.
        oriented_3d = poly[perm]
        oriented_2d_mapped = _project_to_2d(oriented_3d, plane)
        # Lexicographic sort: primary key = first coord, secondary = second coord
        lex_keys = [(float(r[0]), float(r[1])) for r in oriented_2d_mapped]
        start = int(min(range(K), key=lambda i: lex_keys[i]))
        perm = np.roll(perm, -start)

        # Apply permutation to original 3D array
        out[pid] = poly[perm]

    log.info("normalized winding for %d panels", len(out))
    return out
