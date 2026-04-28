"""DSM-aware polygon straighten: POST /api/pipeline/straighten/{sample_id}.

Deliberately narrow scope. The algorithm ONLY sharpens angles — it never
combines / welds corner dots. The job is exactly two steps:

    1. Fit a plane per panel from the DSM interior and derive that panel's
       eave axis in pixel space (perpendicular to the plane's down-slope
       vector).

    2. For each edge, decide whether to snap it:
       * ``eave`` / ``ridge`` / ``hip_cap`` edges that sit within ~32° of
         the eave axis are rotated to be exactly parallel to it.
       * Every other edge is snapped to the nearest eave_axis ± k·45°
         (k ∈ {0,1,2,3}) only when it's already within ~14° of that
         multiple. Catches rakes (90°), perfect 45° hips / valleys, and
         the occasional diagonal the user drew "close enough". Edges that
         aren't near any 45° multiple are left alone on purpose.

We do NOT try to weld hip/valley edges to the two-plane intersection line,
force-orthogonalize unlabeled edges, re-orient rake edges relative to the
plane, or combine near-identical corners across panels. Every one of
those was too aggressive in earlier iterations. Corner identity is the
user's job (via the labeler's vertex magnet at draw time).
"""

from __future__ import annotations

import logging
import math
from io import BytesIO

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from supabase import Client

from ..planes import Plane, fit_plane
from .config import Settings
from .deps import (
    Principal,
    get_settings,
    get_supabase,
    require_principal,
    verify_sample_access,
)

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PanelIn(BaseModel):
    id: int
    corners_pix: list[list[float]]
    edge_types: list[str] | None = None


class StraightenIn(BaseModel):
    panels: list[PanelIn]


class PanelOut(BaseModel):
    id: int
    corners_pix: list[list[float]]
    edge_types: list[str] | None = None


class StraightenOut(BaseModel):
    panels: list[PanelOut]


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

MIN_INTERIOR_PIXELS = 8
EDGE_BLEED_ERODE_PX = 2

# Tolerance for snapping eave / ridge edges to the plane's eave axis.
# Wider than the 45° tolerance because we really want these flat — the
# whole point of the Straighten button is to clean up the water-shedding
# lines a metal roof is laid against.
EAVE_RIDGE_SNAP_DEG = 32.0

# Tolerance for snapping every other edge to the nearest eave_axis + k·45°.
# Intentionally tighter: edges that are obviously not near a 45° multiple
# should be left alone, not dragged into an axis they don't belong on.
ORTHO_45_SNAP_DEG = 14.0

# Relaxation: every corner is shared by two edges. Each relaxation pass
# re-averages target positions across the edges that own each corner.
RELAX_PASSES = 6
RELAX_BLEND = 0.55  # 1 = snap fully to target, 0 = keep current

