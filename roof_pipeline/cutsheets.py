"""Multi-page PDF of dimensioned panel cut sheets via ReportLab + matplotlib."""

from __future__ import annotations

import logging
import math
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend so this works in API/server contexts
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .planes import Plane

log = logging.getLogger(__name__)

M_TO_FT = 3.280839895
SQM_TO_SQFT = 10.7639104


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def rotation_to_horizontal(normal: np.ndarray) -> np.ndarray:
    """Return R such that R @ normal = +z_hat.

    Uses Rodrigues' rotation formula. The axis is normal x z_hat, the angle
    is the angle between them. After applying R to every panel vertex, all
    z-components become equal (up to numerical noise) and the (x, y) pairs
    are the true-length 2D drawing of the panel -- because rotation is an
    isometry, every edge length and interior angle is preserved exactly.
    """
    n = normal / np.linalg.norm(normal)
    z_hat = np.array([0.0, 0.0, 1.0])
    cos_a = float(np.clip(n @ z_hat, -1.0, 1.0))

    if cos_a > 1.0 - 1e-9:
        return np.eye(3)
    if cos_a < -1.0 + 1e-9:
        # 180-degree flip about world x-axis
        return np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], dtype=float)

    axis = np.cross(n, z_hat)
    axis /= np.linalg.norm(axis)
    angle = math.acos(cos_a)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * (K @ K)


