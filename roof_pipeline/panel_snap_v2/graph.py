"""Feature graph construction from clustered vertex groups.

Builds a feature graph (INTG-02 schema) from the output of cluster_vertices().
Each cluster becomes a feature node with a valence equal to the number of
distinct panels that contributed vertices to that cluster.

Valence classification:
  1 -- unshared (isolated vertex, belongs to one panel only)
  2 -- corner (two panels share this vertex)
  3 -- ridge_apex (three panels meet at this point)
  4+ -- hip_apex (four or more panels converge)

Phase 1 scope: position_xyz is always None. The solver that places the welded
apex at the geometrically correct position is implemented in Phase 2.
"""

from __future__ import annotations

import json
import logging
import sys

import numpy as np

from ..planes import Plane
from .clustering import cluster_vertices
from .winding import normalize_winding

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_feature_graph(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> dict:
    """Build feature graph from polygon vertices.

    Steps:
    1. Normalize winding to CCW (handles mixed-winding inputs, e.g. TEST-05)
    2. Cluster vertices with three-pass expanding tolerance
    3. Build nodes (one per cluster) with valence = number of distinct panels
    4. Build edges (one per panel pair sharing 2+ features)

    Returns dict matching INTG-02 schema:
    {
        "features": [{"id": int, "valence": int, "position_xyz": null, "panel_ids": [int]}],
        "edges": [{"panel_a": int, "panel_b": int, "feature_ids": [int]}]
    }

    Args:
        polygons: Panel ID to (K, 3) ordered boundary vertices.
        planes: Panel ID to fitted Plane dataclass. Required for winding
            normalization (plane normal defines the 2D projection basis).
        tol: Base snap tolerance in metres for vertex clustering.

    Returns:
        Feature graph dict conforming to INTG-02 schema.
    """
    # -------------------------------------------------------------------
    # 1. Normalize winding to ensure consistent CCW vertex order.
    #    This handles TEST-05: panels with opposite winding still produce
    #    the correct shared-vertex clusters after normalization.
    # -------------------------------------------------------------------
    normed = normalize_winding(polygons, planes)

    # -------------------------------------------------------------------
    # 2. Cluster vertices.
    # -------------------------------------------------------------------
    groups, items = cluster_vertices(normed, planes, tol=tol)

    # -------------------------------------------------------------------
    # 3. Build feature nodes.
    #    One node per cluster. panel_ids = sorted unique panel IDs from
    #    all items in the cluster. valence = len(panel_ids).
    # -------------------------------------------------------------------
    features: list[dict] = []
    feature_id = 0
    # Map from cluster root index -> feature id (for edge building below)
    root_to_feature_id: dict[int, int] = {}

    # Map from item index -> feature id (for quick lookup)
    item_to_feature_id: dict[int, int] = {}

    for root, members in groups.items():
        # Collect unique panel IDs for this cluster
        panel_ids = sorted({items[m][0] for m in members})
        valence = len(panel_ids)

        # Log classification per D-03
        if valence == 1:
            label = "unshared"
        elif valence == 2:
            label = "corner"
        elif valence == 3:
            label = "ridge_apex"
        else:
            label = f"hip_apex(v{valence})"

        log.info(
            "feature %d: valence=%d (%s) panels=%s",
            feature_id, valence, label, panel_ids,
        )

        feature_dict = {
            "id": feature_id,
            "valence": valence,
            "position_xyz": None,  # Phase 1: solver not yet implemented
            "panel_ids": panel_ids,
        }
        features.append(feature_dict)
        root_to_feature_id[root] = feature_id
        for m in members:
            item_to_feature_id[m] = feature_id
        feature_id += 1

    # -------------------------------------------------------------------
    # 4. Build edges.
    #    For each pair of panels (a, b) where a < b, collect all feature
    #    IDs where both panels appear in that feature's panel_ids.
    #    If there are 2+ such features, create an edge entry.
    # -------------------------------------------------------------------
    all_panel_ids = sorted(polygons.keys())
    edges: list[dict] = []

    for i, pid_a in enumerate(all_panel_ids):
        for pid_b in all_panel_ids[i + 1:]:
            shared_feature_ids = [
                f["id"]
                for f in features
                if pid_a in f["panel_ids"] and pid_b in f["panel_ids"]
            ]
            if len(shared_feature_ids) >= 2:
                edges.append({
                    "panel_a": pid_a,
                    "panel_b": pid_b,
                    "feature_ids": sorted(shared_feature_ids),
                })

    # -------------------------------------------------------------------
    # 5. Log summary per D-03
    # -------------------------------------------------------------------
    log.info(
        "feature graph: %d nodes, %d edges", len(features), len(edges),
    )
    valence_counts: dict[int, int] = {}
    for f in features:
        v = f["valence"]
        valence_counts[v] = valence_counts.get(v, 0) + 1
    for v in sorted(valence_counts):
        v_label = {1: "unshared", 2: "corner", 3: "ridge_apex"}.get(
            v, f"hip_apex(v{v})"
        )
        log.info("  valence-%d (%s): %d nodes", v, v_label, valence_counts[v])

    return {"features": features, "edges": edges}


def print_dryrun(graph: dict) -> None:
    """Print feature graph JSON to stdout, summary to stderr, then exit(0).

    Per D-01: JSON to stdout, human-readable summary to stderr.
    Per D-03: Summary shows total node/edge counts and valence distribution.
    """
    json.dump(graph, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()

    # Summary to stderr (per D-03)
    features = graph["features"]
    edges = graph["edges"]
    valence_counts: dict[int, int] = {}
    for f in features:
        v = f["valence"]
        valence_counts[v] = valence_counts.get(v, 0) + 1

    print("--- snap-v2 dry-run summary ---", file=sys.stderr)
    print(f"nodes: {len(features)}, edges: {len(edges)}", file=sys.stderr)
    for v in sorted(valence_counts):
        label = {1: "unshared", 2: "corner", 3: "ridge_apex"}.get(
            v, f"hip_apex(v{v})"
        )
        print(f"  valence-{v} ({label}): {valence_counts[v]} nodes", file=sys.stderr)
    print("-------------------------------", file=sys.stderr)
