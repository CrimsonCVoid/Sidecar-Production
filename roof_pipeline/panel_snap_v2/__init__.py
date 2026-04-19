"""Topology-aware snap engine v2: mesh-weld snapping for ridges and hip apices.

Replaces the pairwise edge snap in snapping.py with a union-find clustering +
feature graph approach that handles 3+ panels meeting at hip/ridge apices.

Public API: snap_polygons() -- drop-in replacement for snap_shared_edges()
with an extended signature (accepts planes dict for plane-aware solving).

Pipeline stages:
  1. Normalize winding (CCW)
  2. Build feature graph (clustering + valence classification)
  3. Solve apex positions (valence-2/3/4+ dispatch)
  4. Validate pass 1: read-only diagnostic (D-04)
  5. Densify shared edges
  6. Validate pass 2: repair gate (D-04, D-05, D-06)
"""

from __future__ import annotations

import logging

import numpy as np

from ..planes import Plane
from .clustering import cluster_vertices
from .densify import densify_edges
from .graph import build_feature_graph
from .solver import solve_apices
from .validate import validate_polygons
from .winding import normalize_winding

log = logging.getLogger(__name__)


def _update_graph_positions(
    graph: dict,
    polygons: dict[int, np.ndarray],
) -> None:
    """Fill in position_xyz for each feature node from solved polygon vertices.

    After solving, each cluster's position is the actual vertex position in
    the polygon arrays. For each feature with valence >= 2, we find the
    vertex from the first member panel that is closest (in XY) to a vertex
    in another member panel. This is the shared/solved vertex.

    For valence-1 (unshared) features, position_xyz stays None -- these
    are not written to the sidecar JSON in any meaningful way.
    """
    for feature in graph["features"]:
        panel_ids = feature["panel_ids"]
        if len(panel_ids) < 2:
            # Unshared vertex -- no solved position
            continue

        pid_a = panel_ids[0]
        pid_b = panel_ids[1]

        if pid_a not in polygons or pid_b not in polygons:
            continue

        poly_a = polygons[pid_a]
        poly_b = polygons[pid_b]

        # Find the vertex in poly_a that is nearest to any vertex in poly_b
        # (in XY). After solving, shared vertices have matching XY positions.
        best_dist = float("inf")
        best_pos = None

        for va in poly_a:
            dists_xy = np.linalg.norm(poly_b[:, :2] - va[:2], axis=1)
            min_dist = float(np.min(dists_xy))
            if min_dist < best_dist:
                best_dist = min_dist
                best_pos = va

        if best_pos is not None and best_dist < 1.0:
            feature["position_xyz"] = [
                float(best_pos[0]),
                float(best_pos[1]),
                float(best_pos[2]),
            ]


def snap_polygons(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> tuple[dict[int, np.ndarray], dict]:
    """Topology-aware snap: cluster, solve apices, densify edges, validate.

    Drop-in replacement for snapping.snap_shared_edges (TOPO-01), with an
    extended signature that accepts planes (needed for plane-aware solving).

    Returns:
        (snapped_polygons, feature_graph) -- the graph is needed by run_real.py
        for the snap_v2_features.json sidecar (INTG-02).
    """
    # Copy-on-write per established pipeline convention
    out = {pid: poly.copy() for pid, poly in polygons.items()}

    # 1. Normalize winding to CCW
    out = normalize_winding(out, planes)

    # 2. Build feature graph (clustering inside)
    graph = build_feature_graph(out, planes, tol=tol)

    # 3. Solve apex positions
    out, solved_positions = solve_apices(out, planes, graph, tol=tol)

    # 4. Validate pass 1: read-only diagnostic (D-04)
    #    No repair, logs at DEBUG. Tells us solver quality separately from densify.
    validate_polygons(out, planes, stage="solver", repair=False)

    # 5. Densify shared edges
    out = densify_edges(out, planes, graph, tol=tol)

    # 6. Validate pass 2: repair gate (D-04, D-05, D-06)
    out = validate_polygons(out, planes, stage="densify", repair=True)

    # Update feature graph positions now that solver has run
    _update_graph_positions(graph, out)

    return out, graph
