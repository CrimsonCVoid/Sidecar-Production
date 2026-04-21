"""Snap preview endpoint: POST /snap-preview (API-01)."""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request

from ..panel_snap_v2 import snap_polygons
from ..panel_snap_v2.schema import PanelsInput
from ..planes import Plane
from .deps import Principal, require_principal
from .schemas import SnapPreviewResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _planes_from_clicks(panels_input: PanelsInput) -> tuple[dict[int, np.ndarray], dict[int, Plane]]:
    """Build polygon arrays and flat-plane approximations from click data.

    For snap-preview, we don't need real DSM elevations -- the topology
    (which vertices cluster, which panels share edges) is determined by
    XY positions. We construct flat planes at z=0 and use pixel coordinates
    scaled by res_m (defaulting to 1.0 if not provided).

    This avoids requiring DSM file access for the preview endpoint.
    """
    res_m = panels_input.res_m or 1.0
    polygons: dict[int, np.ndarray] = {}
    planes: dict[int, Plane] = {}

    for panel in panels_input.panels:
        corners = np.array(panel.corners_pix, dtype=np.float64)
        # Convert pixel coords to meters: x = col * res_m, y = row * res_m, z = 0
        xs = corners[:, 0] * res_m
        ys = corners[:, 1] * res_m
        zs = np.zeros(len(corners))
        verts_3d = np.stack([xs, ys, zs], axis=1)

        polygons[panel.id] = verts_3d

        # Flat plane at z=0
        normal = np.array([0.0, 0.0, 1.0])
        centroid = verts_3d.mean(axis=0)
        planes[panel.id] = Plane(
            normal=normal,
            centroid=centroid,
            rms_residual=0.0,
            d=float(normal @ centroid),
        )

    return polygons, planes


@router.post("/preview", response_model=SnapPreviewResponse)
async def snap_preview(
    body: PanelsInput,
    request: Request,
    principal: Principal = Depends(require_principal),
):
    """Snap polygons and return feature graph + snapped coordinates (API-01).

    Accepts PanelsInput (mask.json format), builds flat-plane approximations,
    runs snap_polygons, returns the feature graph and snapped polygon arrays.
    Target: <500ms for 12-panel roof.
    """
    # Stateless compute on caller-supplied polygons — no sample_id, no DB
    # touches. Still auth-gated so random callers can't pin the CPU: the
    # snap engine is O(P^2 E^2) and a large body can burn real cycles.
    del principal  # used only for its side effect of requiring auth

    # Set sample_id on request state for structured logging
    request.state.sample_id = f"preview-{len(body.panels)}panels"

    if not body.panels:
        raise HTTPException(status_code=422, detail="No panels provided")

    try:
        polygons, planes = _planes_from_clicks(body)

        # Run snap engine in thread to avoid blocking event loop (D-12)
        snap_tol = body.res_m or 1.0
        snapped, feature_graph = await asyncio.to_thread(
            snap_polygons, polygons, planes, tol=snap_tol,
        )

        # Serialize polygons: dict[int, ndarray] -> dict[str, list[list[float]]]
        snapped_serialized = {
            str(pid): poly.tolist()
            for pid, poly in snapped.items()
        }

        return SnapPreviewResponse(
            feature_graph=feature_graph,
            snapped_polygons=snapped_serialized,
        )

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
