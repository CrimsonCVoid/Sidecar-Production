"""Regression test for densify on 12-panel hip-and-valley roof (FIX-01, FIX-02).

Uses inline constants from fb7e705c sample: 12 panels' 3D polygon vertices
and 12 fitted Plane objects. Extracted one-time from
/Users/carterbrady/Downloads/fb7e705c.mask.json + fit_all_panels run.
Per D-10: no binary blobs, no external file paths at runtime.

The root cause: densify_edges() used `source_poly = out[source_pid]` which
reads from the mutated `out` dict. Panels participating in 2+ graph edges
accumulated spurious inserted vertices via a mutation chain, causing panel 8
to self-intersect with 65.9% area loss on the real DSM data.

Fix: use a pre-densify snapshot for source lookups so mutations in `out`
don't contaminate later edge iterations.
"""

from __future__ import annotations

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.densify import densify_edges
from roof_pipeline.panel_snap_v2.graph import build_feature_graph
from roof_pipeline.panel_snap_v2.winding import normalize_winding


# ---------------------------------------------------------------------------
# Inline constants from fb7e705c (12-panel hip-and-valley roof)
# Extracted one-time from mask.json + synthetic tilted planes (D-12)
# ---------------------------------------------------------------------------

def _build_fb7e705c_polygons() -> dict[int, np.ndarray]:
    """Return 12-panel polygon dict with inline vertex arrays."""
    return {
        1: np.array([[43.490422, 52.321439, 5.604297], [44.531216, 37.771563, 3.830258], [50.372407, 38.472506, 4.380555], [49.522779, 49.114094, 5.671088], [47.632357, 49.050372, 5.513803]]),
        2: np.array([[49.798908, 49.177816, 5.908150], [50.691017, 38.642432, 4.433686], [56.128635, 38.939801, 4.110287], [56.234839, 42.147146, 4.533922], [51.285757, 45.885509, 5.366658], [54.599305, 49.623871, 5.647297]]),
        3: np.array([[51.434442, 45.885509, 5.487785], [56.277320, 42.210868, 4.598113], [56.914541, 42.741886, 4.597388], [57.020744, 44.228734, 4.757618], [55.682581, 45.991712, 5.089178], [51.795533, 46.034194, 5.469918]]),
        4: np.array([[51.646849, 46.097916, 5.301696], [55.300248, 46.034194, 4.811633], [56.234839, 47.372357, 4.780406], [55.937469, 49.538908, 4.970514], [54.705509, 49.560149, 5.135751]]),
        5: np.array([[54.132010, 52.682531, 5.383878], [56.744615, 50.983275, 5.067332], [58.974888, 51.131960, 4.737692], [58.019057, 52.894938, 4.811098]]),
        6: np.array([[54.153251, 52.597568, 5.376319], [58.146501, 53.128586, 4.814728], [58.550074, 54.657916, 4.649865], [54.790471, 54.424268, 5.159088]]),
        7: np.array([[49.883871, 55.571266, 5.062882], [50.117519, 50.006203, 5.562075], [50.011315, 49.793797, 5.594530], [55.215285, 50.154888, 4.954543], [55.215285, 51.535533, 4.823950], [54.132010, 52.066551, 4.899833], [54.493102, 54.530471, 4.624736], [54.429380, 56.166005, 4.477451]]),
        8: np.array([[44.255087, 55.146452, 4.425506], [44.276328, 52.618809, 4.666510], [47.993449, 49.730074, 5.372516], [49.607742, 49.836278, 5.550715], [49.395335, 55.571266, 4.984753]]),
        9: np.array([[40.006948, 49.730074, 4.791288], [40.155633, 47.775931, 4.768488], [43.065608, 47.733449, 5.198872], [42.980645, 50.133648, 5.241353]]),
        10: np.array([[40.091911, 47.563524, 4.872648], [40.622928, 44.929677, 4.772997], [43.129330, 44.908437, 5.110343], [43.044367, 47.138710, 5.244012]]),
        11: np.array([[44.127643, 58.247593, 4.727332], [44.170124, 55.571266, 5.074244], [47.674839, 56.166005, 5.269713], [47.462432, 58.693648, 4.928711]]),
        12: np.array([[47.950968, 56.357171, 5.147068], [49.501538, 56.781985, 5.128514], [49.650223, 58.991017, 4.807367], [48.120893, 58.927295, 4.773339], [48.163375, 56.420893, 5.143712]]),
    }