def polygon_area_2d(verts_xy: np.ndarray) -> float:
    """Shoelace area of a planar polygon (returns positive area)."""
    x = verts_xy[:, 0]
    y = verts_xy[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def slope_rise_over_12(normal: np.ndarray) -> int:
    """Roof pitch as 'rise per 12 horizontal' integer."""
    nx, ny, nz = normal
    horiz = math.hypot(nx, ny)
    if abs(nz) < 1e-9:
        return 99  # vertical wall, not a real roof panel
    ratio = horiz / abs(nz)
    return int(round(ratio * 12))


def azimuth_degrees(normal: np.ndarray) -> float:
    """Azimuth of the down-slope direction, 0 = north, clockwise.

    DSM convention: x = east, y = north. The horizontal projection of the
    *outward* normal points up-slope; flipping it gives the down-slope
    (water-shedding) direction shown on a roof plan.
    """
    nx, ny, _ = normal
    horiz = math.hypot(nx, ny)
    if horiz < 1e-9:
        return 0.0  # flat panel, azimuth undefined
    east = -nx / horiz
    north = -ny / horiz
    # atan2(east, north): rotates so north is 0, clockwise positive
    az = math.degrees(math.atan2(east, north))
    return (az + 360.0) % 360.0


def meters_to_ft_in(meters: float) -> str:
    """Format a length in meters as feet + inches rounded to nearest 1/4 inch."""
    total_in = meters * M_TO_FT * 12.0
    feet = int(total_in // 12)
    inches_remainder = total_in - feet * 12
    quarters = round(inches_remainder * 4)  # nearest quarter inch
    if quarters == 48:
        feet += 1
        quarters = 0
    whole_in = quarters // 4
    frac = quarters % 4
    frac_str = {0: "", 1: "1/4", 2: "1/2", 3: "3/4"}[frac]
    if frac_str:
        return f"{feet}' {whole_in} {frac_str}\""
    return f"{feet}' {whole_in}\""


def interior_angle_deg(prev_v: np.ndarray, vert: np.ndarray, next_v: np.ndarray) -> float:
    """Interior angle at ``vert`` formed by edges (prev->vert) and (vert->next)."""
    a = prev_v - vert
    b = next_v - vert
    cos_t = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    cos_t = max(-1.0, min(1.0, cos_t))
    return math.degrees(math.acos(cos_t))


# ---------------------------------------------------------------------------
# Image renderers (matplotlib -> PNG -> embedded in PDF)
# ---------------------------------------------------------------------------

# Edge type → 2-letter code shown next to the length on each cut sheet edge.
# Mirrors stores/labeler-store.ts EDGE_TYPE_META (website). Legacy keys
# (rake, hip_cap, wall) map to the canonical new code so old projects
# print consistently with new ones.
EDGE_TYPE_CODES: dict[str, str] = {
    "eave": "ED",
    "ridge": "RC",
    "hip": "HC",
    "hip_cap": "HC",
    "valley": "VF",
    "rake": "GR",
    "transition": "TF",
    "high_side": "HS",
    "flying_gable": "FG",
    "sidewall": "SW",
    "wall": "SW",  # legacy
    "endwall": "EW",
    "chimney_flashing": "CF",
    "unlabeled": "",
}


def _edge_code_for(t: str | None) -> str:
    if not t:
        return ""
    return EDGE_TYPE_CODES.get(str(t).lower(), "")


def _render_panel_drawing_png(
    verts_xy_ft: np.ndarray,
    out_path: Path,
    panel_id: int,
    edge_types: list[str] | None = None,
    page_down_xy: np.ndarray | None = None,
) -> None:
    """Top-down dimensioned drawing of one panel in true-length feet.

    ``edge_types`` is the labeler's per-edge classification (length must
    match ``verts_xy_ft``). When provided, the 2-letter code is prefixed
    to each edge length on the drawing so crews can identify ridges,
    eaves, hips, etc. at a glance. Falls back to length-only when omitted
    or mismatched length.

    ``page_down_xy`` is a 2D unit vector (in the rotated panel frame)
    pointing down-slope. When provided, the polygon is rotated in-plane
    so that direction maps to (0, -1) on the page — i.e. ridges land at
    the top of the page and eaves at the bottom, consistent across every
    per-panel page. Pure 2D rotation, still an isometry: every edge
    length and interior angle is preserved exactly. Pass None for flat
    panels (no defined down-slope) or to keep the legacy arbitrary
    orientation.
    """
    # Page-down alignment: rotate the planar polygon so the projected
    # down-slope points to (0, -1) on the page. Applied BEFORE the plot
    # so axes labels still read true-length feet.
    if page_down_xy is not None:
        d = np.asarray(page_down_xy, dtype=float)
        norm = float(np.linalg.norm(d))
        if norm > 1e-9:
            d /= norm
            cur_angle = math.atan2(d[1], d[0])
            target_angle = -math.pi / 2  # (0, -1)
            rot_angle = target_angle - cur_angle
            c, s = math.cos(rot_angle), math.sin(rot_angle)
            R2 = np.array([[c, -s], [s, c]])
            verts_xy_ft = verts_xy_ft @ R2.T

    fig, ax = plt.subplots(figsize=(7.5, 6.0), dpi=150)
    closed = np.vstack([verts_xy_ft, verts_xy_ft[:1]])
    ax.plot(closed[:, 0], closed[:, 1], "k-", linewidth=1.5)
    ax.fill(closed[:, 0], closed[:, 1], color="#cfe3ff", alpha=0.6)

    centroid = verts_xy_ft.mean(axis=0)
    n = verts_xy_ft.shape[0]
    use_codes = edge_types is not None and len(edge_types) == n
    for i in range(n):
        a = verts_xy_ft[i]
        b = verts_xy_ft[(i + 1) % n]
        mid = 0.5 * (a + b)
        edge = b - a
        length_m = float(np.linalg.norm(edge)) / M_TO_FT
        # Outward normal of the edge, used to push the label off the polygon
        out_dir = np.array([edge[1], -edge[0]])
        out_dir /= (np.linalg.norm(out_dir) + 1e-9)
        if np.dot(mid + out_dir - centroid, out_dir) < 0:
            out_dir = -out_dir
        label_pos = mid + out_dir * 0.6
        length_str = meters_to_ft_in(length_m)
        # "ED 12'-3"" when labeled, "12'-3"" when not — keeps unlabeled
        # legacy projects looking the same as before.
        code = _edge_code_for(edge_types[i]) if use_codes else ""
        label_str = f"{code} {length_str}" if code else length_str
        ax.annotate(
            label_str,
            xy=label_pos,
            ha="center", va="center",
            fontsize=9, color="#003366",
        )

        # Interior angle at vertex i
        prev_v = verts_xy_ft[(i - 1) % n]
        vert = verts_xy_ft[i]
        next_v = verts_xy_ft[(i + 1) % n]
        angle = interior_angle_deg(prev_v, vert, next_v)
        # Push the angle label slightly toward the centroid
        inward = centroid - vert
        inward /= (np.linalg.norm(inward) + 1e-9)
        ax.annotate(
            f"{angle:.1f}\u00b0",
            xy=vert + inward * 0.5,
            ha="center", va="center",
            fontsize=8, color="#660000",
        )

    ax.set_aspect("equal")
    ax.set_xlabel("feet (true length)")
    ax.set_ylabel("feet (true length)")
    ax.set_title(f"Panel #{panel_id} -- un-rotated to horizontal")
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _render_context_inset_png(
    full_mesh: trimesh.Trimesh,
    panel_id: int,
    panel_face_mask: np.ndarray,
    out_path: Path,
) -> None:
    """3D inset of the entire roof with one panel highlighted."""
    fig = plt.figure(figsize=(3.0, 2.5), dpi=150)
    ax = fig.add_subplot(111, projection="3d")

    verts = full_mesh.vertices
    faces = full_mesh.faces
    tri_verts = verts[faces]

    base = Poly3DCollection(
        tri_verts[~panel_face_mask],
        facecolor="#bbbbbb", edgecolor="#666666", linewidth=0.2,
    )
    hl = Poly3DCollection(
        tri_verts[panel_face_mask],
        facecolor="#ff5555", edgecolor="#660000", linewidth=0.3,
    )
    ax.add_collection3d(base)
    ax.add_collection3d(hl)

    mn = verts.min(axis=0)
    mx = verts.max(axis=0)
    ax.set_xlim(mn[0], mx[0])
    ax.set_ylim(mn[1], mx[1])
    ax.set_zlim(mn[2], mx[2])
    try:
        ax.set_box_aspect((mx - mn))
    except Exception:
        pass
    ax.set_axis_off()
    ax.view_init(elev=35, azim=-60)
    ax.set_title(f"Panel #{panel_id}", fontsize=8)
    fig.tight_layout(pad=0)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def _render_plan_view_png(
    full_mesh: trimesh.Trimesh,
    out_path: Path,
    polygons: dict[int, np.ndarray] | None = None,
) -> None:
    """Top-down orthographic plan view used on the cover page.

    Earlier versions iterated ``full_mesh.faces`` and drew each triangle
    with a stroke, which exposed every earcut interior diagonal as a
    visible slanted line — making clean panels look fragmented and
    off-axis. The fix: fill triangles WITHOUT edges so the colour is
    contiguous, then trace each panel's true boundary polygon on top
    from ``polygons`` (the original CCW vertex list, no triangulation).
    """
    fig, ax = plt.subplots(figsize=(7.0, 5.0), dpi=150)
    verts = full_mesh.vertices
    # Edgeless fills — no more triangulation diagonals leaking into the
    # final image. Slight alpha keeps overlapping panel fills readable
    # if any triangles happen to z-fight (rare but defensive).
    for tri in full_mesh.faces:
        poly = verts[tri]
        ax.fill(
            poly[:, 0] * M_TO_FT,
            poly[:, 1] * M_TO_FT,
            facecolor="#cfe3ff",
            edgecolor="none",
        )
    # Crisp panel boundaries on top. Closed polygon per panel; uses the
    # boundary verts that came out of polygonization, so the lines match
    # the eaves / hips / ridges users actually drew.
    if polygons:
        for verts_3d in polygons.values():
            if verts_3d.shape[0] < 2:
                continue
            closed = np.vstack([verts_3d, verts_3d[:1]])
            ax.plot(
                closed[:, 0] * M_TO_FT,
                closed[:, 1] * M_TO_FT,
                color="#003366",
                linewidth=0.9,
            )
    ax.set_aspect("equal")
    ax.set_xlabel("east (ft)")
    ax.set_ylabel("north (ft)")
    ax.set_title("Roof plan view")
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Per-panel face mask (which mesh faces belong to which panel)
# ---------------------------------------------------------------------------

def _panel_face_masks(
    polygons: dict[int, np.ndarray],
    full_mesh: trimesh.Trimesh,
) -> dict[int, np.ndarray]:
    """Build boolean face-masks per panel by counting vertices per panel.

    trimesh.util.concatenate preserves the per-submesh vertex ordering, so
    we can recover which face belongs to which panel by counting vertices
    in insertion order.
    """
    panel_ids = list(polygons.keys())
    vert_offsets: dict[int, tuple[int, int]] = {}
    cursor = 0
    for pid in panel_ids:
        n = polygons[pid].shape[0]
        vert_offsets[pid] = (cursor, cursor + n)
        cursor += n

    masks: dict[int, np.ndarray] = {}
    for pid in panel_ids:
        lo, hi = vert_offsets[pid]
        face_in_panel = np.all((full_mesh.faces >= lo) & (full_mesh.faces < hi), axis=1)
        masks[pid] = face_in_panel
    return masks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_cutsheets_pdf(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    full_mesh: trimesh.Trimesh,
    out_path: str | Path,
    edge_types_by_panel: dict[int, list[str]] | None = None,
) -> Path:
    """Write the multi-page cut-sheet PDF: cover + one page per panel.

    ``edge_types_by_panel`` is the labeler's per-edge classification keyed
    by panel id; when supplied (and the per-panel list length matches the
    polygon's vertex count), each edge label gets its 2-letter code
    prefix (e.g. "ED 12'-3\\""). Omitted / mismatched panels render
    length-only so legacy projects look unchanged.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
    )
    flowables = []

    panel_face_masks = _panel_face_masks(polygons, full_mesh)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # ---- Cover page ----
        plan_png = tmp_dir / "plan.png"
        _render_plan_view_png(full_mesh, plan_png, polygons=polygons)
        flowables.append(Paragraph("My Metal Roofer -- Panel Cut Sheets", styles["Title"]))
        flowables.append(Spacer(1, 0.2 * inch))
        flowables.append(Image(str(plan_png), width=6.5 * inch, height=4.6 * inch))
        flowables.append(Spacer(1, 0.2 * inch))

        # Panel index table
        table_rows = [["Panel ID", "Area (ft\u00b2)", "Slope", "Azimuth (\u00b0)"]]
        total_sqft = 0.0
        for pid, plane in planes.items():
            verts_3d = polygons[pid]
            R = rotation_to_horizontal(plane.normal)
            verts_rot = verts_3d @ R.T
            area_m2 = polygon_area_2d(verts_rot[:, :2])
            area_ft2 = area_m2 * SQM_TO_SQFT
            total_sqft += area_ft2
            table_rows.append([
                str(pid),
                f"{area_ft2:.1f}",
                f"{slope_rise_over_12(plane.normal)}/12",
                f"{azimuth_degrees(plane.normal):.0f}",
            ])
        table_rows.append(["TOTAL", f"{total_sqft:.1f}", "", ""])

        index_table = Table(table_rows, hAlign="LEFT")
        index_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003366")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dddddd")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]))
        flowables.append(index_table)
        flowables.append(PageBreak())

        # ---- One page per panel ----
        for pid in sorted(planes.keys()):
            plane = planes[pid]
            verts_3d = polygons[pid]
            R = rotation_to_horizontal(plane.normal)
            verts_rot = verts_3d @ R.T
            verts_xy_m = verts_rot[:, :2]
            verts_xy_ft = verts_xy_m * M_TO_FT
            area_m2 = polygon_area_2d(verts_xy_m)
            area_ft2 = area_m2 * SQM_TO_SQFT

            # Page-down direction: project the world-frame down-slope vector
            # ((-nx, -ny, 0) / horiz) into the rotated 2D panel frame so
            # the per-panel renderer can swing it to point at (0, -1) on
            # the page. None for flat panels \u2014 leaves legacy orientation.
            nx, ny, _ = plane.normal
            horiz = math.hypot(nx, ny)
            if horiz > 1e-9:
                ds_world = np.array([-nx / horiz, -ny / horiz, 0.0])
                ds_rot = R @ ds_world
                page_down_xy = ds_rot[:2]
            else:
                page_down_xy = None

            # Residual gives a quick read on plane-fit confidence \u2014 a
            # panel with high residual tends to also have visibly off
            # sheet runs, so surfacing it on the page header lets a
            # contractor cross-check at a glance. Centimetres because
            # roofs are measured in inches and meters reads as too
            # precise for the actual confidence interval.
            residual_cm = (
                getattr(plane, "rms_residual", None) or 0.0
            ) * 100.0
            residual_str = (
                f" &nbsp; | &nbsp; Plane fit: \u00b1{residual_cm:.1f} cm"
                if residual_cm > 0
                else ""
            )

            header = (
                f"<b>Panel #{pid}</b> &nbsp; | &nbsp; "
                f"Area: {area_ft2:.1f} ft\u00b2 &nbsp; | &nbsp; "
                f"Slope: {slope_rise_over_12(plane.normal)}/12 &nbsp; | &nbsp; "
                f"Azimuth: {azimuth_degrees(plane.normal):.0f}\u00b0"
                f"{residual_str}"
            )
            flowables.append(Paragraph(header, styles["Heading2"]))
            flowables.append(Spacer(1, 0.1 * inch))

            drawing_png = tmp_dir / f"panel_{pid}.png"
            edge_types = (
                edge_types_by_panel.get(pid) if edge_types_by_panel else None
            )
            _render_panel_drawing_png(
                verts_xy_ft, drawing_png, pid,
                edge_types=edge_types,
                page_down_xy=page_down_xy,
            )
            flowables.append(Image(str(drawing_png), width=6.5 * inch, height=5.2 * inch))

            inset_png = tmp_dir / f"inset_{pid}.png"
            _render_context_inset_png(
                full_mesh, pid, panel_face_masks[pid], inset_png,
            )
            flowables.append(Spacer(1, 0.1 * inch))
            flowables.append(Image(str(inset_png), width=2.5 * inch, height=2.0 * inch))

            if pid != max(planes.keys()):
                flowables.append(PageBreak())

        # Build with all temp PNGs still on disk; SimpleDocTemplate reads
        # them lazily during build(), so we can't drop the tempdir earlier.
        doc.build(flowables)

    log.info("wrote %s (%d panels)", out_path, len(planes))
    return out_path
