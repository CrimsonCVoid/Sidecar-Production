"""Pairwise edge snapping to close gaps where panels meet (ridges, hips).

Two snapping "modes" are exposed:

  * 3D mode (``snap_shared_corners``, ``densify_shared_edges``, ``snap_shared_edges``)
    is the original behavior: adjacency uses full 3D distance. Good when panels
    literally touch in 3D (e.g. a gable ridge where both sides meet at the same
    elevation).

  * 2D (plan-view) mode (``snap_shared_corners_xy``, ``densify_shared_edges_xy``)
    uses only XY distance for adjacency, then reconstructs each panel's Z by
    projecting the merged XY back onto that panel's own fitted plane. This is
    the right logic for roofs where panels share an edge in PLAN VIEW but sit
    at different elevations -- e.g. a low patio roof abutting a taller main
    roof. The two panels read as logically adjacent (for edge/trim labeling)
    without the 3D mesh fusing them.
"""

from __future__ import annotations

import logging

import numpy as np

from .planes import Plane

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers for the 2D (plan-view) mode
# ---------------------------------------------------------------------------

def _z_on_plane(x: float, y: float, plane: Plane) -> float:
    """Z-coordinate on ``plane`` at world (x, y). Uses n . p = d.

    If the plane is (nearly) vertical, nz approaches 0 and we can't invert;
    the caller should handle that case (unusual for roof faces).
    """
    nx, ny, nz = plane.normal
    if abs(nz) < 1e-9:
        return float(plane.centroid[2])  # fallback: centroid Z
    return (plane.d - nx * x - ny * y) / nz


def _point_to_segment_dist_xy(
    p: np.ndarray, a: np.ndarray, b: np.ndarray,
) -> tuple[float, float]:
    """Shortest XY distance from ``p`` to segment ``ab``. Returns (distance, t)
    where t is the parameter along ab of the closest point (clamped to [0,1])."""
    p2, a2, b2 = p[:2], a[:2], b[:2]
    ab = b2 - a2
    denom = float(ab @ ab)
    if denom == 0.0:
        return float(np.linalg.norm(p2 - a2)), 0.0
    t = float((p2 - a2) @ ab) / denom
    t_clamped = max(0.0, min(1.0, t))
    closest = a2 + t_clamped * ab
    return float(np.linalg.norm(p2 - closest)), t_clamped


def _point_to_segment_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """Shortest distance from 3D point ``p`` to segment ``ab``."""
    ab = b - a
    denom = float(ab @ ab)
    if denom == 0.0:
        return float(np.linalg.norm(p - a))
    t = float((p - a) @ ab) / denom
    t = max(0.0, min(1.0, t))
    closest = a + t * ab
    return float(np.linalg.norm(p - closest))


def _edges_match(
    a0: np.ndarray, a1: np.ndarray,
    b0: np.ndarray, b1: np.ndarray,
    tol: float,
) -> bool:
    """Both endpoints of A near segment B and vice versa => shared edge."""
    return (
        _point_to_segment_dist(a0, b0, b1) <= tol
        and _point_to_segment_dist(a1, b0, b1) <= tol
        and _point_to_segment_dist(b0, a0, a1) <= tol
        and _point_to_segment_dist(b1, a0, a1) <= tol
    )