def _build_fb7e705c_planes() -> dict[int, Plane]:
    """Return 12 fitted Plane objects with inline constants."""
    return {
        1: Plane(normal=np.array([-0.078028026692, -0.126160679397, 0.988936352868]), centroid=np.array([47.109836, 45.345995, 5.000000]), rms_residual=0.01, d=-4.452087336206),
        2: Plane(normal=np.array([0.066079417417, -0.132809640348, 0.988936352868]), centroid=np.array([53.123077, 44.069429, 5.000000]), rms_residual=0.01, d=2.602178685724),
        3: Plane(normal=np.array([0.095627737813, -0.113402935307, 0.988936352868]), centroid=np.array([54.854194, 44.515484, 5.000000]), rms_residual=0.01, d=5.142077665367),
        4: Plane(normal=np.array([0.131455884332, -0.068733110290, 0.988936352868]), centroid=np.array([54.764983, 47.720705, 5.000000]), rms_residual=0.01, d=8.863868526130),
        5: Plane(normal=np.array([0.143718088193, 0.036742361135, 0.988936352868]), centroid=np.array([56.967643, 51.923176, 5.000000]), rms_residual=0.01, d=15.039742549577),
        6: Plane(normal=np.array([0.129444920020, 0.072449310945, 0.988936352868]), centroid=np.array([56.410074, 53.702084, 5.000000]), rms_residual=0.01, d=16.137358347530),
        7: Plane(normal=np.array([0.115129102303, 0.093542395621, 0.988936352868]), centroid=np.array([52.937221, 52.478089, 5.000000]), rms_residual=0.01, d=15.948222672019),
        8: Plane(normal=np.array([-0.115306689026, 0.093323402432, 0.988936352868]), centroid=np.array([47.105588, 52.580576, 5.000000]), rms_residual=0.01, d=4.420090591658),
        9: Plane(normal=np.array([-0.146594510956, -0.022692274747, 0.988936352868]), centroid=np.array([41.552208, 48.843275, 5.000000]), rms_residual=0.01, d=-2.255008936254),
        10: Plane(normal=np.array([-0.133650319667, -0.064362116407, 0.988936352868]), centroid=np.array([41.722134, 46.135087, 5.000000]), rms_residual=0.01, d=-3.600846611507),
        11: Plane(normal=np.array([-0.076702496082, 0.126970930021, 0.988936352868]), centroid=np.array([45.858759, 57.169628, 5.000000]), rms_residual=0.01, d=8.686081268045),
        12: Plane(normal=np.array([-0.028073156901, 0.145659836047, 0.988936352868]), centroid=np.array([48.677400, 57.495672, 5.000000]), rms_residual=0.01, d=11.952963713989),
    }


class TestFb7e705cRegression:
    """FIX-01/FIX-02: 12-panel hip-and-valley roof densify regression."""

    def test_fb7e705c_panel8_densify_no_area_rejection(self):
        """Panel 8 passes through densify without spurious vertex growth.

        Panel 8 shares edges with 2+ neighbors (panels 1 and 7). Before
        the fix, densify caused mutation-chain vertex accumulation that
        created a self-intersecting polygon with 65.9% area loss.
        """
        polygons = _build_fb7e705c_polygons()
        planes = _build_fb7e705c_planes()

        graph = build_feature_graph(polygons, planes, tol=1.0)

        pre_count = len(polygons[8])

        # Must NOT raise RuntimeError
        result = densify_edges(polygons, planes, graph, tol=1.0)

        # Panel 8 must exist in the output
        assert 8 in result, "Panel 8 missing from densify output"

        # Panel 8 should not accumulate spurious vertices from mutation chain
        post_count = len(result[8])
        growth = post_count - pre_count
        assert growth <= 2, (
            f"Panel 8 vertex growth {growth} (from {pre_count} to "
            f"{post_count}) suggests mutation-chain contamination"
        )

    def test_fb7e705c_all_panels_survive_densify(self):
        """All 12 panels pass through densify_edges without error."""
        polygons = _build_fb7e705c_polygons()
        planes = _build_fb7e705c_planes()

        graph = build_feature_graph(polygons, planes, tol=1.0)
        result = densify_edges(polygons, planes, graph, tol=1.0)

        for pid in polygons:
            assert pid in result, f"Panel {pid} missing from densify output"

    def test_fb7e705c_multi_neighbor_no_mutation_chain(self):
        """Panels with 2+ graph edges don't accumulate spurious vertices.

        The mutation-chain bug caused panels participating in multiple
        graph edges to grow unboundedly as vertices inserted from one
        edge became source candidates for the next edge.
        """
        polygons = _build_fb7e705c_polygons()
        planes = _build_fb7e705c_planes()

        graph = build_feature_graph(polygons, planes, tol=1.0)

        # Find all panels that participate in 2+ graph edges
        edge_counts: dict[int, int] = {}
        for edge in graph.get("edges", []):
            for pid in (edge["panel_a"], edge["panel_b"]):
                edge_counts[pid] = edge_counts.get(pid, 0) + 1
        multi_panels = [pid for pid, count in edge_counts.items() if count >= 2]

        pre_counts = {pid: len(polygons[pid]) for pid in multi_panels}
        result = densify_edges(polygons, planes, graph, tol=1.0)

        for pid in multi_panels:
            growth = len(result[pid]) - pre_counts[pid]
            assert growth <= 3, (
                f"Panel {pid} (in {edge_counts[pid]} edges) grew by "
                f"{growth} vertices -- possible mutation-chain leak"
            )
