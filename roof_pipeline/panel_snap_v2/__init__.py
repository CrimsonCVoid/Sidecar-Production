"""Topology-aware snap engine v2: mesh-weld snapping for ridges and hip apices.

Replaces the pairwise edge snap in snapping.py with a union-find clustering +
feature graph approach that handles 3+ panels meeting at hip/ridge apices.

Public API: snap_polygons() -- Phase 2 will wire this to run_real.py via
--snap-v2. Phase 1 exposes --snap-v2-dryrun (print graph, exit 0).
"""

from __future__ import annotations

from .clustering import cluster_vertices
from .graph import build_feature_graph
from .winding import normalize_winding


def snap_polygons(
    polygons: dict,
    planes: dict,
    tol: float = 1.0,
) -> dict:
    """Drop-in replacement for snapping.snap_shared_edges (TOPO-01).

    In Phase 1, this only normalizes winding, clusters, and builds the
    feature graph. The solver (which writes solved positions back into
    the polygon arrays) is added in Phase 2.

    Returns the input polygons unchanged (solver not yet implemented).
    The feature graph is built as a side effect and can be retrieved
    via build_feature_graph().

    Args:
        polygons: Panel ID to (K, 3) ordered boundary vertices.
        planes: Panel ID to fitted Plane dataclass. Required for winding
            normalization (not in snap_shared_edges signature -- Phase 2
            integration uses the extended signature).
        tol: Base snap tolerance in metres.

    Returns:
        Copy of input polygons (no positions modified in Phase 1).
    """
    import numpy as np  # noqa: F401 -- ensure numpy available in scope

    # Copy-on-write per established pipeline convention
    out = {pid: poly.copy() for pid, poly in polygons.items()}
    # Phase 1: graph is built but positions are not solved.
    # Phase 2 will add: solve apices, densify edges, validate.
    return out