def densify_shared_edges(
    polygons: dict[int, np.ndarray],
    tol: float = 0.5,
) -> dict[int, np.ndarray]:
    """Insert collinear vertices so two adjacent panels truly share their edge.

    Scenario: panel A has corners (P1, P2) along a shared eave; panel B has
    (P1, Q, P2) where Q is an extra mid-edge click. After corner-snapping,
    P1 and P2 are identical in both, but A's edge is the straight line
    P1->P2 while B's edge zig-zags through Q. If Q is even slightly off
    the P1->P2 line you get a thin triangular gap.

    Fix: for every other panel's vertex Q that falls within ``tol`` of an
    edge (P_i, P_{i+1}) of panel A -- but is NOT close to either endpoint
    -- project Q onto that edge line and insert the projection into A's
    polygon between P_i and P_{i+1}. After this, both polygons have the
    same number of vertices along the shared edge, all collinear, no gap.

    Idempotent over a few passes; we run it once -- it handles the common
    "one extra click on one side" case cleanly.
    """
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    insert_count = 0

    for pid_a in list(out.keys()):
        # Collect candidate vertices from every OTHER panel
        candidates: list[np.ndarray] = []
        for pid_b, poly_b in out.items():
            if pid_b == pid_a:
                continue
            candidates.extend(poly_b)
        if not candidates:
            continue

        # Walk A's edges and decide which candidates project onto each one.
        # Build the new polygon by appending each original vertex followed
        # by any candidates that fall along the edge to the next vertex.
        poly_a = out[pid_a]
        n = poly_a.shape[0]
        new_verts: list[np.ndarray] = []

        for i in range(n):
            p0 = poly_a[i]
            p1 = poly_a[(i + 1) % n]
            new_verts.append(p0)

            edge = p1 - p0
            edge_len2 = float(edge @ edge)
            if edge_len2 < 1e-12:
                continue

            # Find candidates that project onto interior of this edge,
            # within `tol` perpendicular distance, AND are not within tol
            # of either endpoint (so we don't duplicate corners).
            insertions: list[tuple[float, np.ndarray]] = []  # (t, point)
            for q in candidates:
                t = float((q - p0) @ edge) / edge_len2
                if not (0.05 < t < 0.95):
                    continue
                proj = p0 + t * edge
                if float(np.linalg.norm(q - proj)) > tol:
                    continue
                # Skip if near an existing edge vertex (handled by corner-snap)
                if float(np.linalg.norm(q - p0)) <= tol:
                    continue
                if float(np.linalg.norm(q - p1)) <= tol:
                    continue
                insertions.append((t, proj))

            if not insertions:
                continue

            # Sort along the edge and dedupe near-coincident projections
            insertions.sort(key=lambda x: x[0])
            kept: list[tuple[float, np.ndarray]] = []
            for t, p in insertions:
                if kept and abs(t - kept[-1][0]) * (edge_len2 ** 0.5) < tol:
                    continue
                kept.append((t, p))
            for _, p in kept:
                new_verts.append(p)
                insert_count += 1

        out[pid_a] = np.array(new_verts)

    log.info("densified %d new vertices along shared edges (tol=%.3f m)",
             insert_count, tol)
    return out


def snap_shared_corners(
    polygons: dict[int, np.ndarray],
    tol: float = 1.0,
) -> dict[int, np.ndarray]:
    """Merge clicked corners across panels that fall within ``tol`` meters.

    The labeler captures one click per corner; when two panels share a
    corner (ridge endpoint, hip junction) the user clicked it twice -- once
    per panel -- and the two clicks are off by a few cm to a meter. This
    function groups all near-coincident vertices and replaces each group
    with its centroid, so adjacent panels' shared corners become exactly
    identical and the mesh has zero gap there.

    Operates on each polygon's full vertex list -- it doesn't matter which
    edges they belong to. Compare with snap_shared_edges() which works on
    edge segments and is the right primitive for re-traced contours.

    Algorithm:
      1. Flatten all (panel_id, vertex_index, xyz) into a list.
      2. Union-find: for each pair within tol, merge their groups.
      3. Each group collapses to its centroid; write back to both polys.
    """
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    items: list[tuple[int, int, np.ndarray]] = []
    for pid, poly in out.items():
        for vi, v in enumerate(poly):
            items.append((pid, vi, v))

    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    tol2 = tol * tol
    for i in range(n):
        vi = items[i][2]
        for j in range(i + 1, n):
            vj = items[j][2]
            d = vi - vj
            if float(d @ d) <= tol2:
                union(i, j)

    # Group items by root, compute centroid, write back to polygons
    groups: dict[int, list[int]] = {}
    for i in range(n):
        r = find(i)
        groups.setdefault(r, []).append(i)

    snap_count = 0
    for members in groups.values():
        if len(members) <= 1:
            continue
        verts = np.stack([items[m][2] for m in members])
        centroid = verts.mean(axis=0)
        for m in members:
            pid, vi, _ = items[m]
            out[pid][vi] = centroid
        snap_count += len(members) - 1

    log.info("snapped %d corners into shared positions (tol=%.3f m)",
             snap_count, tol)
    return out


