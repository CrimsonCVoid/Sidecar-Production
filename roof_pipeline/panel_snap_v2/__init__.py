"""panel_snap_v2 -- topology-aware snap engine subpackage.

Replaces the pairwise edge snap in snapping.py with a union-find clustering +
feature graph approach that handles 3+ panels meeting at hip/ridge apices.

Public API: snap_polygons() -- Phase 2 will wire this to run_real.py via
--snap-v2. Phase 1 exposes --snap-v2-dryrun (print graph, exit 0).
"""

from __future__ import annotations
