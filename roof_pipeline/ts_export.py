"""Emit cut-sheet data as JSON consumable by the TS PDF_Exporter.

Schema target: the TS class builds PDFs by walking a list of ``DrawType``s,
each containing ``Draw`` entries with a polyline of ``{x, z}`` points and
an optional centered text label. We mirror that structure 1:1 in JSON.

Coordinate mapping per panel:
  1. Un-rotate the 3D polygon so its plane normal points to +Z (Rodrigues).
  2. Take the 2D (u, v) coords in the rotated XY plane (inches).
  3. Center on the panel's centroid so each page draws around (0, 0)
     -- the TS transform `z*scale+300, -x*scale+400` then puts the
     drawing centered on the page.
  4. Emit our (u, v) as TS `{ x: -v_in, z: u_in }` so the panel reads
     right-side-up after the TS transform.

Page layout (matches TS ``Pages`` array order):
  page 0           cover -- full roof plan view + panel index list
  page 1..N        one per panel (in sorted ID order)
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import trimesh

from .cutsheets import (
    SQM_TO_SQFT,
    azimuth_degrees,
    interior_angle_deg,
    meters_to_ft_in,
    polygon_area_2d,
    rotation_to_horizontal,
    slope_rise_over_12,
)
from .planes import Plane

log = logging.getLogger(__name__)

M_TO_IN = 39.37007874


def _draw_type(
    type_name: str,
    order: int,
    layers: list[int],
    color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
    text_size: float = 8.0,
    text_height_offset: float = 0.0,
) -> dict:
    return {
        "type": type_name,
        "order": order,
        "layers": layers,
        "color": {"r": color[0], "g": color[1], "b": color[2], "a": color[3]},
        "text_size": text_size,
        "text_height_offset": text_height_offset,
        "draws": [],
    }


def _ts_pt(u_in: float, v_in: float) -> dict:
    """Map our local 2D (u, v) inches into TS {x, z} so the page reads
    right-side up after the TS `pageX = z*scale+300, pageY = -x*scale+400`
    transform: u → z (horizontal), v → -x (vertical, with page Y flipped)."""
    return {"x": -v_in, "z": u_in}


def _flatten_panel_to_inches(
    verts_3d: np.ndarray,
    plane: Plane,
) -> tuple[np.ndarray, float]:
    """Un-rotate panel to horizontal; return (N, 2) inches centered on origin
    and the panel area in square feet."""
    R = rotation_to_horizontal(plane.normal)
    rot = verts_3d @ R.T
    uv_m = rot[:, :2]
    area_ft2 = polygon_area_2d(uv_m) * SQM_TO_SQFT
    # Center each panel on its own centroid so the drawing sits at (0, 0)
    centroid = uv_m.mean(axis=0)
    uv_in = (uv_m - centroid) * M_TO_IN
    return uv_in, float(area_ft2)


def _plan_view_inches(
    polygons: dict[int, np.ndarray],
) -> dict[int, np.ndarray]:
    """Top-down inches view of every panel for the cover page.

    Use the raw 3D x/y (no un-rotation -- this is a plan, not a true-length
    drawing). Center the whole roof on (0, 0) so it fits the page.
    """
    all_xy = np.vstack([p[:, :2] for p in polygons.values()])
    centroid = all_xy.mean(axis=0)
    return {
        pid: (poly[:, :2] - centroid) * M_TO_IN
        for pid, poly in polygons.items()
    }


def write_ts_json(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    full_mesh: trimesh.Trimesh,
    out_path: str | Path,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    panel_ids = sorted(planes.keys())
    cover_page = 0
    panel_page_index = {pid: i + 1 for i, pid in enumerate(panel_ids)}
    total_pages = 1 + len(panel_ids)

    # Build DrawTypes. Order numbers control z-stacking (lower draws first).
    outline = _draw_type("panel_outline", order=10, layers=[],
                         color=(0.0, 0.0, 0.0, 1.0))
    edge_lbl = _draw_type("edge_label", order=20, layers=[],
                          color=(0.0, 0.2, 0.4, 1.0), text_size=6.0,
                          text_height_offset=4.0)
    angle_lbl = _draw_type("angle_label", order=30, layers=[],
                           color=(0.4, 0.0, 0.0, 1.0), text_size=5.0)
    header_lbl = _draw_type("panel_header", order=40, layers=[],
                            color=(0.0, 0.0, 0.0, 1.0), text_size=10.0)
    plan_outline = _draw_type("plan_outline", order=10, layers=[cover_page],
                              color=(0.0, 0.2, 0.4, 1.0))
    plan_label = _draw_type("plan_label", order=20, layers=[cover_page],
                            color=(0.0, 0.0, 0.0, 1.0), text_size=10.0)
    cover_title = _draw_type("cover_title", order=40, layers=[cover_page],
                             color=(0.0, 0.0, 0.0, 1.0), text_size=14.0)

    # ---- Cover page: top-down plan view + per-panel labels ----
    plan_xy = _plan_view_inches(polygons)
    cover_title["draws"].append({
        "sketch_id": "cover", "line_id": "title",
        "points": [_ts_pt(0.0, 360.0)],
        "text": "My Metal Roofer -- Panel Plan",
        "text_rotate": 0.0,
    })
    for pid in panel_ids:
        poly_in = plan_xy[pid]
        pts = [_ts_pt(float(u), float(v)) for u, v in poly_in]
        plan_outline["draws"].append({
            "sketch_id": f"panel_{pid}", "line_id": "plan_outline",
            "points": pts,
        })
        cx, cy = poly_in.mean(axis=0)
        plan_label["draws"].append({
            "sketch_id": f"panel_{pid}", "line_id": "plan_label",
            "points": [_ts_pt(float(cx), float(cy))],
            "text": str(pid), "text_rotate": 0.0,
        })

    # ---- Per-panel pages: outline, edge lengths, vertex angles, header ----
    page_meta = [{"page": cover_page, "type": "cover", "panel_id": None}]
    for pid in panel_ids:
        page = panel_page_index[pid]
        plane = planes[pid]
        verts_3d = polygons[pid]
        uv_in, area_ft2 = _flatten_panel_to_inches(verts_3d, plane)

        outline["layers"].append(page)
        edge_lbl["layers"].append(page)
        angle_lbl["layers"].append(page)
        header_lbl["layers"].append(page)

        # Outline (one Draw, all corners; the TS Draw closes the loop)
        outline["draws"].append({
            "sketch_id": f"panel_{pid}", "line_id": "outline",
            "points": [_ts_pt(float(u), float(v)) for u, v in uv_in],
        })

        # Edge length labels: one Draw per edge (2 pts + ft-in text)
        n = uv_in.shape[0]
        for i in range(n):
            a = uv_in[i]
            b = uv_in[(i + 1) % n]
            edge_in = np.linalg.norm(b - a)
            length_m = float(edge_in / M_TO_IN)
            angle_deg = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            edge_lbl["draws"].append({
                "sketch_id": f"panel_{pid}", "line_id": f"edge_{i}",
                "points": [
                    _ts_pt(float(a[0]), float(a[1])),
                    _ts_pt(float(b[0]), float(b[1])),
                ],
                "text": meters_to_ft_in(length_m),
                "text_rotate": angle_deg,
            })

        # Vertex angle labels: 1-point Draw places text exactly there
        centroid_uv = uv_in.mean(axis=0)
        for i in range(n):
            prev_v = uv_in[(i - 1) % n]
            vert = uv_in[i]
            next_v = uv_in[(i + 1) % n]
            angle = interior_angle_deg(prev_v, vert, next_v)
            inward = centroid_uv - vert
            inward = inward / (np.linalg.norm(inward) + 1e-9)
            anchor = vert + inward * 8.0  # 8" inside the corner
            angle_lbl["draws"].append({
                "sketch_id": f"panel_{pid}", "line_id": f"angle_{i}",
                "points": [_ts_pt(float(anchor[0]), float(anchor[1]))],
                "text": f"{angle:.1f}\u00b0",
                "text_rotate": 0.0,
            })

        # Header at the top of the page
        header_text = (
            f"Panel #{pid}  |  {area_ft2:.1f} ft^2  |  "
            f"{slope_rise_over_12(plane.normal)}/12  |  "
            f"{azimuth_degrees(plane.normal):.0f} deg"
        )
        header_lbl["draws"].append({
            "sketch_id": f"panel_{pid}", "line_id": "header",
            "points": [_ts_pt(0.0, 360.0)],
            "text": header_text,
            "text_rotate": 0.0,
        })

        page_meta.append({
            "page": page,
            "type": "panel",
            "panel_id": pid,
            "area_sqft": round(area_ft2, 2),
            "slope_rise_per_12": slope_rise_over_12(plane.normal),
            "azimuth_deg": round(azimuth_degrees(plane.normal), 1),
            "plane_residual_m": round(plane.rms_residual, 4),
            "vertex_count": int(n),
        })

    total_sqft = sum(
        _flatten_panel_to_inches(polygons[pid], planes[pid])[1]
        for pid in panel_ids
    )

    payload = {
        "schema_version": 1,
        "generator": "roof_pipeline.ts_export",
        "units": "inches",
        "page_size": [600, 800],
        "scale_hint": 0.5,
        "page_count": total_pages,
        "page_meta": page_meta,
        "totals": {
            "panel_count": len(panel_ids),
            "total_slope_sqft": round(total_sqft, 1),
            "footprint_min_m": full_mesh.bounds[0].tolist(),
            "footprint_max_m": full_mesh.bounds[1].tolist(),
        },
        # Conceptually equivalent to the TS DataDrawings.DrawTypes array.
        # The TS side iterates these in `Order` ascending, then per layer.
        "draw_types": [
            outline,
            edge_lbl,
            angle_lbl,
            header_lbl,
            plan_outline,
            plan_label,
            cover_title,
        ],
    }

    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    log.info("wrote TS exporter JSON: %s (%d pages, %d panels, %.0f ft^2 total)",
             out_path, total_pages, len(panel_ids), total_sqft)
    return out_path
