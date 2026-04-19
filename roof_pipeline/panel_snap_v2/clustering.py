"""Three-pass expanding-tolerance vertex clustering via union-find.

Groups polygon vertices that are topologically the same point (hip apices,
ridge convergences) even when pairwise distances exceed the base tolerance.
The three-pass expansion (0.3t, 0.6t, t) catches transitive chains that a
single-pass approach would miss.

This is the core data structure that the feature graph (graph.py) is built
from. The function does NOT write centroids back to polygons -- that is the
solver's job in Phase 2.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.cluster.hierarchy import DisjointSet

from ..planes import Plane

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PASS_FRACTIONS = (0.3, 0.6, 1.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cluster_vertices(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    tol: float = 1.0,
) -> tuple[dict[int, list[int]], list[tuple[int, int, np.ndarray]]]:
    """Cluster polygon vertices using three-pass expanding tolerance.

    Each pass uses a fraction of the base tolerance (0.3t, 0.6t, t).
    Passes are cumulative: each pass adds unions on top of the previous
    pass state, so transitive chains across passes are handled correctly.
    Uses scipy.cluster.hierarchy.DisjointSet for union-find.

    Validates tol > 0 at function entry (T-01-05: tol comes from CLI argparse
    but negative values are nonsensical and produce no merges silently).

    Args:
        polygons: Panel ID to (K, 3) ordered boundary vertices.
        planes: Panel ID to fitted Plane dataclass (accepted but not used in
            Phase 1 -- reserved for Phase 2 weighted clustering).
        tol: Base snap tolerance in metres. Passes use 0.3*tol, 0.6*tol, tol.

    Returns:
        (groups, items) where:
        - groups: dict mapping root index -> list of member indices into items.
          Includes singleton groups (size 1) so graph.py can count valence for
          all vertices, not just merged ones.
        - items: list of (panel_id, vertex_index, xyz_array) tuples, one entry
          per vertex across all panels. Iteration order is sorted by panel ID
          for determinism.
    """
    if tol <= 0:
        raise ValueError(f"tol must be positive, got {tol!r}")

    # ------------------------------------------------------------------
    # 1. Flatten all vertices into a list for indexed access.
    #    Sort by panel ID for determinism (dict iteration order is insertion
    #    order in Python 3.7+ but panels may have been inserted in any order).
    # ------------------------------------------------------------------
    items: list[tuple[int, int, np.ndarray]] = []
    for pid in sorted(polygons.keys()):
        poly = polygons[pid]
        for vi in range(len(poly)):
            items.append((pid, int(vi), poly[vi]))

    n = len(items)
    if n == 0:
        log.info("cluster_vertices: no vertices to cluster (tol=%.3f m)", tol)
        return {}, items

    # ------------------------------------------------------------------
    # 2. Create DisjointSet over all vertex indices.
    # ------------------------------------------------------------------
    ds: DisjointSet[int] = DisjointSet(range(n))

    # ------------------------------------------------------------------
    # 3. Three-pass expanding-tolerance merge.
    #    Each pass is cumulative -- unions from pass 1 are preserved in pass 2.
    # ------------------------------------------------------------------
    for fraction in _PASS_FRACTIONS:
        pass_tol = tol * fraction
        tol2 = pass_tol * pass_tol
        log.info(
            "clustering pass %.1ft (tol=%.3f m): %d items",
            fraction,
            pass_tol,
            n,
        )
        for i in range(n):
            xi = items[i][2]
            for j in range(i + 1, n):
                xj = items[j][2]
                d = xi - xj
                if float(d @ d) <= tol2:
                    ds.merge(i, j)

    # ------------------------------------------------------------------
    # 4. Build groups dict: root index -> list of member indices.
    #    Include singletons so graph.py gets every vertex's cluster.
    # ------------------------------------------------------------------
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = ds[i]
        if root not in groups:
            groups[root] = []
        groups[root].append(i)

    log.info(
        "clustered %d vertices into %d groups (tol=%.3f m)",
        n,
        len(groups),
        tol,
    )
    return groups, items