# Edges considered "primary water-shedding lines" — these always target
# the panel's eave axis directly. Everything else goes through the 45°
# snap path. ``hip_cap`` is included because a capped hip visually reads
# as a ridge line and users expect the same treatment.
EAVE_AXIS_TYPES = {"eave", "ridge", "hip_cap"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plane_pixel_axes(plane: Plane) -> tuple[np.ndarray, np.ndarray]:
    """Return (down_slope_pix, eave_pix) — unit 2D vectors in pixel space.

    World convention: row increases going south (positive row → negative
    world y). So a world-XY direction (dx, dy) becomes pixel (dx, -dy).
    """
    nx, ny, _nz = plane.normal
    horiz = float(math.hypot(nx, ny))
    if horiz < 1e-9:
        # Perfectly flat panel — no meaningful down-slope. Fall back to
        # page axes so snapping does something reasonable.
        return np.array([1.0, 0.0]), np.array([0.0, 1.0])
    # Down-slope points in the direction the panel drops (world +normal XY
    # components are up-slope, so -normal is down-slope). We only need a
    # line direction, sign is arbitrary, but picking a consistent sign
    # avoids flipping on each pass.
    down_world = np.array([nx, ny]) / horiz
    down_pix = np.array([down_world[0], -down_world[1]])
    down_pix = down_pix / (np.linalg.norm(down_pix) or 1.0)
    eave_pix = np.array([-down_pix[1], down_pix[0]])
    return down_pix, eave_pix


def _align_direction_sign(target: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Flip ``target`` so it points the same way as ``current`` (avoids
    rotating an edge by 180° when snapping)."""
    if float(np.dot(target, current)) < 0:
        return -target
    return target


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def _fit_planes_per_panel(
    panels: list[dict],
    dsm: np.ndarray,
    res_m: float,
) -> dict[int, Plane | None]:
    """Fit a plane through the DSM-sampled interior of each panel polygon."""
    from scipy.ndimage import binary_erosion
    from skimage.draw import polygon as draw_polygon

    h, w = dsm.shape
    valid_dsm = ~np.isnan(dsm)
    out: dict[int, Plane | None] = {}

    for p in panels:
        pid = p["id"]
        corners = p.get("corners_pix") or []
        if len(corners) < 3:
            out[pid] = None
            continue

        cols_px = np.array([float(c[0]) for c in corners])
        rows_px = np.array([float(c[1]) for c in corners])
        rr, cc = draw_polygon(rows_px, cols_px, shape=(h, w))
        if rr.size == 0:
            out[pid] = None
            continue

        mask = np.zeros((h, w), dtype=bool)
        mask[rr, cc] = True
        mask &= valid_dsm

        eroded = binary_erosion(mask, iterations=EDGE_BLEED_ERODE_PX)
        sample_mask = eroded if eroded.sum() >= MIN_INTERIOR_PIXELS else mask
        if sample_mask.sum() < MIN_INTERIOR_PIXELS:
            out[pid] = None
            continue

        rr_s, cc_s = np.nonzero(sample_mask)
        fit_source = np.column_stack([
            cc_s.astype(np.float64) * res_m,
            -rr_s.astype(np.float64) * res_m,  # +y = north
            dsm[rr_s, cc_s],
        ])

        try:
            out[pid] = fit_plane(fit_source)
        except Exception as exc:
            log.warning("straighten: plane fit failed for panel %d: %s", pid, exc)
            out[pid] = None

    return out


def _rotate_axis(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """Rotate a 2D unit vector by ``angle_rad``."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([c * axis[0] - s * axis[1], s * axis[0] + c * axis[1]])


def _signed_angle_to_axis(vec: np.ndarray, axis: np.ndarray) -> float:
    """Angle of ``vec`` relative to ``axis``, folded to [-π/2, π/2).

    Result is positive when ``vec`` is CCW from ``axis``. Used to decide
    which 45° multiple an edge is closest to.
    """
    vx, vy = vec / (np.linalg.norm(vec) or 1.0)
    ax, ay = axis / (np.linalg.norm(axis) or 1.0)
    cross = vx * ay - vy * ax
    dot = vx * ax + vy * ay
    theta = math.atan2(-cross, dot)  # flip sign so CCW-of-axis is positive
    # Fold to [-π/2, π/2) — direction is a line, orientation doesn't matter.
    if theta >= math.pi / 2:
        theta -= math.pi
    elif theta < -math.pi / 2:
        theta += math.pi
    return theta


def _target_direction_for_edge(
    a: np.ndarray,
    b: np.ndarray,
    edge_type: str,
    eave_axis: np.ndarray | None,
) -> np.ndarray | None:
    """Resolve a target pixel-space direction for one edge.

    Two snap paths:

      * ``edge_type`` ∈ EAVE_AXIS_TYPES (``eave`` / ``ridge`` / ``hip_cap``):
        target the eave axis directly. Uses the wider EAVE_RIDGE_SNAP_DEG
        tolerance because we really want these flat.

      * Anything else: target the nearest ``eave_axis ± k·45°``
        (k ∈ {0,1,2,3}), only when the current edge is within the tighter
        ORTHO_45_SNAP_DEG tolerance of that multiple. Otherwise leave the
        edge alone.

    Returns None when the edge should be left alone (no plane fit, edge
    too short, or current angle too far from any snap target).
    """
    if eave_axis is None:
        return None
    cur = b - a
    cur_norm = float(np.linalg.norm(cur))
    if cur_norm < 1e-9:
        return None

    theta = _signed_angle_to_axis(cur, eave_axis)
    theta_deg = math.degrees(theta)
    etype = (edge_type or "").lower()

    if etype in EAVE_AXIS_TYPES:
        if abs(theta_deg) <= EAVE_RIDGE_SNAP_DEG:
            return _align_direction_sign(eave_axis, cur)
        return None

    # Nearest 45° multiple in [-90°, 90°] (5 candidates: -90, -45, 0, 45, 90,
    # but -90 and 90 are the same line, so effectively four distinct axes).
    step_deg = 45.0
    k = round(theta_deg / step_deg)
    target_deg = k * step_deg
    if abs(theta_deg - target_deg) <= ORTHO_45_SNAP_DEG:
        target_dir = _rotate_axis(eave_axis, math.radians(target_deg))
        return _align_direction_sign(target_dir, cur)
    return None


def _relax_panel_corners(
    panels: list[dict],
    axes_by_idx: list[tuple[np.ndarray, np.ndarray] | None],
) -> list[list[list[float]]]:
    """Iteratively snap edges toward their target directions and blend
    corner positions across the edges that share each corner.

    Returns the updated ``corners_pix`` for every panel (shape-preserving).
    """
    corners_by_idx: list[np.ndarray] = [
        np.array(p.get("corners_pix", []), dtype=np.float64).reshape(-1, 2)
        for p in panels
    ]

    for _ in range(RELAX_PASSES):
        # Accumulate target positions per corner, keyed by (panel_idx,
        # corner_idx). Each edge contributes targets to its two endpoints.
        sums: dict[tuple[int, int], np.ndarray] = {}
        weights: dict[tuple[int, int], float] = {}

        for pi, p in enumerate(panels):
            verts = corners_by_idx[pi]
            n = verts.shape[0]
            if n < 3:
                continue
            axes = axes_by_idx[pi]
            eave_axis = axes[1] if axes is not None else None
            types = p.get("edge_types") or [""] * n

            for ei in range(n):
                a = verts[ei]
                b = verts[(ei + 1) % n]
                etype = types[ei] if ei < len(types) else ""
                target = _target_direction_for_edge(a, b, etype, eave_axis)
                if target is None:
                    continue
                cur = b - a
                cur_len = float(np.linalg.norm(cur))
                if cur_len < 1e-9:
                    continue

                mid = (a + b) / 2.0
                new_a = mid - (cur_len / 2.0) * target
                new_b = mid + (cur_len / 2.0) * target

                key_a = (pi, ei)
                key_b = (pi, (ei + 1) % n)
                sums[key_a] = sums.get(key_a, np.zeros(2)) + new_a
                weights[key_a] = weights.get(key_a, 0.0) + 1.0
                sums[key_b] = sums.get(key_b, np.zeros(2)) + new_b
                weights[key_b] = weights.get(key_b, 0.0) + 1.0

        if not sums:
            break

        # Blend each corner toward its accumulated target.
        for pi, verts in enumerate(corners_by_idx):
            n = verts.shape[0]
            for ci in range(n):
                w = weights.get((pi, ci), 0.0)
                if w <= 0.0:
                    continue
                target_pos = sums[(pi, ci)] / w
                verts[ci] = (
                    (1.0 - RELAX_BLEND) * verts[ci] + RELAX_BLEND * target_pos
                )

    return [verts.tolist() for verts in corners_by_idx]


# ---------------------------------------------------------------------------
# FastAPI endpoint
# ---------------------------------------------------------------------------


@router.post("/straighten/{sample_id}", response_model=StraightenOut)
async def straighten_endpoint(
    sample_id: str,
    body: StraightenIn,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
) -> StraightenOut:
    """Straighten polygons by sharpening edge angles only.

    Workflow:
      1. Plane fit per panel from the eroded DSM interior.
      2. Per-panel eave axis (perpendicular to the plane's down-slope).
      3. For each edge: if labeled ``eave``/``ridge``/``hip_cap``, target
         the eave axis; otherwise target the nearest ``eave_axis + k·45°``
         if within tolerance, else leave alone.
      4. Iterative relaxation: corner positions are a weighted average
         across the edges that target them. Edges that wouldn't snap
         contribute nothing.

    Corners are never welded across panels — only per-edge angles are
    sharpened. Users position shared corners via the labeler's vertex
    magnet; we don't override that.
    """
    verify_sample_access(principal, sample_id, supabase)
    request.state.sample_id = sample_id

    panels_in = [p.model_dump() for p in body.panels]
    if not panels_in:
        raise HTTPException(status_code=400, detail="No panels to straighten")

    # --- 1. Load DSM from storage ----------------------------------------
    sample_row = (
        supabase.table("training_samples")
        .select("dsm_storage_path, meters_per_px")
        .eq("id", sample_id)
        .execute()
    )
    if not sample_row.data:
        raise HTTPException(status_code=404, detail="Sample not found")
    sample = sample_row.data[0]
    dsm_path = sample.get("dsm_storage_path")
    if not dsm_path:
        raise HTTPException(status_code=400, detail="Sample has no DSM")

    dsm_bytes: bytes | None = None
    for bucket in (settings.training_bucket, settings.storage_bucket):
        try:
            dsm_bytes = supabase.storage.from_(bucket).download(dsm_path)
            break
        except Exception:
            continue
    if dsm_bytes is None:
        raise HTTPException(status_code=404, detail="Could not download DSM")

    import rasterio

    with rasterio.open(BytesIO(dsm_bytes)) as ds:
        dsm = ds.read(1).astype(np.float64)
        res_m = abs(ds.res[0]) if ds.res else float(sample.get("meters_per_px") or 0.25)

    # --- 2. Per-panel plane fit + eave axis ------------------------------
    planes_by_id = _fit_planes_per_panel(panels_in, dsm, res_m)
    axes_by_idx: list[tuple[np.ndarray, np.ndarray] | None] = [
        _plane_pixel_axes(pl) if (pl := planes_by_id.get(p["id"])) is not None else None
        for p in panels_in
    ]

    # --- 3. Iterative edge alignment -------------------------------------
    # Straighten only SHARPENS ANGLES — it no longer welds close corners
    # across panels. The user controls corner identity via the labeler's
    # vertex-magnet at draw time; an automatic weld here would silently
    # yank points the user had positioned deliberately.
    snapped_corners = _relax_panel_corners(panels_in, axes_by_idx)

    # --- 4. Assemble response -------------------------------------------
    out_panels: list[PanelOut] = []
    for p_in, new_corners in zip(panels_in, snapped_corners):
        out_panels.append(
            PanelOut(
                id=p_in["id"],
                corners_pix=new_corners,
                edge_types=p_in.get("edge_types"),
            )
        )
    return StraightenOut(panels=out_panels)