def snap_shared_corners_xy(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> dict[int, np.ndarray]:
    """2D-adjacency version of ``snap_shared_corners``.

    Clusters vertices by XY distance (ignoring Z entirely). Each cluster
    collapses to a shared target XY. Each member's Z is then RECONSTRUCTED
    by projecting that XY onto its own panel's fitted plane, so the two
    panels share the XY but their Z values track their own surfaces.

    That means adjacent panels at different elevations (say, a low patio
    abutting a tall main roof) get a clean shared corner in plan view
    while their 3D geometry stays accurate to each fitted plane.
    """
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    items: list[tuple[int, int, np.ndarray]] = []
    for pid, poly in out.items():
        for vi, v in enumerate(poly):
            items.append((pid, vi, v))

    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    tol2 = tol * tol
    for i in range(n):
        vi_xy = items[i][2][:2]
        for j in range(i + 1, n):
            vj_xy = items[j][2][:2]
            d = vi_xy - vj_xy
            if float(d @ d) <= tol2:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    snap_count = 0
    for members in groups.values():
        if len(members) <= 1:
            continue
        # Target XY = centroid of members' XYs. Each member's Z is then the
        # Z of its own plane at that XY.
        xy = np.stack([items[m][2][:2] for m in members]).mean(axis=0)
        for m in members:
            pid, vi, _ = items[m]
            plane = planes.get(pid)
            if plane is None:
                out[pid][vi] = np.array([xy[0], xy[1], items[m][2][2]])
                continue
            z = _z_on_plane(float(xy[0]), float(xy[1]), plane)
            out[pid][vi] = np.array([xy[0], xy[1], z])
        snap_count += len(members) - 1

    log.info("snapped %d corners in plan view (tol=%.3f m, XY-adjacency)",
             snap_count, tol)
    return out


def densify_shared_edges_xy(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 0.6,
) -> dict[int, np.ndarray]:
    """2D-adjacency version of ``densify_shared_edges``.

    For every other panel's vertex Q, check if Q's XY projects onto an
    interior point of edge (A_i, A_{i+1}) of panel A within ``tol`` XY
    distance (NOT 3D). When so, insert a new vertex on A's polygon at
    that XY, with Z recovered from panel A's fitted plane. This closes
    the "one panel had an extra mid-edge click, the other didn't" case
    without caring whether the two panels are at the same elevation.
    """
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    insert_count = 0

    for pid_a in list(out.keys()):
        plane_a = planes.get(pid_a)
        candidates: list[np.ndarray] = []
        for pid_b, poly_b in out.items():
            if pid_b == pid_a:
                continue
            candidates.extend(poly_b)
        if not candidates:
            continue

        poly_a = out[pid_a]
        n = poly_a.shape[0]
        new_verts: list[np.ndarray] = []

        for i in range(n):
            p0 = poly_a[i]
            p1 = poly_a[(i + 1) % n]
            new_verts.append(p0)

            edge_xy = (p1 - p0)[:2]
            edge_len2 = float(edge_xy @ edge_xy)
            if edge_len2 < 1e-12:
                continue

            insertions: list[tuple[float, np.ndarray]] = []
            for q in candidates:
                d_xy, t = _point_to_segment_dist_xy(q, p0, p1)
                if not (0.05 < t < 0.95):
                    continue
                if d_xy > tol:
                    continue
                # Don't duplicate corners handled by the XY corner-snap pass
                if float(np.linalg.norm((q - p0)[:2])) <= tol:
                    continue
                if float(np.linalg.norm((q - p1)[:2])) <= tol:
                    continue
                # Build the inserted vertex on PANEL A's plane at the
                # projected XY, so the polygon stays planar.
                proj_xy = p0[:2] + t * edge_xy
                if plane_a is not None:
                    z = _z_on_plane(float(proj_xy[0]), float(proj_xy[1]), plane_a)
                else:
                    z = float(0.5 * (p0[2] + p1[2]))
                insertions.append((t, np.array([proj_xy[0], proj_xy[1], z])))

            if not insertions:
                continue

            insertions.sort(key=lambda x: x[0])
            kept: list[tuple[float, np.ndarray]] = []
            for t, p in insertions:
                if kept and abs(t - kept[-1][0]) * (edge_len2 ** 0.5) < tol:
                    continue
                kept.append((t, p))
            for _, p in kept:
                new_verts.append(p)
                insert_count += 1

        out[pid_a] = np.array(new_verts)

    log.info("densified %d new vertices in plan view (tol=%.3f m, XY-adjacency)",
             insert_count, tol)
    return out


def snap_shared_edges(
    polygons: dict[int, np.ndarray],
    tol: float = 0.15,
) -> dict[int, np.ndarray]:
    """Snap near-coincident edges from different panels to their midline.

    For each pair of panels, every (a_i, a_{i+1}) edge from panel A is
    compared against every edge of panel B. If they match within ``tol`` we:

      1. Pick the endpoint pairing with smaller total distance --
         (a0->b0, a1->b1) or the swapped (a0->b1, a1->b0).
      2. Replace each pair with its midpoint, then write those midpoints
         back into both panels' vertex arrays.

    Result: both panels' shared edge sits exactly on the same line, so the
    exported mesh has no ridge gap. Vertices not part of a shared edge are
    untouched.

    Complexity is O(P^2 * E^2) which is fine for tens of panels with tens
    of edges each. The polygon vertex count after RDP is small.
    """
    # Work on copies so we don't mutate the input
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    panel_ids = sorted(out.keys())
    snap_count = 0

    for i, pid_a in enumerate(panel_ids):
        for pid_b in panel_ids[i + 1:]:
            poly_a = out[pid_a]
            poly_b = out[pid_b]
            n_a = poly_a.shape[0]
            n_b = poly_b.shape[0]

            for ea in range(n_a):
                a0 = poly_a[ea]
                a1 = poly_a[(ea + 1) % n_a]
                for eb in range(n_b):
                    b0 = poly_b[eb]
                    b1 = poly_b[(eb + 1) % n_b]
                    if not _edges_match(a0, a1, b0, b1, tol):
                        continue

                    # Pick endpoint pairing with lower total distance
                    direct = np.linalg.norm(a0 - b0) + np.linalg.norm(a1 - b1)
                    swapped = np.linalg.norm(a0 - b1) + np.linalg.norm(a1 - b0)
                    if direct <= swapped:
                        m_for_a0 = 0.5 * (a0 + b0)
                        m_for_a1 = 0.5 * (a1 + b1)
                        poly_b[eb] = m_for_a0
                        poly_b[(eb + 1) % n_b] = m_for_a1
                    else:
                        m_for_a0 = 0.5 * (a0 + b1)
                        m_for_a1 = 0.5 * (a1 + b0)
                        poly_b[(eb + 1) % n_b] = m_for_a0
                        poly_b[eb] = m_for_a1

                    poly_a[ea] = m_for_a0
                    poly_a[(ea + 1) % n_a] = m_for_a1
                    snap_count += 1

    log.info("snapped %d shared edges (tol=%.3f m)", snap_count, tol)
    return out
