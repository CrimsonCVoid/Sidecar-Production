"""Tiered golden-file smoke test for gable roof identity (TEST-01, D-09).

Verifies that snap_v2 on the synthetic 2-panel gable produces deterministic
output across runs. Three tiers of comparison:

  Tier 0 (pre-flight): Snapped polygon arrays at atol=1e-12
  Tier 1 (strict byte): snap_v2_features.json deterministic byte match
  Tier 2 (structural): OBJ/glTF mesh vertices at atol=1e-9, exact face match

Tier 3 (semantic PDF via pdfplumber) is deferred to Milestone 2.

Golden files stored in tests/golden/gable/ per D-10. Regenerate with
``pytest --regenerate-golden`` per D-11.

Cross-checks compare v1 and v2 structurally: same panel IDs, same vertex
count, and matching XY positions. Z values differ by design (D-02: v2 uses
per-plane Z reconstruction while v1 averages Z at shared edges). Vertex
ordering differs due to CCW winding normalization in v2.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from roof_pipeline.boundaries import extract_panel_polygons
from roof_pipeline.mesh import build_roof_mesh
from roof_pipeline.planes import fit_all_panels
from roof_pipeline.snapping import snap_shared_edges
from roof_pipeline.synthetic import make_synthetic_gable
from roof_pipeline.panel_snap_v2 import snap_polygons

GOLDEN_DIR = Path(__file__).parent / "golden" / "gable"


@pytest.fixture(scope="module")
def gable_pipeline():
    """Run both v1 and v2 snap on synthetic gable, return results."""
    roof = make_synthetic_gable()
    planes = fit_all_panels(roof.dsm, roof.mask, roof.res_m)
    polygons = extract_panel_polygons(roof.mask, roof.dsm, roof.res_m, planes)

    # V1 path (reference)
    v1_polygons = snap_shared_edges(polygons, tol=0.15)
    v1_mesh = build_roof_mesh(v1_polygons, planes)

    # V2 path (under test)
    v2_polygons, v2_graph = snap_polygons(polygons, planes, tol=0.15)
    v2_mesh = build_roof_mesh(v2_polygons, planes)

    return {
        "v1_polygons": v1_polygons,
        "v2_polygons": v2_polygons,
        "v2_graph": v2_graph,
        "v1_mesh": v1_mesh,
        "v2_mesh": v2_mesh,
        "planes": planes,
    }


class TestGableSmokeIdentity:
    """D-09: Tiered golden-file comparison for gable roof.

    TEST-01: test_gable_two_panels_unchanged -- deterministic output from v2.
    """

    def test_tier0_polygon_allclose(self, request, gable_pipeline):
        """Tier 0 (pre-flight): Snapped polygon dict at atol=1e-12."""
        v2 = gable_pipeline["v2_polygons"]
        golden_path = GOLDEN_DIR / "polygons.npz"

        if request.config.getoption("--regenerate-golden"):
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            np.savez(golden_path, **{str(k): v for k, v in v2.items()})
            pytest.skip("regenerated golden: polygons.npz")

        assert golden_path.exists(), (
            f"Golden file missing: {golden_path}. Run with --regenerate-golden"
        )
        golden = np.load(golden_path)
        for pid_str in golden.files:
            pid = int(pid_str)
            assert pid in v2, f"Panel {pid} in golden but not in v2 output"
            np.testing.assert_allclose(
                v2[pid], golden[pid_str], atol=1e-12,
                err_msg=f"Tier 0 FAILED: panel {pid} polygon arrays differ",
            )

    def test_tier0_v1_v2_structural_match(self, gable_pipeline):
        """Tier 0 cross-check: v1 and v2 produce structurally equivalent output.

        Checks same panel IDs, same vertex count per panel, and matching XY
        positions (within tolerance). Z values differ by design (D-02: per-plane
        Z reconstruction in v2 vs averaged Z in v1). Vertex ordering differs
        due to CCW winding normalization.
        """
        v1 = gable_pipeline["v1_polygons"]
        v2 = gable_pipeline["v2_polygons"]
        assert set(v1.keys()) == set(v2.keys()), (
            "Panel ID mismatch between v1 and v2"
        )
        for pid in sorted(v1.keys()):
            assert v1[pid].shape == v2[pid].shape, (
                f"Panel {pid} shape mismatch: v1={v1[pid].shape}, "
                f"v2={v2[pid].shape}"
            )
            # XY positions should match after accounting for vertex reordering.
            # Sort both by XY coordinates and compare.
            v1_xy = v1[pid][:, :2]
            v2_xy = v2[pid][:, :2]
            v1_sorted = v1_xy[np.lexsort(v1_xy.T)]
            v2_sorted = v2_xy[np.lexsort(v2_xy.T)]
            np.testing.assert_allclose(
                v1_sorted, v2_sorted, atol=1e-6,
                err_msg=f"Panel {pid}: v1 vs v2 XY positions differ",
            )

    def test_tier1_json_byte_identity(self, request, gable_pipeline):
        """Tier 1 (strict byte): snap_v2_features.json deterministic."""
        graph = gable_pipeline["v2_graph"]
        actual_bytes = json.dumps(graph, indent=2, sort_keys=True).encode()
        golden_path = GOLDEN_DIR / "features.json"

        if request.config.getoption("--regenerate-golden"):
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            golden_path.write_bytes(actual_bytes)
            pytest.skip("regenerated golden: features.json")

        assert golden_path.exists(), f"Golden file missing: {golden_path}"
        golden_bytes = golden_path.read_bytes()
        assert actual_bytes == golden_bytes, (
            f"Tier 1 FAILED: features.json differs. "
            f"Actual size={len(actual_bytes)}, golden size={len(golden_bytes)}"
        )

    def test_tier2_mesh_structural(self, request, gable_pipeline):
        """Tier 2 (structural): mesh vertices at atol=1e-9, exact face match."""
        v2_mesh = gable_pipeline["v2_mesh"]
        golden_verts_path = GOLDEN_DIR / "mesh_vertices.npy"
        golden_faces_path = GOLDEN_DIR / "mesh_faces.npy"

        if request.config.getoption("--regenerate-golden"):
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            np.save(golden_verts_path, v2_mesh.vertices)
            np.save(golden_faces_path, v2_mesh.faces)
            pytest.skip("regenerated golden: mesh_vertices.npy, mesh_faces.npy")

        assert golden_verts_path.exists(), (
            f"Golden file missing: {golden_verts_path}"
        )
        golden_verts = np.load(golden_verts_path)
        golden_faces = np.load(golden_faces_path)

        np.testing.assert_allclose(
            v2_mesh.vertices, golden_verts, atol=1e-9, rtol=1e-9,
            err_msg="Tier 2 FAILED: mesh vertices differ",
        )
        np.testing.assert_array_equal(
            v2_mesh.faces, golden_faces,
            err_msg="Tier 2 FAILED: mesh faces differ",
        )

    def test_tier2_v1_v2_mesh_structural_match(self, gable_pipeline):
        """Tier 2 cross-check: v1 and v2 meshes are structurally equivalent.

        Same vertex count, same face count. Vertex positions compared after
        sorting by XY to handle reordering from winding normalization.
        """
        v1_mesh = gable_pipeline["v1_mesh"]
        v2_mesh = gable_pipeline["v2_mesh"]

        assert v1_mesh.vertices.shape == v2_mesh.vertices.shape, (
            f"Mesh vertex shape mismatch: v1={v1_mesh.vertices.shape}, "
            f"v2={v2_mesh.vertices.shape}"
        )
        assert v1_mesh.faces.shape == v2_mesh.faces.shape, (
            f"Mesh face shape mismatch: v1={v1_mesh.faces.shape}, "
            f"v2={v2_mesh.faces.shape}"
        )

        # XY positions should match after sorting
        v1_xy = v1_mesh.vertices[:, :2]
        v2_xy = v2_mesh.vertices[:, :2]
        v1_sorted = v1_xy[np.lexsort(v1_xy.T)]
        v2_sorted = v2_xy[np.lexsort(v2_xy.T)]
        np.testing.assert_allclose(
            v1_sorted, v2_sorted, atol=1e-6,
            err_msg="Mesh XY positions differ between v1 and v2",
        )
