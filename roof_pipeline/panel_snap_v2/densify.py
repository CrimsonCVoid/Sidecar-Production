"""Edge-walking densification for shared edges (TOPO-09).

For each shared-edge pair in the feature graph, collects all vertices from
both touching panels that lie on or near the shared edge, sorts them by
parameter t along the edge line, and redistributes so every panel carries
the same vertex list along that edge.

Copy-on-write: the input polygons dict is never mutated (T-02-07).
"""

from __future__ import annotations

import logging

import numpy as np

from ..planes import Plane

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _z_on_plane(x: float, y: float, plane: Plane) -> float:
    """Z-coordinate on ``plane`` at world (x, y). Uses n . p = d.

    If the plane is (nearly) vertical, nz approaches 0 and we can't invert;
    fall back to centroid Z (unusual for roof faces).
    """
    nx, ny, nz = plane.normal
    if abs(nz) < 1e-9:
        return float(plane.centroid[2])
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def densify_edges(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    graph: dict,
    tol: float = 1.0,
) -> dict[int, np.ndarray]:
    """Densify shared edges so adjacent panels carry the same vertex list.

    For each edge in the feature graph (panel_a, panel_b sharing 2+ features),
    collect all vertices from both panels that lie near the shared edge line,
    sort by parameter t, and insert missing vertices into each panel's polygon.
    Z is reconstructed per-panel via _z_on_plane.

    Copy-on-write: input polygons dict is never mutated.

    Args:
        polygons: Panel ID to (K, 3) ordered boundary vertices.
        planes: Panel ID to fitted Plane dataclass.
        graph: Feature graph from build_feature_graph().
        tol: Base snap tolerance in metres.

    Returns:
        Copy of polygons with densified shared edges.
    """
    # ------------------------------------------------------------------
    # 1. Copy-on-write per established pipeline convention (T-02-07).
    # ------------------------------------------------------------------
    out = {pid: poly.copy() for pid, poly in polygons.items()}

    # Snapshot source vertices before any mutations.  Densify inserts
    # vertices from a *source* panel into a *target* panel's edges.
    # Without the snapshot, a panel that participates in 2+ graph edges
    # accumulates spurious inserted vertices: edge (A,P) inserts into P,
    # then edge (B,P) uses the already-enlarged P as source, projecting
    # those spurious vertices back onto B's edges.  Using the pre-densify
    # snapshot for source lookups breaks this mutation chain.
    source_snapshot = {pid: poly.copy() for pid, poly in out.items()}

    insert_count = 0
    edge_count = 0

    # ------------------------------------------------------------------
    # 2. For each shared edge in the feature graph, densify both panels.
    # ------------------------------------------------------------------
    for graph_edge in graph.get("edges", []):
        pid_a = graph_edge["panel_a"]
        pid_b = graph_edge["panel_b"]

        if pid_a not in out or pid_b not in out:
            continue

        edge_count += 1

        # D-05 diagnostic counters (reset per graph_edge)
        candidates_considered = 0
        edge_insertions = 0
        insertion_positions: list[tuple[float, float]] = []

        # Process both directions: insert B's vertices into A, and
        # A's vertices into B.
        for target_pid, source_pid in [(pid_a, pid_b), (pid_b, pid_a)]:
            target_plane = planes.get(target_pid)
            target_poly = out[target_pid]
            source_poly = source_snapshot[source_pid]

            n = target_poly.shape[0]
            new_verts: list[np.ndarray] = []

            for i in range(n):
                p0 = target_poly[i]
                p1 = target_poly[(i + 1) % n]
                new_verts.append(p0)

                edge_xy = (p1 - p0)[:2]
                edge_len2 = float(edge_xy @ edge_xy)
                if edge_len2 < 1e-12:
                    continue

                # Find source vertices that project onto this edge
                insertions: list[tuple[float, np.ndarray]] = []
                for q in source_poly:
                    candidates_considered += 1
                    d_xy, t = _point_to_segment_dist_xy(q, p0, p1)

                    # Skip near-endpoints (0.05 < t < 0.95)
                    if not (0.05 < t < 0.95):
                        continue
                    if d_xy > tol:
                        continue

                    # Skip if near an existing vertex (endpoint dedup)
                    if float(np.linalg.norm((q - p0)[:2])) <= tol:
                        continue
                    if float(np.linalg.norm((q - p1)[:2])) <= tol:
                        continue

                    # Project onto the edge in XY and reconstruct Z
                    proj_xy = p0[:2] + t * edge_xy
                    if target_plane is not None:
                        z = _z_on_plane(
                            float(proj_xy[0]), float(proj_xy[1]),
                            target_plane,
                        )
                    else:
                        z = float(0.5 * (p0[2] + p1[2]))

                    insertions.append(
                        (t, np.array([proj_xy[0], proj_xy[1], z])),
                    )

                if not insertions:
                    continue

                # Sort by parameter t along the edge
                insertions.sort(key=lambda x: x[0])

                # Dedupe near-coincident projections
                edge_len = edge_len2 ** 0.5
                kept: list[tuple[float, np.ndarray]] = []
                for t, p in insertions:
                    if kept and abs(t - kept[-1][0]) * edge_len < tol:
                        continue
                    kept.append((t, p))

                for _, p in kept:
                    new_verts.append(p)
                    insert_count += 1
                    edge_insertions += 1
                    insertion_positions.append((float(p[0]), float(p[1])))

            out[target_pid] = np.array(new_verts)

        # D-05: per-shared-edge diagnostic log
        log.debug(
            "densify edge panel_a=%d panel_b=%d "
            "candidates_considered=%d vertices_inserted=%d "
            "insertion_positions_xy=%s",
            pid_a, pid_b,
            candidates_considered,
            edge_insertions,
            insertion_positions,
        )

    # ------------------------------------------------------------------
    # 3. Summary log.
    # ------------------------------------------------------------------
    log.info(
        "densified %d vertices across %d shared edges",
        insert_count, edge_count,
    )

    return out
