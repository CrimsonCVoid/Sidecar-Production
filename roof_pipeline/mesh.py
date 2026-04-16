"""Triangulate per-panel polygons in their plane's local 2D frame, export mesh."""

from __future__ import annotations

import logging
from pathlib import Path

import mapbox_earcut as earcut
import numpy as np
import trimesh

from .planes import Plane

log = logging.getLogger(__name__)


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two orthonormal in-plane vectors (u, v) given a unit normal.

    Pick an arbitrary world axis least aligned with the normal, project it
    into the plane to get u, then v = n x u. This avoids the degenerate case
    where the seed vector is parallel to the normal.
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


def _triangulate_polygon(verts_3d: np.ndarray, plane: Plane) -> np.ndarray:
    """Earcut triangulation in the plane's local 2D frame.

    earcut returns flat triangle indices into the original vertex array,
    so we can reuse the 3D coords directly without lifting back ourselves.
    """
    u, v = _plane_basis(plane.normal)
    centered = verts_3d - plane.centroid
    uv = np.stack([centered @ u, centered @ v], axis=1).astype(np.float64)

    # mapbox_earcut v2 API: pass (N, 2) float64 + uint32 ring-length array
    rings = np.array([uv.shape[0]], dtype=np.uint32)
    tris = earcut.triangulate_float64(uv, rings)
    if tris.size == 0:
        raise RuntimeError(f"earcut returned no triangles for polygon shape {uv.shape}")
    return tris.reshape(-1, 3)


def build_roof_mesh(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
) -> trimesh.Trimesh:
    """Build one trimesh from all panel polygons, tagged with panel IDs."""
    sub_meshes = []
    for pid, verts in polygons.items():
        plane = planes[pid]
        faces = _triangulate_polygon(verts, plane)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        # Stash the panel ID per-face for downstream use (e.g. coloring)
        mesh.metadata["panel_id"] = pid
        sub_meshes.append(mesh)
        log.info("panel %d: %d triangles", pid, faces.shape[0])

    if not sub_meshes:
        raise RuntimeError("no panels to mesh")

    combined = trimesh.util.concatenate(sub_meshes)
    log.info(
        "combined mesh: %d vertices, %d faces",
        combined.vertices.shape[0], combined.faces.shape[0],
    )
    return combined


def export_mesh(mesh: trimesh.Trimesh, out_dir: str | Path) -> dict[str, Path]:
    """Write OBJ and glTF; return the output paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    obj_path = out / "roof.obj"
    gltf_path = out / "roof.gltf"
    mesh.export(obj_path)
    mesh.export(gltf_path)
    log.info("wrote %s and %s", obj_path, gltf_path)
    return {"obj": obj_path, "gltf": gltf_path}
