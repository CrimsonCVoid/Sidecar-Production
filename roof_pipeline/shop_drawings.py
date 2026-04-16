"""Industry-standard metal roofing shop drawings (4-page PDF, ReportLab).

Consumes a ``roof`` dict produced upstream by the DSM pipeline and emits a
fabricator-facing PDF with:

    page 1  Panel Layout Plan          (ANSI B portrait)
    page 2  Edge / Trim Diagram        (Letter portrait)
    page 3  Sheet Cut List             (ANSI B landscape)
    page 4  Combined Edge Detail       (ANSI B landscape)

Public API: ``generate_shop_drawings(roof, output_path, trim_formulas=None)``.
"""

from __future__ import annotations

import datetime
import logging
import math
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as pdfcanvas

from .cutsheets import SQM_TO_SQFT, polygon_area_2d, rotation_to_horizontal
from .planes import Plane

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANSI_B_PORTRAIT = (792.0, 1224.0)        # 11" x 17" at 72 dpi
ANSI_B_LANDSCAPE = (1224.0, 792.0)
LETTER = letter                          # (612, 792)

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

EDGE_CODE: dict[str, str] = {
    "EAVE": "ED", "RIDGE": "RC", "HIP": "HC", "VALLEY": "VF",
    "GABLE": "GR", "TRANSITION": "TF", "HIGH_SIDE": "HS",
    "FLYING_GABLE": "FG", "SIDEWALL": "SW", "ENDWALL": "EW",
    "CHIMNEY_FLASHING": "CF",
}

# Display order in the trim-takeoff block (skips zero-LF rows at render time)
TRIM_TAKEOFF_ORDER: list[tuple[str, str]] = [
    ("EAVE", "ED"), ("VALLEY", "VF"), ("TRANSITION", "TF"),
    ("HIP", "HC"), ("RIDGE", "RC"), ("GABLE", "GR"),
    ("SIDEWALL", "SW"), ("ENDWALL", "EW"),
    ("CHIMNEY_FLASHING", "CF"), ("HIGH_SIDE", "HS"),
    ("FLYING_GABLE", "FG"),
]

DISCLAIMER = (
    "ALWAYS FIELD VERIFY ALL DIMENSIONS. We do our best, however, we will "
    "likely not be 100% to-the-inch precise. Estimating with imagery & drawings "
    "of varying quality is an imperfect science. As such, no warranty, expressed "
    "or implied, is made regarding accuracy, adequacy, or reliability of this layout."
)

# Distinct panel fill colors (semi-transparent at draw time so overlaps
# read as blends). 12 colors -- enough for any realistic roof.
PANEL_PALETTE: list[str] = [
    "#5B9BD5", "#ED7D31", "#70AD47", "#FFC000",
    "#9E480E", "#636363", "#264478", "#997300",
    "#A5A5A5", "#43682B", "#7030A0", "#C00000",
]


def _meta(roof: dict) -> dict:
    """Title-block + material fields with sensible defaults.

    Missing material/finish/gauge keys get placeholders rather than blanks
    so the installer sees a clearly-marked "TBD" if the upstream form
    didn't collect them yet.
    """
    today = datetime.date.today().strftime("%-m/%-d/%y")
    return {
        "estimate_number": roof.get("estimate_number", ""),
        "project_name":    roof.get("project_name", "PROJECT NAME"),
        "project_address": roof.get("project_address", "PROJECT ADDRESS"),
        "revision":        str(roof.get("revision", "0")),
        "date":            roof.get("date", today),
        "drawn_by":        roof.get("drawn_by", "AUTO"),
        "checked_by":      roof.get("checked_by", "--"),
        "fabricator_name": roof.get("fabricator_name", "INTEGRITY METALS"),
        "gauge":           roof.get("gauge", "24 GA"),
        "material":        roof.get("material", "GALVALUME"),
        "finish_color":    roof.get("finish_color", "MILL FINISH"),
    }


DEFAULT_TRIM_FORMULAS: dict[str, Callable[[dict[str, float]], float]] = {
    "EAVE CLEAT":    lambda t: t.get("ED", 0.0),
    "GABLE CLEAT":   lambda t: t.get("GR", 0.0),
    "PANEL STARTER": lambda t: t.get("ED", 0.0),
    "Z-FLASHING":    lambda t: t.get("RC", 0.0) + t.get("HC", 0.0) + t.get("VF", 0.0),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def feet_to_ft_in(decimal_ft: float) -> str:
    """Format decimal feet as feet-inches (e.g. 17.833 -> "17'-10\"").

    Rounds to the nearest inch. Carries 12 -> +1 ft when rounding pushes
    inches to a full foot (so 17.96 -> "18'" not "17'-12\"").
    """
    if decimal_ft is None or not math.isfinite(decimal_ft):
        return "?"
    sign = "-" if decimal_ft < 0 else ""
    decimal_ft = abs(decimal_ft)
    feet = int(decimal_ft)
    inches = int(round((decimal_ft - feet) * 12.0))
    if inches == 12:
        feet += 1
        inches = 0
    if inches == 0:
        return f"{sign}{feet}'"
    return f"{sign}{feet}'-{inches}\""


def fit_to_box(
    points_xy: np.ndarray,
    box_w: float,
    box_h: float,
    margin: float = 0.05,
) -> tuple[float, np.ndarray]:
    """Uniform scale + translation so ``points_xy`` fits centered in (box_w, box_h).

    Returns ``(scale, offset)`` where ``page_pt = scale * world_pt + offset``.
    Margin is a fraction of the box per side.
    """
    if points_xy.shape[0] == 0:
        return 1.0, np.array([box_w / 2.0, box_h / 2.0])
    mn = points_xy.min(axis=0)
    mx = points_xy.max(axis=0)
    span = np.maximum(mx - mn, 1e-9)
    avail_w = box_w * (1.0 - 2 * margin)
    avail_h = box_h * (1.0 - 2 * margin)
    scale = float(min(avail_w / span[0], avail_h / span[1]))
    centroid_world = (mn + mx) / 2.0
    offset = np.array([box_w / 2.0, box_h / 2.0]) - scale * centroid_world
    return scale, offset


def _world_to_page(p: np.ndarray, scale: float, offset: np.ndarray) -> np.ndarray:
    return scale * p + offset


def text_angle_for_edge(p1: np.ndarray, p2: np.ndarray) -> float:
    """Edge angle in degrees, flipped 180 if the natural angle would be upside-down."""
    angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
    if angle > 90.0:
        angle -= 180.0
    elif angle < -90.0:
        angle += 180.0
    return angle


def _outward_normal(p1: np.ndarray, p2: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    """Unit normal of edge p1->p2 pointing AWAY from the polygon centroid."""
    edge = p2 - p1
    n = np.array([edge[1], -edge[0]], dtype=float)
    n /= (np.linalg.norm(n) + 1e-9)
    mid = 0.5 * (p1 + p2)
    if float(np.dot(mid + n - centroid, n)) < 0:
        n = -n
    return n


def _clip_polygon_halfplane(
    poly: np.ndarray, normal: np.ndarray, offset: float,
) -> np.ndarray:
    """Sutherland-Hodgman clip: keep points where ``p . normal >= offset``.

    `poly` is (N, 2). Returns the clipped polygon, possibly empty.
    Used by the scan-line panel layout to compute each panel's actual
    plan-view shape (a strip of the panel polygon).
    """
    if poly.shape[0] == 0:
        return poly
    out: list[np.ndarray] = []
    n = poly.shape[0]
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        a_in = float(a @ normal) >= offset
        b_in = float(b @ normal) >= offset
        if a_in:
            out.append(a)
        if a_in != b_in:
            denom = float((b - a) @ normal)
            if abs(denom) > 1e-12:
                t = (offset - float(a @ normal)) / denom
                out.append(a + t * (b - a))
    return np.array(out) if out else np.zeros((0, 2))


def _clip_polygon_to_strip(
    poly: np.ndarray, perp_axis: np.ndarray, perp_lo: float, perp_hi: float,
) -> np.ndarray:
    """Clip ``poly`` to the strip ``perp_lo <= p . perp_axis <= perp_hi``."""
    poly = _clip_polygon_halfplane(poly, perp_axis, perp_lo)
    poly = _clip_polygon_halfplane(poly, -perp_axis, -perp_hi)
    return poly


def _panel_outline_2d(panel: dict) -> np.ndarray:
    """Un-rotate ``boundary_3d`` to horizontal and return the (N, 2) true-length polygon.

    Uses ``rotation_to_horizontal(plane_normal)`` from cutsheets.py so the
    rotated polygon's z-component is constant and (x, y) is true-length.
    Falls back to the raw XY projection if plane_normal is missing.
    """
    boundary = np.asarray(panel.get("boundary_3d", []), dtype=float)
    if boundary.size == 0:
        return np.zeros((0, 2))
    if boundary.shape[1] == 2:
        return boundary.copy()
    normal = panel.get("plane_normal")
    if normal is None:
        log.warning("panel %s missing plane_normal; using XY projection",
                    panel.get("panel_id", "?"))
        return boundary[:, :2]
    R = rotation_to_horizontal(np.asarray(normal, dtype=float))
    rot = boundary @ R.T
    return rot[:, :2]


def sum_edges_by_type(roof: dict) -> dict[str, float]:
    """LF totals per edge type CODE, summed across every panel."""
    totals: dict[str, float] = {}
    for panel in roof.get("roof_panels", []):
        for edge in panel.get("edges", []):
            code = EDGE_CODE.get(edge.get("type", ""), edge.get("type", "??"))
            totals[code] = totals.get(code, 0.0) + float(edge.get("length_ft", 0.0))
    return totals


def _slope_numerator(slope: str) -> int | None:
    """'4/12' -> 4. Returns None on unparseable input."""
    try:
        return int(str(slope).split("/")[0])
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _draw_polygon(c: pdfcanvas.Canvas, pts: np.ndarray, line_width: float = 2.0,
                  stroke=colors.black, fill=None) -> None:
    if pts.shape[0] < 2:
        return
    path = c.beginPath()
    path.moveTo(float(pts[0, 0]), float(pts[0, 1]))
    for x, y in pts[1:]:
        path.lineTo(float(x), float(y))
    path.close()
    c.setStrokeColor(stroke)
    c.setLineWidth(line_width)
    if fill is not None:
        c.setFillColor(fill)
        c.drawPath(path, stroke=1, fill=1)
    else:
        c.drawPath(path, stroke=1, fill=0)


def _draw_centered_text(
    c: pdfcanvas.Canvas, text: str, x: float, y: float,
    rotate: float = 0.0, size: float = 8.0, font: str = FONT,
    color=colors.black,
) -> None:
    if not text:
        return
    c.saveState()
    c.translate(x, y)
    c.rotate(rotate)
    width = pdfmetrics.stringWidth(text, font, size)
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawString(-width / 2.0, -size / 3.0, text)
    c.restoreState()


def _draw_text_box(
    c: pdfcanvas.Canvas, x: float, y: float, w: float, h: float,
    title: str, rows: list[tuple[str, str]],
    title_size: float = 9.0, row_size: float = 8.0,
) -> None:
    """Boxed key-value list with a title bar at the top."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.75)
    c.rect(x, y, w, h, stroke=1, fill=0)
    # Title bar
    c.setFillColor(colors.HexColor("#222222"))
    c.rect(x, y + h - title_size - 6, w, title_size + 6, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, title_size)
    c.drawString(x + 4, y + h - title_size - 2, title)
    # Rows
    c.setFillColor(colors.black)
    c.setFont(FONT, row_size)
    line_h = row_size + 3
    cur_y = y + h - title_size - 6 - line_h
    for label, value in rows:
        if cur_y < y + 4:
            break
        c.setFont(FONT, row_size)
        c.drawString(x + 4, cur_y, label)
        c.setFont(FONT_BOLD, row_size)
        c.drawRightString(x + w - 4, cur_y, value)
        cur_y -= line_h


# ---------------------------------------------------------------------------
# Page 1: Panel Layout Plan (ANSI B portrait)
# ---------------------------------------------------------------------------

def _render_page1(
    c: pdfcanvas.Canvas, roof: dict,
    page_num: int = 1, total_pages: int = 4,
) -> None:
    page_w, page_h = ANSI_B_PORTRAIT
    c.setPageSize((page_w, page_h))

    panels = roof.get("roof_panels", [])
    if not panels:
        log.warning("page1: no panels to plot")
        return

    meta = _meta(roof)

    # Header band: title left, page right -- single thin rule below
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.line(40, page_h - 60, page_w - 40, page_h - 60)
    c.setFont(FONT_BOLD, 18)
    c.drawString(40, page_h - 44, "PANEL LAYOUT PLAN")
    c.setFont(FONT, 9)
    c.drawString(40, page_h - 56, meta["fabricator_name"])
    c.setFont(FONT, 9)
    c.drawRightString(page_w - 40, page_h - 44,
                      f"Estimate {meta['estimate_number']}")
    c.drawRightString(page_w - 40, page_h - 56,
                      f"REV {meta['revision']}  |  {meta['date']}  |  "
                      f"DRAWN: {meta['drawn_by']}  |  Page {page_num} of {total_pages}")

    coverage_ft = float(roof.get("coverage_width_in", 24.0)) / 12.0

    # Drawing area: full width, between header and title block. The legend
    # may overlap if the roof footprint is huge -- legend is drawn last so
    # it always wins visually, but we don't carve out space for it because
    # the typical roof footprint sits in the middle of the page.
    draw_x0, draw_y0 = 50.0, 220.0
    draw_w = page_w - 100.0
    draw_h = page_h - 80 - draw_y0  # header at top, title block below draw_y0

    # Compute global plan-view bounds across ALL panels so the layout is
    # to-scale across the whole roof (one shared scale + offset).
    all_xy = np.vstack([
        np.asarray(s["boundary_3d"], dtype=float)[:, :2]
        for s in panels if len(s.get("boundary_3d", []))
    ])
    scale, offset = fit_to_box(all_xy, draw_w, draw_h, margin=0.06)
    offset = offset + np.array([draw_x0, draw_y0])

    # Pre-compute panel polygons (clipped to panel shapes) so we can draw
    # all panel fills first, then all outlines on top -- avoids panel
    # rectangles visually escaping the panel polygon.
    panel_color: list[colors.Color] = []
    panel_outline_world: list[np.ndarray] = []
    panel_run_axis: list[np.ndarray] = []  # 2D run direction per panel (world == page)
    panel_sheet_polys: list[list[np.ndarray]] = []  # per-panel list of clipped polys (world XY)
    panel_sheet_lengths: list[list[float]] = []
    for idx, panel in enumerate(panels):
        boundary = np.asarray(panel.get("boundary_3d", []), dtype=float)
        if boundary.shape[0] < 3:
            panel_color.append(colors.black)
            panel_outline_world.append(np.zeros((0, 2)))
            panel_run_axis.append(np.array([1.0, 0.0]))
            panel_sheet_polys.append([])
            panel_sheet_lengths.append([])
            continue
        outline = boundary[:, :2]
        panel_color.append(colors.HexColor(PANEL_PALETTE[idx % len(PANEL_PALETTE)]))
        panel_outline_world.append(outline)

        plane_normal = np.asarray(panel.get("plane_normal", [0, 0, 1]), dtype=float)
        nx, ny = float(plane_normal[0]), float(plane_normal[1])
        horiz = math.hypot(nx, ny)
        run_dir = (np.array([-nx, -ny]) / horiz) if horiz > 1e-9 else np.array([1.0, 0.0])
        panel_run_axis.append(run_dir)

        polys, lengths = _scan_line_sheets(outline, plane_normal, coverage_ft)
        panel_sheet_polys.append(polys)
        panel_sheet_lengths.append(lengths)

    # Pass 1: panel fills + clipped panels (semi-transparent)
    sheet_running_id = 0
    for idx in range(len(panels)):
        color = panel_color[idx]
        run_dir_world = panel_run_axis[idx]
        # Run direction vector in PAGE space = same direction as world (our
        # page transform is uniform scale + translation, no flips).
        run_axis_pg = run_dir_world  # unit vector, direction only
        for poly_world, length_ft in zip(panel_sheet_polys[idx], panel_sheet_lengths[idx]):
            sheet_running_id += 1
            poly_pg = np.array([_world_to_page(p, scale, offset) for p in poly_world])
            if poly_pg.shape[0] < 3:
                continue
            c.saveState()
            c.setFillColor(color)
            c.setFillAlpha(0.35)
            c.setStrokeAlpha(1.0)
            _draw_polygon(c, poly_pg, line_width=0.5,
                          stroke=colors.HexColor("#222222"), fill=color)
            c.restoreState()

            _draw_sheet_length_label(c, poly_pg, length_ft,
                                     sheet_id=sheet_running_id,
                                     run_axis_pg=run_axis_pg)

    # Pass 2: panel outlines on top, in the panel color (thicker)
    for idx in range(len(panels)):
        outline = panel_outline_world[idx]
        if outline.shape[0] < 3:
            continue
        outline_pg = np.array([_world_to_page(p, scale, offset) for p in outline])
        _draw_polygon(c, outline_pg, line_width=2.0, stroke=panel_color[idx])

        # Section ID badge: white fill, colored border, DARK text so it's
        # readable on every color in the palette (S4 yellow-on-white was
        # invisible in v2).
        cx, cy = outline_pg.mean(axis=0)
        sid = panels[idx].get("panel_id", str(idx + 1))
        c.saveState()
        c.setFillColor(colors.white)
        c.setStrokeColor(panel_color[idx])
        c.setLineWidth(1.2)
        c.circle(float(cx), float(cy), 11, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#222222"))
        c.setFont(FONT_BOLD, 9)
        c.drawCentredString(float(cx), float(cy) - 3.0, sid.replace("panel_", "P"))
        c.restoreState()

    # ---- Boxed panels legend in the upper-right corner of the drawing area
    # (drawn after the panels/outlines so it always wins visually)
    legend_w = 260.0
    n_sec = len(panels)
    legend_h = 28.0 + n_sec * 16.0 + 20.0  # +20 for the TOTAL row
    legend_x = draw_x0 + draw_w - legend_w
    legend_y = draw_y0 + draw_h - legend_h
    c.saveState()
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.6)
    c.rect(legend_x, legend_y, legend_w, legend_h, stroke=1, fill=1)
    c.setFillColor(colors.HexColor("#222222"))
    c.rect(legend_x, legend_y + legend_h - 18, legend_w, 18, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 10)
    c.drawString(legend_x + 8, legend_y + legend_h - 13, "PANELS")
    c.setFillColor(colors.black)
    c.setFont(FONT, 9)
    grand_sheets = 0
    grand_lf = 0.0
    for idx, panel in enumerate(panels):
        color = colors.HexColor(PANEL_PALETTE[idx % len(PANEL_PALETTE)])
        ly = legend_y + legend_h - 18 - 14 - idx * 16
        c.setFillColor(color)
        c.rect(legend_x + 8, ly, 18, 11, stroke=0, fill=1)
        c.setFillColor(colors.black)
        n_sheets = len(panel.get("sheets", []))
        total_lf = sum(float(sh.get("length_ft", 0.0)) for sh in panel.get("sheets", []))
        grand_sheets += n_sheets
        grand_lf += total_lf
        c.drawString(legend_x + 32, ly + 1,
                     f"{panel.get('panel_id', '?')}   "
                     f"{n_sheets} sheets   {feet_to_ft_in(total_lf)}")
    # Grand-total row (highlighted) -- the fabricator wants "total pieces" at a glance
    total_y = legend_y + 8
    c.setFillColor(colors.HexColor("#f2f2f2"))
    c.rect(legend_x, total_y - 2, legend_w, 18, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont(FONT_BOLD, 9)
    c.drawString(legend_x + 8, total_y + 3,
                 f"TOTAL   {grand_sheets} sheets   {feet_to_ft_in(grand_lf)}")
    c.restoreState()

    # ---- North arrow in the upper-left corner of the drawing area
    _draw_north_arrow(c, draw_x0 + 40, draw_y0 + draw_h - 50, size=64)

    # ---- Title block in the lower-right corner of the page
    tb_w = 320.0
    tb_h = 130.0
    tb_x = page_w - 40 - tb_w
    tb_y = 70.0
    c.saveState()
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.9)
    c.rect(tb_x, tb_y, tb_w, tb_h, stroke=1, fill=0)
    # Title rows (project name, address)
    c.setFont(FONT_BOLD, 13)
    c.drawString(tb_x + 8, tb_y + tb_h - 20, meta["project_name"])
    c.setFont(FONT, 9)
    c.drawString(tb_x + 8, tb_y + tb_h - 34, meta["project_address"])
    # Divider above the data grid
    c.line(tb_x, tb_y + tb_h - 44, tb_x + tb_w, tb_y + tb_h - 44)
    # 4-cell data grid: REV | DATE | DRAWN | SHEET
    cell_w = tb_w / 4.0
    grid_top = tb_y + tb_h - 44
    grid_bot = tb_y + 28
    for i in range(1, 4):
        c.line(tb_x + i * cell_w, grid_top, tb_x + i * cell_w, grid_bot)
    c.line(tb_x, grid_bot, tb_x + tb_w, grid_bot)
    labels = ["REV", "DATE", "DRAWN BY", "SHEET"]
    values = [meta["revision"], meta["date"], meta["drawn_by"], "1 OF 4"]
    for i, (lab, val) in enumerate(zip(labels, values)):
        cx = tb_x + i * cell_w + cell_w / 2.0
        c.setFont(FONT, 7)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawCentredString(cx, grid_top - 11, lab)
        c.setFillColor(colors.black)
        c.setFont(FONT_BOLD, 11)
        c.drawCentredString(cx, grid_bot + 6, val)
    # Bottom row: fabricator + estimate number
    c.setFont(FONT_BOLD, 9)
    c.drawString(tb_x + 8, tb_y + 12, meta["fabricator_name"])
    c.setFont(FONT, 9)
    c.drawRightString(tb_x + tb_w - 8, tb_y + 12, f"Estimate {meta['estimate_number']}")
    # Optional CHECKED BY tucked below the divider on the right
    if meta["checked_by"] and meta["checked_by"] != "--":
        c.setFont(FONT, 7)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawRightString(tb_x + tb_w - 8, grid_bot - 12,
                          f"CHECKED BY: {meta['checked_by']}")
        c.setFillColor(colors.black)
    c.restoreState()

    # Footer
    c.setStrokeColor(colors.grey)
    c.setLineWidth(0.5)
    c.line(40, 60, page_w - 40, 60)
    c.setFont(FONT, 7)
    c.setFillColor(colors.grey)
    c.drawString(40, 48, "MRQ -- Material Requisition Quote (sample)")
    c.drawRightString(page_w - 40, 48, f"Page {page_num} of {total_pages}")
    c.setFillColor(colors.black)


def _scan_line_sheets(
    outline_world: np.ndarray,
    plane_normal: np.ndarray,
    coverage_ft: float,
) -> tuple[list[np.ndarray], list[float]]:
    """Lay panels by sweeping a coverage-wide strip across the panel.

    For each strip position perp_lo .. perp_lo + coverage along the
    cross-slope axis, clip the panel polygon to that strip. The
    resulting (possibly trapezoidal) polygon IS the panel's plan-view
    shape -- so panels never poke outside the panel, and trapezoidal
    hip faces get correctly tapered end panels.

    Returns (clipped_polys_world_xy, sheet_length_ft_list). Panel length
    is the run extent of each clipped polygon, converted from plan-view
    feet to slope (true-length) feet via 1 / cos(theta).
    """
    M_TO_FT = 3.280839895
    if outline_world.shape[0] < 3:
        return [], []

    # Run dir = down-slope horizontal direction. Perp dir = orthogonal in plan.
    nx, ny, nz = plane_normal
    horiz = math.hypot(float(nx), float(ny))
    if horiz < 1e-9:
        run_dir = np.array([1.0, 0.0])
    else:
        run_dir = -np.array([float(nx), float(ny)]) / horiz
    perp_dir = np.array([-run_dir[1], run_dir[0]])

    cos_theta = abs(float(nz))
    if cos_theta < 1e-6:
        cos_theta = 1.0

    # Convert coverage from feet to whatever world unit we're in. The
    # pipeline gives us meters, so divide by m->ft. (Caller ensures
    # outline_world is in the same unit as the rest of plan_normal frame.)
    coverage_world = coverage_ft / M_TO_FT

    perp_proj = outline_world @ perp_dir
    perp_min, perp_max = float(perp_proj.min()), float(perp_proj.max())
    perp_span = perp_max - perp_min
    if perp_span <= 0:
        return [], []

    n_panels = max(1, int(math.ceil(perp_span / coverage_world)))
    # Centre the strip stack so any overhang is split evenly on both sides.
    start_perp = perp_min - max(0.0, (n_panels * coverage_world - perp_span) / 2.0)

    polys: list[np.ndarray] = []
    lengths: list[float] = []
    for i in range(n_panels):
        lo = start_perp + i * coverage_world
        hi = lo + coverage_world
        clipped = _clip_polygon_to_strip(outline_world, perp_dir, lo, hi)
        if clipped.shape[0] < 3:
            continue
        run_proj = clipped @ run_dir
        run_extent_world = float(run_proj.max() - run_proj.min())
        # Convert plan-view world extent -> true slope length in feet.
        length_ft = run_extent_world * M_TO_FT / cos_theta
        polys.append(clipped)
        lengths.append(length_ft)
    return polys, lengths


def _draw_sheet_length_label(
    c: pdfcanvas.Canvas, poly_pg: np.ndarray, length_ft: float,
    sheet_id: int | None = None,
    run_axis_pg: np.ndarray | None = None,
) -> None:
    """Draw panel ID + length along the panel's slope (run) direction.

    Policy:
      - The length label is rotated along the RUN axis (eave->ridge) so
        adjacent panels read consistently and the visual length differences
        between panels are obvious.
      - The P# is always drawn, even for tiny corner-clipped panels. When
        the panel is too small to fit the ID inside, we draw it OUTSIDE the
        polygon with a thin leader line back to the centroid -- otherwise
        the installer loses sight of panels that were visibly trimmed.
    """
    if poly_pg.shape[0] < 3:
        return

    centroid = poly_pg.mean(axis=0)

    # Angle: prefer the panel's run axis (steep direction) so all panels on
    # the same face read the same way. Fall back to longest-edge direction.
    if run_axis_pg is not None and np.linalg.norm(run_axis_pg) > 1e-6:
        rd = run_axis_pg / np.linalg.norm(run_axis_pg)
        angle = math.degrees(math.atan2(rd[1], rd[0]))
    else:
        edges = np.diff(np.vstack([poly_pg, poly_pg[:1]]), axis=0)
        edge_lens = np.linalg.norm(edges, axis=1)
        long_edge = edges[int(np.argmax(edge_lens))]
        angle = math.degrees(math.atan2(long_edge[1], long_edge[0]))
    if angle > 90:
        angle -= 180
    elif angle < -90:
        angle += 180

    # Dimensions projected onto the (run, perp) basis in page space
    rad = math.radians(angle)
    run_vec = np.array([math.cos(rad), math.sin(rad)])
    perp_vec = np.array([-math.sin(rad), math.cos(rad)])
    run_proj = poly_pg @ run_vec
    perp_proj = poly_pg @ perp_vec
    run_extent = float(run_proj.max() - run_proj.min())  # panel length on page
    perp_extent = float(perp_proj.max() - perp_proj.min())  # panel width on page

    length_text = feet_to_ft_in(length_ft)
    fits_inside = perp_extent >= 10.0 and run_extent >= 40.0

    if fits_inside:
        # Two lines stacked across the panel's width (P# above, length below).
        text_size = max(4.5, min(8.0, perp_extent * 0.40))
        line_offset = max(text_size * 0.60, 3.0)
        id_pos = centroid + perp_vec * line_offset
        len_pos = centroid - perp_vec * line_offset
        if sheet_id is not None:
            _draw_centered_text(c, f"S{sheet_id}",
                                float(id_pos[0]), float(id_pos[1]),
                                rotate=angle, size=text_size * 0.9,
                                font=FONT_BOLD, color=colors.HexColor("#222222"))
        _draw_centered_text(c, length_text,
                            float(len_pos[0]), float(len_pos[1]),
                            rotate=angle, size=text_size,
                            color=colors.HexColor("#222222"))
        return

    # Panel is too small to hold both labels. Always show the P# with a
    # leader to keep the count contiguous; length only if it fits.
    if run_extent >= 20.0 and perp_extent >= 6.0:
        # Just enough room for the length inside, rotated along run axis
        _draw_centered_text(c, length_text,
                            float(centroid[0]), float(centroid[1]),
                            rotate=angle, size=max(4.0, min(6.5, perp_extent * 0.5)),
                            color=colors.HexColor("#222222"))
    if sheet_id is not None:
        # Pull the ID OUT of the polygon along the perp axis + leader line.
        # Alternate sides per panel to reduce pile-up on narrow strips: we
        # can't easily know adjacency here, so just pick the side with more
        # whitespace by flipping away from the polygon centroid-of-page.
        leader = perp_vec * (perp_extent / 2 + 8.0)
        out_pos = centroid + leader
        c.saveState()
        c.setStrokeColor(colors.HexColor("#888888"))
        c.setLineWidth(0.3)
        c.line(float(centroid[0]), float(centroid[1]),
               float(out_pos[0]), float(out_pos[1]))
        c.restoreState()
        _draw_centered_text(c, f"S{sheet_id}",
                            float(out_pos[0]) + float(perp_vec[0]) * 4,
                            float(out_pos[1]) + float(perp_vec[1]) * 4,
                            rotate=angle, size=5.5,
                            font=FONT_BOLD, color=colors.HexColor("#222222"))


def _draw_north_arrow(c: pdfcanvas.Canvas, x: float, y: float, size: float = 28.0) -> None:
    """Small N arrow inside a circle. Assumes world +Y = north so the arrow
    on the page points UP (positive page Y)."""
    c.saveState()
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.white)
    c.setLineWidth(0.75)
    c.circle(x, y, size / 2.0, stroke=1, fill=1)
    # Arrow shaft (bottom -> top inside circle)
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.4)
    c.line(x, y - size * 0.30, x, y + size * 0.32)
    # Arrowhead
    head = size * 0.10
    p = c.beginPath()
    p.moveTo(x, y + size * 0.40)
    p.lineTo(x - head, y + size * 0.20)
    p.lineTo(x + head, y + size * 0.20)
    p.close()
    c.setFillColor(colors.black)
    c.drawPath(p, stroke=0, fill=1)
    # "N" label below the arrow
    c.setFont(FONT_BOLD, 8)
    c.drawCentredString(x, y - size * 0.50, "N")
    c.restoreState()


# ---------------------------------------------------------------------------
# Label placement engine (tiered fallback: inline -> shift -> shrink -> leader -> marker)
# ---------------------------------------------------------------------------

def _text_bbox_aabb(text: str, size: float, anchor: np.ndarray,
                    angle_deg: float, font: str = FONT) -> tuple[float, float, float, float]:
    """Axis-aligned bbox (page-space) of ``text`` centered on ``anchor`` after
    rotation. We rotate the 4 local-space corners then take min/max.
    """
    w = float(pdfmetrics.stringWidth(text, font, size))
    h = float(size)  # conservative; Helvetica x-height is ~0.72*size
    hw, hh = w / 2.0, h / 2.0
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    corners = np.array([
        [-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh],
    ])
    rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
    world = corners @ rot.T + anchor
    xmin, ymin = world.min(axis=0)
    xmax, ymax = world.max(axis=0)
    # Small padding so touching-but-not-overlapping labels count as clear
    return float(xmin) - 1.5, float(ymin) - 1.5, float(xmax) + 1.5, float(ymax) + 1.5


def _aabbs_overlap(a: tuple[float, float, float, float],
                   b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _segment_intersects_aabb(p0: np.ndarray, p1: np.ndarray,
                             bbox: tuple[float, float, float, float]) -> bool:
    """True if segment p0->p1 crosses the AABB. Uses a Liang-Barsky-ish clip."""
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    xmin, ymin, xmax, ymax = bbox
    # Trivial inside / outside rejections
    if (x0 < xmin and x1 < xmin) or (x0 > xmax and x1 > xmax):
        return False
    if (y0 < ymin and y1 < ymin) or (y0 > ymax and y1 > ymax):
        return False
    # If any endpoint inside, intersects
    if xmin <= x0 <= xmax and ymin <= y0 <= ymax:
        return True
    if xmin <= x1 <= xmax and ymin <= y1 <= ymax:
        return True
    # Parametric clipping
    dx, dy = x1 - x0, y1 - y0
    t_enter, t_exit = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0),
                 (-dy, y0 - ymin), (dy, ymax - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t_exit:
                return False
            if t > t_enter:
                t_enter = t
        else:
            if t < t_enter:
                return False
            if t < t_exit:
                t_exit = t
    return t_enter <= t_exit


class _EdgeLabelSpec:
    """One edge label with enough metadata for the placement engine."""
    def __init__(self, edge_a: np.ndarray, edge_b: np.ndarray,
                 centroid_pg: np.ndarray, text: str,
                 base_size: float = 7.5):
        self.edge_a = edge_a.astype(float)
        self.edge_b = edge_b.astype(float)
        self.mid = 0.5 * (self.edge_a + self.edge_b)
        self.centroid = centroid_pg.astype(float)
        self.length = float(np.linalg.norm(self.edge_b - self.edge_a))
        edge = self.edge_b - self.edge_a
        normal = np.array([edge[1], -edge[0]])
        normal = normal / (np.linalg.norm(normal) + 1e-9)
        # Outward (away from polygon centroid)
        if float(np.dot(self.mid + normal - self.centroid, normal)) < 0:
            normal = -normal
        self.normal = normal
        angle = math.degrees(math.atan2(edge[1], edge[0]))
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        self.angle = angle
        self.text = text
        self.base_size = base_size


class _LabelPlacement:
    """Resolved placement for one label."""
    def __init__(self, spec: _EdgeLabelSpec):
        self.spec = spec
        self.mode = "inline"    # inline | leader | marker
        self.anchor = spec.mid + spec.normal * 22.0
        self.angle = spec.angle
        self.size = spec.base_size
        self.text = spec.text
        self.leader_from = spec.mid  # edge midpoint
        self.marker_num: int | None = None

    def bbox(self) -> tuple[float, float, float, float]:
        return _text_bbox_aabb(self.text, self.size, self.anchor,
                               0.0 if self.mode == "leader" else self.angle)


def _place_edge_labels(
    specs: list[_EdgeLabelSpec],
    obstacle_aabbs: list[tuple[float, float, float, float]],
    roof_edges: list[tuple[np.ndarray, np.ndarray]],
    margin_bounds: tuple[float, float, float, float],
    min_font_size: float = 5.0,
) -> list[_LabelPlacement]:
    """Place labels using a tiered fallback:
       1. inline at default outward offset
       2. shift along edge (t = 0.3 ... 0.7) if overlap
       3. shrink down to min_font_size if overlap
       4. push further outward along the normal
       5. leader line to nearest page margin
       6. numbered marker on the edge + legend
    """
    placements = [_LabelPlacement(s) for s in specs]

    def collides(p: _LabelPlacement, idx: int) -> bool:
        b = p.bbox()
        for j, q in enumerate(placements):
            if j == idx:
                continue
            if _aabbs_overlap(b, q.bbox()):
                return True
        for ob in obstacle_aabbs:
            if _aabbs_overlap(b, ob):
                return True
        # also check that the label doesn't sit on a roof edge
        for a, c in roof_edges:
            if _segment_intersects_aabb(a, c, b):
                return True
        return False

    # ---- Tier 1-4: inline adjustments ----
    OUTWARD_STEPS = [22.0, 28.0, 34.0, 42.0]
    SHIFT_Ts = [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]  # along-edge midpoint slide
    SIZE_STEPS_FRAC = [1.0, 0.9, 0.8, 0.72, 0.66]

    for idx, p in enumerate(placements):
        # Very short edges: force numbered-marker tier upfront
        if p.spec.length < max(16.0, 2.2 * p.spec.base_size):
            continue  # leave for later marker tier

        resolved = False
        for out in OUTWARD_STEPS:
            if resolved:
                break
            for t in SHIFT_Ts:
                if resolved:
                    break
                for size_frac in SIZE_STEPS_FRAC:
                    new_mid = p.spec.edge_a + t * (p.spec.edge_b - p.spec.edge_a)
                    p.anchor = new_mid + p.spec.normal * out
                    p.size = p.spec.base_size * size_frac
                    if p.size < min_font_size:
                        continue
                    if not collides(p, idx):
                        resolved = True
                        p.leader_from = new_mid
                        break

    # ---- Tier 5: leader line to nearest margin for still-colliding labels ----
    x0, y0, x1, y1 = margin_bounds
    MARGIN_PAD = 12.0
    for idx, p in enumerate(placements):
        if p.mode != "inline" or not collides(p, idx):
            continue
        # Already resolved? Check post-adjustments:
        if not collides(p, idx):
            continue
        # Route to nearest margin along the outward normal. Preference order:
        # the margin side the outward normal points toward first.
        outward = p.spec.normal
        candidates: list[tuple[np.ndarray, float]] = []
        if outward[0] > 0:
            candidates.append((np.array([x1 - MARGIN_PAD, p.spec.mid[1]]), x1 - p.spec.mid[0]))
            candidates.append((np.array([x0 + MARGIN_PAD, p.spec.mid[1]]), p.spec.mid[0] - x0))
        else:
            candidates.append((np.array([x0 + MARGIN_PAD, p.spec.mid[1]]), p.spec.mid[0] - x0))
            candidates.append((np.array([x1 - MARGIN_PAD, p.spec.mid[1]]), x1 - p.spec.mid[0]))
        if outward[1] > 0:
            candidates.append((np.array([p.spec.mid[0], y1 - MARGIN_PAD]), y1 - p.spec.mid[1]))
            candidates.append((np.array([p.spec.mid[0], y0 + MARGIN_PAD]), p.spec.mid[1] - y0))
        else:
            candidates.append((np.array([p.spec.mid[0], y0 + MARGIN_PAD]), p.spec.mid[1] - y0))
            candidates.append((np.array([p.spec.mid[0], y1 - MARGIN_PAD]), y1 - p.spec.mid[1]))
        # Pick the shortest leader that actually resolves
        candidates.sort(key=lambda c: c[1])
        trial_mode = p.mode
        trial_angle = p.angle
        p.mode = "leader"
        p.angle = 0.0
        p.size = max(p.spec.base_size * 0.85, min_font_size)
        resolved = False
        for cand, _dist in candidates:
            # try small perturbations along the margin to avoid other leaders
            for shift in (0, 22, -22, 44, -44, 66, -66):
                if abs(cand[0] - x0 - MARGIN_PAD) < 1 or abs(cand[0] - (x1 - MARGIN_PAD)) < 1:
                    trial = cand + np.array([0.0, float(shift)])
                else:
                    trial = cand + np.array([float(shift), 0.0])
                if not (x0 <= trial[0] <= x1 and y0 <= trial[1] <= y1):
                    continue
                p.anchor = trial
                if not collides(p, idx):
                    resolved = True
                    break
            if resolved:
                break
        if not resolved:
            # Roll back to inline; will be handled by marker tier below
            p.mode = trial_mode
            p.angle = trial_angle

    # ---- Tier 6: numbered markers for unresolved + very-short edges ----
    next_marker = 1
    for idx, p in enumerate(placements):
        needs_marker = (
            p.spec.length < max(16.0, 2.2 * p.spec.base_size)
            or (p.mode == "inline" and collides(p, idx))
        )
        if not needs_marker:
            continue
        p.mode = "marker"
        p.marker_num = next_marker
        p.anchor = p.spec.mid + p.spec.normal * 8.0
        p.angle = 0.0
        p.size = 6.5
        p.text = f"({p.marker_num})"
        next_marker += 1

    return placements


def _draw_placement(c: pdfcanvas.Canvas, p: _LabelPlacement) -> None:
    """Draw the resolved label (inline text / leader-line text / marker)."""
    if p.mode == "marker":
        # Small circled number sitting ON the edge midpoint
        c.saveState()
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#222222"))
        c.setLineWidth(0.6)
        c.circle(float(p.anchor[0]), float(p.anchor[1]), 7.0, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#222222"))
        c.setFont(FONT_BOLD, 6.0)
        c.drawCentredString(float(p.anchor[0]), float(p.anchor[1]) - 2.0, p.text)
        c.restoreState()
        return

    if p.mode == "leader":
        c.saveState()
        c.setStrokeColor(colors.HexColor("#888888"))
        c.setLineWidth(0.4)
        c.line(float(p.leader_from[0]), float(p.leader_from[1]),
               float(p.anchor[0]), float(p.anchor[1]))
        c.restoreState()
        _draw_centered_text(c, p.text,
                            float(p.anchor[0]), float(p.anchor[1]),
                            rotate=0.0, size=p.size,
                            color=colors.HexColor("#222222"))
        return

    # inline
    c.saveState()
    c.setStrokeColor(colors.HexColor("#AAAAAA"))
    c.setLineWidth(0.35)
    midline_end = p.spec.mid + p.spec.normal * 6.0
    c.line(float(p.spec.mid[0]), float(p.spec.mid[1]),
           float(midline_end[0]), float(midline_end[1]))
    c.restoreState()
    _draw_centered_text(c, p.text,
                        float(p.anchor[0]), float(p.anchor[1]),
                        rotate=p.angle, size=p.size,
                        color=colors.HexColor("#222222"))


def _draw_marker_legend(
    c: pdfcanvas.Canvas,
    placements: list[_LabelPlacement],
    x: float, y: float, w: float,
    title: str = "EDGE MARKERS",
) -> float:
    """Draw a small legend mapping (n) -> full edge label text.

    Returns the height used, so callers can layout beneath it.
    """
    markers = [p for p in placements if p.mode == "marker"]
    if not markers:
        return 0.0
    markers.sort(key=lambda p: p.marker_num or 0)
    rows = [(f"({p.marker_num})", p.spec.text) for p in markers]
    h = 18 + len(rows) * 9
    _draw_text_box(c, x, y - h, w, h, title, rows,
                   title_size=8.0, row_size=6.5)
    return h


def _draw_slope_marker(
    c: pdfcanvas.Canvas, x: float, y: float, slope_num: int,
    size: float = 18.0,
) -> None:
    """Slope marker (e.g. '+4') with a white halo so it stays readable when
    edge labels happen to land near the panel centroid."""
    text = f"+{slope_num}"
    half = size * 0.65
    c.saveState()
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.white)
    c.setFillAlpha(0.85)
    c.circle(x, y, half, stroke=0, fill=1)
    c.restoreState()
    _draw_centered_text(c, text, x, y, rotate=0.0, size=size,
                        font=FONT_BOLD, color=colors.HexColor("#003366"))


# ---------------------------------------------------------------------------
# Page 2: Edge / Trim Condition Diagram (Letter portrait)
# ---------------------------------------------------------------------------

PAGE2_PANELS_PER_PAGE = 6  # 2 cols x 3 rows. More than this packs too tight.


def _num_edge_trim_pages(roof: dict) -> int:
    """How many Edge/Trim diagram pages this roof will take."""
    n = len(roof.get("roof_panels", []))
    if n <= 0:
        return 1
    return math.ceil(n / PAGE2_PANELS_PER_PAGE)


def _render_page2(
    c: pdfcanvas.Canvas, roof: dict,
    chunk_index: int = 0,
    page_num: int = 2,
    total_pages: int = 4,
) -> None:
    """Render one page of the Edge/Trim diagram.

    Paginated at ``PAGE2_PANELS_PER_PAGE`` (=6) panels per page. Layout is
    always a 2-column x 3-row grid (last page may be partial). The caller
    invokes once per chunk and handles showPage() between them.
    """
    page_w, page_h = LETTER
    c.setPageSize((page_w, page_h))
    meta = _meta(roof)

    all_panels = roof.get("roof_panels", [])
    start = chunk_index * PAGE2_PANELS_PER_PAGE
    panels = all_panels[start:start + PAGE2_PANELS_PER_PAGE]
    total_chunks = _num_edge_trim_pages(roof)

    # Header
    c.setFont(FONT_BOLD, 12)
    title = "EDGE / TRIM CONDITION DIAGRAM"
    if total_chunks > 1:
        title = f"{title}  ({chunk_index + 1} of {total_chunks})"
    c.drawCentredString(page_w / 2.0, page_h - 40, title)
    c.setFont(FONT, 9)
    c.drawCentredString(page_w / 2.0, page_h - 54, meta["project_name"])
    c.setFont(FONT, 8)
    c.drawCentredString(page_w / 2.0, page_h - 66,
                        f"Estimate {meta['estimate_number']}")
    c.drawRightString(page_w - 40, page_h - 40,
                      f"Page {page_num} of {total_pages}")
    c.setFont(FONT, 7)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawRightString(page_w - 40, page_h - 52,
                      f"REV {meta['revision']}  |  {meta['date']}  |  DRAWN: {meta['drawn_by']}")
    c.setFillColor(colors.black)

    if not panels:
        return

    slope_num = _slope_numerator(roof.get("primary_slope", "4/12")) or 4

    # Fixed 2 x 3 grid (6 slots); last page may have empty slots.
    margin_x = 36
    top_y = page_h - 90
    bottom_y = 60
    cols = 2
    rows_per_page = 3
    slot_w = (page_w - 2 * margin_x - 24) / cols
    gap_y = 16
    slot_h = (top_y - bottom_y - (rows_per_page - 1) * gap_y) / rows_per_page

    # Use the ABSOLUTE panel index (not chunk-local) for the section header
    # so numbering is continuous across pages.
    page_placements: list[_LabelPlacement] = []
    marker_running = 0
    for local_idx, panel in enumerate(panels):
        absolute_idx = start + local_idx
        col = local_idx % cols
        row = local_idx // cols
        slot_x0 = margin_x + col * (slot_w + 24)
        slot_y0 = top_y - (row + 1) * slot_h - row * gap_y
        slot_placements = _draw_panel_edge_diagram(
            c, panel, slot_x0, slot_y0, slot_w, slot_h, slope_num,
            panel_label=panel.get("panel_id", f"P{absolute_idx + 1}"),
            marker_offset=marker_running,
        )
        marker_running += sum(1 for p in slot_placements if p.mode == "marker")
        page_placements.extend(slot_placements)

    # Page-level marker legend: one box spanning the bottom of the page,
    # listing every (N) marker that appeared in any slot on this page.
    markers = [p for p in page_placements if p.mode == "marker"]
    if markers:
        n = len(markers)
        cols_legend = 3
        rows_legend = math.ceil(n / cols_legend)
        legend_h = 16 + rows_legend * 10
        legend_y = 40
        legend_w = page_w - 2 * margin_x
        c.saveState()
        c.setStrokeColor(colors.black)
        c.setFillColor(colors.white)
        c.setLineWidth(0.6)
        c.rect(margin_x, legend_y, legend_w, legend_h, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#222222"))
        c.setFont(FONT_BOLD, 7.5)
        c.drawString(margin_x + 6, legend_y + legend_h - 10, "EDGE MARKERS")
        col_w = (legend_w - 12) / cols_legend
        markers.sort(key=lambda p: p.marker_num or 0)
        for i, p in enumerate(markers):
            cc = i % cols_legend
            rr = i // cols_legend
            cx = margin_x + 6 + cc * col_w
            cy = legend_y + legend_h - 18 - rr * 10
            c.setFont(FONT_BOLD, 6.5)
            c.drawString(cx, cy, f"({p.marker_num})")
            c.setFont(FONT, 6.5)
            c.drawString(cx + 20, cy, p.spec.text)
        c.restoreState()


def _draw_panel_edge_diagram(
    c: pdfcanvas.Canvas,
    panel: dict,
    x0: float, y0: float, w: float, h: float,
    slope_num: int,
    panel_label: str | None = None,
    marker_offset: int = 0,
) -> list[_LabelPlacement]:
    """Draw one panel's edge diagram; return its placed labels so the caller
    can aggregate markers into a page-level legend.

    ``marker_offset`` shifts the numbered marker sequence so each slot picks
    up where the previous slot left off (continuous numbering across a page).
    """
    outline = _panel_outline_2d(panel)
    if outline.shape[0] < 3:
        return []
    scale, offset = fit_to_box(outline, w, h, margin=0.18)
    offset = offset + np.array([x0, y0])

    # Panel header (above the slot)
    c.setFont(FONT_BOLD, 9)
    c.drawString(x0, y0 + h - 4,
                 panel_label or str(panel.get("panel_id", "panel")))

    outline_pg = np.array([_world_to_page(p, scale, offset) for p in outline])
    _draw_polygon(c, outline_pg, line_width=2.0, stroke=colors.black)

    centroid_pg = outline_pg.mean(axis=0)

    # Slope marker with a white halo, smaller font, sits at centroid
    _draw_slope_marker(c, float(centroid_pg[0]), float(centroid_pg[1]), slope_num)
    slope_bbox = (float(centroid_pg[0]) - 14, float(centroid_pg[1]) - 14,
                  float(centroid_pg[0]) + 14, float(centroid_pg[1]) + 14)

    # Collect edge label specs and run the placement engine so labels
    # never overlap the slope marker or each other.
    edges = panel.get("edges", [])
    n = outline_pg.shape[0]
    specs: list[_EdgeLabelSpec] = []
    for i, edge in enumerate(edges[:n]):
        p1 = outline_pg[i]
        p2 = outline_pg[(i + 1) % n]
        code = EDGE_CODE.get(edge.get("type", ""), edge.get("type", "??"))
        length_ft = float(edge.get("length_ft", 0.0))
        text = f"({code})-{feet_to_ft_in(length_ft)}"
        specs.append(_EdgeLabelSpec(p1, p2, centroid_pg, text, base_size=7.0))

    roof_edges_pg = [(outline_pg[i], outline_pg[(i + 1) % n]) for i in range(n)]
    # Slot bounds: labels may expand slightly past the polygon's drawing area
    margin_bounds = (x0 - 4.0, y0 - 4.0, x0 + w + 4.0, y0 + h + 4.0)
    placements = _place_edge_labels(
        specs, obstacle_aabbs=[slope_bbox],
        roof_edges=roof_edges_pg, margin_bounds=margin_bounds,
        min_font_size=5.0,
    )
    # Shift marker numbers so they stay unique across the whole page.
    if marker_offset:
        for p in placements:
            if p.mode == "marker" and p.marker_num is not None:
                p.marker_num += marker_offset
                p.text = f"({p.marker_num})"
    for p in placements:
        _draw_placement(c, p)
    return placements


# ---------------------------------------------------------------------------
# Page 3: Sheet Cut List (ANSI B landscape)
# ---------------------------------------------------------------------------

def _render_page3(
    c: pdfcanvas.Canvas, roof: dict,
    trim_formulas: dict[str, Callable[[dict[str, float]], float]],
    page_num: int = 3, total_pages: int = 4,
) -> None:
    page_w, page_h = ANSI_B_LANDSCAPE
    c.setPageSize((page_w, page_h))

    meta = _meta(roof)

    # Header
    c.setFont(FONT_BOLD, 14)
    c.drawString(40, page_h - 36, "SHEET CUT LIST")
    c.setFont(FONT, 9)
    c.drawString(40, page_h - 50,
                 f"{meta['project_name']}   |   {meta['project_address']}")
    c.drawRightString(page_w - 40, page_h - 36, f"Estimate {meta['estimate_number']}")
    c.drawRightString(page_w - 40, page_h - 50,
                      f"REV {meta['revision']}  |  {meta['date']}  |  "
                      f"DRAWN: {meta['drawn_by']}  |  Page {page_num} of {total_pages}")

    # Compute totals
    panels = roof.get("roof_panels", [])
    trim_totals = sum_edges_by_type(roof)
    total_sheet_lf = sum(
        float(p.get("length_ft", 0.0))
        for p in panels
        for s in p.get("sheets", [])
    )
    coverage_ft = float(roof.get("coverage_width_in", 24.0)) / 12.0
    sheet_area_sf = total_sheet_lf * coverage_ft

    # Roof area: each un-rotated panel polygon is in METERS (boundary_3d
    # is meters), so polygon_area_2d returns m^2. Convert to sqft, then to
    # squares (1 SQ = 100 sqft).
    roof_area_sf = 0.0
    for s in panels:
        outline = _panel_outline_2d(s)
        if outline.shape[0] >= 3:
            roof_area_sf += polygon_area_2d(outline) * SQM_TO_SQFT
    roof_area_sq = roof_area_sf / 100.0

    # ---- Right column: ESTIMATE INFO / TRIM TAKEOFF / SS TRIM stacked ----
    # Consolidated so the left side opens up for the panel grid.
    total_sheet_count = sum(len(p.get("sheets", [])) for p in panels)
    col_x = page_w - 300
    col_w = 260
    info_rows: list[tuple[str, str]] = [
        ("ESTIMATE #",     str(meta["estimate_number"])),
        ("TOTAL SHEETS",   f"{total_sheet_count}"),
        ("ROOF AREA (SQ)", f"{roof_area_sq:.1f}"),
        ("PRIMARY SLOPE",  str(roof.get("primary_slope", ""))),
        ("SECONDARY SLOPE",str(roof.get("secondary_slope", ""))),
        ("COVERAGE (IN)",  f"{roof.get('coverage_width_in', 0):.0f}"),
        ("SHEET LF",       feet_to_ft_in(total_sheet_lf)),
        ("SHEET AREA (SF)",f"{sheet_area_sf:.0f}"),
        ("WASTE %",        f"{roof.get('waste_pct', 0):.0f}%"),
        ("PROFILE",        str(roof.get("profile", ""))),
        ("GAUGE",          meta["gauge"]),
        ("MATERIAL",       meta["material"]),
        ("FINISH / COLOR", meta["finish_color"]),
    ]
    if "secondary_profile" in roof:
        sec = roof["secondary_profile"]
        info_rows.append(("2ND PROFILE", str(sec.get("profile", ""))))
        info_rows.append(("2ND COVERAGE (IN)", f"{sec.get('coverage_width_in', 0):.0f}"))
        info_rows.append(("2ND SHEET LF", feet_to_ft_in(sec.get('panel_lf', 0.0))))
    info_h = 24 + len(info_rows) * 11
    info_y = page_h - 70 - info_h
    _draw_text_box(c, col_x, info_y, col_w, info_h, "ESTIMATE INFO", info_rows)

    # Industry convention: print every trim type, even zero-LF, so the
    # installer knows nothing was missed.
    trim_rows = [
        (label, feet_to_ft_in(trim_totals.get(code, 0.0)))
        for label, code in TRIM_TAKEOFF_ORDER
    ]
    trim_h = 24 + len(trim_rows) * 11
    trim_y = info_y - 16 - trim_h
    _draw_text_box(c, col_x, trim_y, col_w, trim_h, "TRIM TAKEOFF (LF)", trim_rows)

    ss_rows = [
        (name, feet_to_ft_in(formula(trim_totals)))
        for name, formula in trim_formulas.items()
    ]
    ss_h = 24 + len(ss_rows) * 11
    ss_y = trim_y - 16 - ss_h
    _draw_text_box(c, col_x, ss_y, col_w, ss_h, "STANDING SEAM TRIM ITEMS", ss_rows)

    # ---- Panel grid: fills everything to the LEFT of the right column ----
    grid_x0 = 40
    grid_y0 = 60
    grid_w = col_x - grid_x0 - 20
    grid_h = page_h - 70 - grid_y0  # header at top

    _draw_sheet_grid(c, panels, grid_x0, grid_y0, grid_w, grid_h)

    # ---- Disclaimer at the very bottom ----
    c.setFont(FONT_ITALIC, 6)
    c.setFillColor(colors.HexColor("#444444"))
    _draw_wrapped(c, DISCLAIMER, 40, 28, page_w - 80, line_h=8.0, font=FONT_ITALIC, size=6.0)
    c.setFillColor(colors.black)


SHEETS_PANELS_PER_ROW = 6


def _draw_sheet_grid(
    c: pdfcanvas.Canvas, panels: list[dict],
    x0: float, y0: float, w: float, h: float,
) -> None:
    """Grid of per-panel cut-list columns, wrapping to new rows every 6 panels.

    Each panel gets a slot (title + stack of proportional horizontal bars).
    When a panel has more sheets than fit vertically in its slot, sheets
    flow into sub-columns within that slot.
    """
    if not panels:
        return
    n_panels = len(panels)
    cols = min(SHEETS_PANELS_PER_ROW, n_panels)
    n_rows = math.ceil(n_panels / SHEETS_PANELS_PER_ROW)
    col_gap = 16.0
    row_gap_panels = 20.0
    panel_w = (w - (cols - 1) * col_gap) / cols
    panel_h = (h - (n_rows - 1) * row_gap_panels) / n_rows

    bar_h = 10.0
    bar_gap = 2.0
    heading_h = 14.0
    sheets_per_subcol = max(4, int((panel_h - heading_h) / (bar_h + bar_gap)))

    for p_idx, panel in enumerate(panels):
        col = p_idx % SHEETS_PANELS_PER_ROW
        row = p_idx // SHEETS_PANELS_PER_ROW
        panel_x = x0 + col * (panel_w + col_gap)
        # First row is at the top: its baseline y = y0 + h - panel_h
        panel_y = y0 + h - (row + 1) * panel_h - row * row_gap_panels

        # Panel heading
        c.setFont(FONT_BOLD, 9)
        c.setFillColor(colors.black)
        title = f"{panel.get('panel_id', 'panel')}  ({len(panel.get('sheets', []))} sheets)"
        c.drawString(panel_x, panel_y + panel_h - 10, title)

        # Shop-floor convention: cut list shows sheets longest -> shortest so
        # the fabricator can batch similar lengths. The original sheet_id is
        # preserved on each bar so the installer can trace a bar back to its
        # physical position on the Page-1 layout plan.
        sheets = sorted(
            panel.get("sheets", []),
            key=lambda sh: float(sh.get("length_ft", 0.0)),
            reverse=True,
        )
        if not sheets:
            continue
        max_len = float(sheets[0].get("length_ft", 0.0))
        if max_len <= 0:
            continue

        n_subcols = max(1, math.ceil(len(sheets) / sheets_per_subcol))
        subcol_gap = 8.0
        subcol_w = (panel_w - (n_subcols - 1) * subcol_gap) / n_subcols
        bar_max = subcol_w
        ft_per_pt = max_len / bar_max

        for i, sheet in enumerate(sheets):
            sub = i // sheets_per_subcol
            local_row = i % sheets_per_subcol
            sub_x = panel_x + sub * (subcol_w + subcol_gap)
            bar_y = (panel_y + panel_h - heading_h
                     - (local_row + 1) * (bar_h + bar_gap))
            length_ft = float(sheet.get("length_ft", 0.0))
            bar_w = length_ft / ft_per_pt
            c.setStrokeColor(colors.black)
            c.setFillColor(colors.HexColor("#e6f0fa"))
            c.setLineWidth(0.5)
            c.rect(sub_x, bar_y, bar_w, bar_h, stroke=1, fill=1)
            label = feet_to_ft_in(length_ft)
            c.setFont(FONT, 6)
            c.setFillColor(colors.black)
            c.drawString(sub_x + 3, bar_y + 3, label)


def _draw_wrapped(
    c: pdfcanvas.Canvas, text: str, x: float, y: float, w: float,
    line_h: float = 9.0, font: str = FONT, size: float = 7.0,
) -> None:
    """Cheap word-wrap; draws bottom-up from y."""
    words = text.split()
    lines: list[str] = []
    cur: list[str] = []
    for word in words:
        trial = " ".join(cur + [word])
        if pdfmetrics.stringWidth(trial, font, size) > w and cur:
            lines.append(" ".join(cur))
            cur = [word]
        else:
            cur.append(word)
    if cur:
        lines.append(" ".join(cur))
    c.setFont(font, size)
    for i, line in enumerate(lines):
        c.drawString(x, y + (len(lines) - 1 - i) * line_h, line)


# ---------------------------------------------------------------------------
# Page 4: Combined Edge Detail (ANSI B landscape)
# ---------------------------------------------------------------------------

def _render_page4(
    c: pdfcanvas.Canvas, roof: dict,
    trim_formulas: dict[str, Callable[[dict[str, float]], float]],
    page_num: int = 4, total_pages: int = 4,
) -> None:
    page_w, page_h = ANSI_B_LANDSCAPE
    c.setPageSize((page_w, page_h))

    meta = _meta(roof)

    # Header
    c.setFont(FONT_BOLD, 14)
    c.drawString(40, page_h - 36, "EDGE DETAIL -- COMBINED VIEW")
    c.setFont(FONT, 9)
    c.drawString(40, page_h - 50, meta["project_name"])
    c.drawRightString(page_w - 40, page_h - 36, f"Estimate {meta['estimate_number']}")
    c.drawRightString(page_w - 40, page_h - 50,
                      f"REV {meta['revision']}  |  {meta['date']}  |  "
                      f"DRAWN: {meta['drawn_by']}  |  Page {page_num} of {total_pages}")

    panels = roof.get("roof_panels", [])
    if not panels:
        return

    # Drawing area (left 2/3 of page); right 1/3 = info blocks
    drw_x0, drw_y0 = 40.0, 70.0
    drw_w = page_w * 2.0 / 3.0 - 40
    drw_h = page_h - 110.0

    # Combined bounds across all panels in actual world XY
    all_xy = np.vstack([
        np.asarray(s["boundary_3d"], dtype=float)[:, :2]
        for s in panels if len(s.get("boundary_3d", []))
    ])
    scale, offset = fit_to_box(all_xy, drw_w, drw_h, margin=0.08)
    offset = offset + np.array([drw_x0, drw_y0])

    slope_num = _slope_numerator(roof.get("primary_slope", "4/12")) or 4

    # Draw panel outlines + slope markers first so labels render on top.
    specs: list[_EdgeLabelSpec] = []
    obstacle_aabbs: list[tuple[float, float, float, float]] = []
    all_roof_edges_pg: list[tuple[np.ndarray, np.ndarray]] = []
    for panel in panels:
        boundary = np.asarray(panel.get("boundary_3d", []), dtype=float)
        if boundary.shape[0] < 3:
            continue
        outline_pg = np.array([_world_to_page(p[:2], scale, offset) for p in boundary])
        _draw_polygon(c, outline_pg, line_width=2.0, stroke=colors.black)
        centroid_pg = outline_pg.mean(axis=0)
        _draw_slope_marker(c, float(centroid_pg[0]), float(centroid_pg[1]), slope_num)
        obstacle_aabbs.append((float(centroid_pg[0]) - 14, float(centroid_pg[1]) - 14,
                               float(centroid_pg[0]) + 14, float(centroid_pg[1]) + 14))
        edges = panel.get("edges", [])
        n = outline_pg.shape[0]
        all_roof_edges_pg.extend([(outline_pg[i], outline_pg[(i + 1) % n])
                                  for i in range(n)])
        for i, edge in enumerate(edges[:n]):
            p1 = outline_pg[i]
            p2 = outline_pg[(i + 1) % n]
            code = EDGE_CODE.get(edge.get("type", ""), edge.get("type", "??"))
            length_ft = float(edge.get("length_ft", 0.0))
            text = f"({code})-{feet_to_ft_in(length_ft)}"
            specs.append(_EdgeLabelSpec(p1, p2, centroid_pg, text, base_size=7.5))

    margin_bounds = (drw_x0 - 6.0, drw_y0 - 6.0,
                     drw_x0 + drw_w + 6.0, drw_y0 + drw_h + 6.0)
    placements = _place_edge_labels(
        specs, obstacle_aabbs=obstacle_aabbs,
        roof_edges=all_roof_edges_pg, margin_bounds=margin_bounds,
        min_font_size=5.0,
    )
    for p in placements:
        _draw_placement(c, p)

    # Right column: same trim takeoff + standing seam blocks as page 3
    trim_totals = sum_edges_by_type(roof)
    info_x = drw_x0 + drw_w + 24
    info_w = page_w - info_x - 40

    trim_rows = [
        (label, feet_to_ft_in(trim_totals.get(code, 0.0)))
        for label, code in TRIM_TAKEOFF_ORDER
    ]
    _draw_text_box(c, info_x, page_h - 270, info_w, 200,
                   "TRIM TAKEOFF (LF)", trim_rows)

    ss_rows = [
        (name, feet_to_ft_in(formula(trim_totals)))
        for name, formula in trim_formulas.items()
    ]
    _draw_text_box(c, info_x, page_h - 400, info_w, 110,
                   "STANDING SEAM TRIM ITEMS", ss_rows)

    # Trim-code reference legend
    legend_rows = [(code, label.replace("_", " ")) for label, code in EDGE_CODE.items()]
    _draw_text_box(c, info_x, 80, info_w, 200,
                   "TRIM CODES", legend_rows)

    # Edge-marker legend: only rendered when the placement engine had to
    # demote labels to numbered markers. Sits above the TRIM CODES box.
    markers = sorted(
        (p for p in placements if p.mode == "marker"),
        key=lambda p: p.marker_num or 0,
    )
    if markers:
        marker_rows = [(f"({p.marker_num})", p.spec.text) for p in markers]
        marker_h = min(200, 24 + len(marker_rows) * 10)
        _draw_text_box(c, info_x, 290, info_w, marker_h,
                       "EDGE MARKERS", marker_rows,
                       title_size=9.0, row_size=7.0)


# ---------------------------------------------------------------------------
# Page 5: 3D Views (top + 4 tilted sides)
# ---------------------------------------------------------------------------

def _render_page_3d_views(
    c: pdfcanvas.Canvas, roof: dict,
    page_num: int = 5, total_pages: int = 5,
) -> None:
    """Embed a 5-view 3D render of the roof.

    Views: TOP (orthographic down) plus FRONT / BACK / LEFT / RIGHT with
    ~20 deg downward tilt so elevation and roof surface are both visible.
    Rendered via matplotlib 3D, saved to a single composite PNG, embedded.
    """
    page_w, page_h = ANSI_B_LANDSCAPE
    c.setPageSize((page_w, page_h))
    meta = _meta(roof)

    # Header (same format as other landscape pages)
    c.setFont(FONT_BOLD, 14)
    c.drawString(40, page_h - 36, "3D VIEWS")
    c.setFont(FONT, 9)
    c.drawString(40, page_h - 50, meta["project_name"])
    c.drawRightString(page_w - 40, page_h - 36,
                      f"Estimate {meta['estimate_number']}")
    c.drawRightString(page_w - 40, page_h - 50,
                      f"REV {meta['revision']}  |  {meta['date']}  |  "
                      f"DRAWN: {meta['drawn_by']}  |  "
                      f"Page {page_num} of {total_pages}")

    panels = roof.get("roof_panels", [])
    if not panels:
        c.setFont(FONT, 10)
        c.drawCentredString(page_w / 2.0, page_h / 2.0, "(no roof geometry)")
        return

    try:
        png_path = _render_5views_png(panels)
    except Exception as e:  # matplotlib missing or mis-configured
        log.warning("page 3D: skipping render (%s)", e)
        c.setFont(FONT, 10)
        c.drawCentredString(page_w / 2.0, page_h / 2.0,
                            "(3D render unavailable)")
        return
    if png_path is None:
        return
    try:
        # Fill the page minus header
        img_x = 40.0
        img_y = 60.0
        img_w = page_w - 80.0
        img_h = page_h - 130.0
        c.drawImage(str(png_path), img_x, img_y, width=img_w, height=img_h,
                    preserveAspectRatio=True, mask="auto")
    finally:
        try:
            png_path.unlink(missing_ok=True)
        except Exception:
            pass


def _render_5views_png(panels: list[dict]) -> Path | None:
    """Render top + 4 angled side views into one composite PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    tris = []
    all_xyz: list[np.ndarray] = []
    face_colors: list[str] = []
    edge_colors: list[str] = []
    for idx, panel in enumerate(panels):
        b = np.asarray(panel.get("boundary_3d", []), dtype=float)
        if b.shape[0] < 3:
            continue
        tris.append(b)
        all_xyz.append(b)
        c_hex = PANEL_PALETTE[idx % len(PANEL_PALETTE)]
        face_colors.append(c_hex)
        edge_colors.append("#222222")
    if not tris:
        return None
    pts = np.vstack(all_xyz)
    mn = pts.min(axis=0)
    mx = pts.max(axis=0)

    fig = plt.figure(figsize=(16, 10), dpi=150)
    gs = fig.add_gridspec(2, 4, wspace=0.02, hspace=0.08)
    ax_top   = fig.add_subplot(gs[0:2, 0:2], projection="3d")
    ax_front = fig.add_subplot(gs[0, 2],     projection="3d")
    ax_right = fig.add_subplot(gs[0, 3],     projection="3d")
    ax_back  = fig.add_subplot(gs[1, 2],     projection="3d")
    ax_left  = fig.add_subplot(gs[1, 3],     projection="3d")

    # Side views get a modest downward tilt (20 deg) so the viewer sees
    # BOTH the elevation and some roof surface.
    SIDE_TILT = 20.0
    # Matplotlib 3D leaves a lot of whitespace around the plot; "zoom" is
    # implemented by shrinking the axis limits around the roof's centroid.
    # The TOP view uses the natural bounds (no zoom). The 4 side views zoom
    # in so the roof fills the subplot.
    SIDE_ZOOM = 1.35

    cx = 0.5 * (mn[0] + mx[0])
    cy = 0.5 * (mn[1] + mx[1])
    cz = 0.5 * (mn[2] + mx[2])

    def populate(ax, elev, azim, title, zoom=1.0, exaggerate_z=1.0):
        for verts, fc, ec in zip(tris, face_colors, edge_colors):
            pc = Poly3DCollection(
                [verts], facecolor=fc, edgecolor=ec, linewidth=0.6, alpha=0.95,
            )
            ax.add_collection3d(pc)
        hx = 0.5 * (mx[0] - mn[0]) / zoom
        hy = 0.5 * (mx[1] - mn[1]) / zoom
        hz = 0.5 * (mx[2] - mn[2]) / zoom
        ax.set_xlim(cx - hx, cx + hx)
        ax.set_ylim(cy - hy, cy + hy)
        ax.set_zlim(cz - hz, cz + hz)
        try:
            ax.set_box_aspect((hx, hy, hz * exaggerate_z))
        except Exception:
            pass
        try:
            ax.set_proj_type("ortho")  # cleaner architectural look
        except Exception:
            pass
        ax.set_axis_off()
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(title, fontsize=11, fontweight="bold")

    # Top view: orthographic down at natural bounds.
    populate(ax_top,   elev=90.0, azim=-90.0, title="TOP", zoom=1.05)
    # Side views: zoom in + exaggerate Z slightly so a shallow roof reads
    # clearly as a sloped surface rather than a flat line.
    populate(ax_front, elev=SIDE_TILT, azim=-90.0, title="FRONT",
             zoom=SIDE_ZOOM, exaggerate_z=1.6)
    populate(ax_right, elev=SIDE_TILT, azim=0.0,   title="RIGHT",
             zoom=SIDE_ZOOM, exaggerate_z=1.6)
    populate(ax_back,  elev=SIDE_TILT, azim=90.0,  title="BACK",
             zoom=SIDE_ZOOM, exaggerate_z=1.6)
    populate(ax_left,  elev=SIDE_TILT, azim=180.0, title="LEFT",
             zoom=SIDE_ZOOM, exaggerate_z=1.6)

    fd, tmp = tempfile.mkstemp(suffix=".png")
    import os
    os.close(fd)
    out = Path(tmp)
    fig.savefig(out, bbox_inches="tight", pad_inches=0.1, facecolor="white")
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_shop_drawings(
    roof: dict,
    output_path: str | Path = "output/shop_drawings.pdf",
    trim_formulas: dict[str, Callable[[dict[str, float]], float]] | None = None,
) -> Path:
    """Render the 4-page metal-roofing shop drawing PDF."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    formulas = dict(DEFAULT_TRIM_FORMULAS)
    if trim_formulas:
        formulas.update(trim_formulas)

    # Integrity check: pages 1, 3, and 4 all read from the same per-panel
    # panels list, so this single accumulator drives every visible total.
    panels = roof.get("roof_panels", [])
    n_sheets = sum(len(p.get("sheets", [])) for p in panels)
    total_lf = sum(float(sh.get("length_ft", 0.0))
                   for p in panels for sh in p.get("sheets", []))
    log.info("shop_drawings: %d panels, %d sheets, total sheet LF = %.1f ft",
             len(panels), n_sheets, total_lf)

    # Dynamic page count: panel layout + edge/trim pages + sheet cut list
    # + combined edge detail + 3D views
    n_p2 = _num_edge_trim_pages(roof)
    total_pages = 1 + n_p2 + 1 + 1 + 1

    c = pdfcanvas.Canvas(str(output_path), pagesize=ANSI_B_PORTRAIT)

    log.info("shop_drawings: rendering page 1 (panel layout plan)")
    _render_page1(c, roof, page_num=1, total_pages=total_pages)
    c.showPage()

    for i in range(n_p2):
        log.info("shop_drawings: rendering page %d (edge / trim diagram %d/%d)",
                 2 + i, i + 1, n_p2)
        _render_page2(c, roof, chunk_index=i,
                      page_num=2 + i, total_pages=total_pages)
        c.showPage()

    p3_num = 2 + n_p2
    log.info("shop_drawings: rendering page %d (sheet cut list)", p3_num)
    _render_page3(c, roof, formulas, page_num=p3_num, total_pages=total_pages)
    c.showPage()

    p4_num = p3_num + 1
    log.info("shop_drawings: rendering page %d (combined edge detail)", p4_num)
    _render_page4(c, roof, formulas, page_num=p4_num, total_pages=total_pages)
    c.showPage()

    p5_num = p4_num + 1
    log.info("shop_drawings: rendering page %d (3D views)", p5_num)
    _render_page_3d_views(c, roof, page_num=p5_num, total_pages=total_pages)
    c.showPage()

    c.save()
    log.info("shop_drawings: wrote %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Sample (Integrity Metals "LEGACY - 4009 MAVERICK AVE" reference)
# ---------------------------------------------------------------------------

def _build_sample_roof() -> dict:
    """Hardcoded sample matching the reference drawing's headline numbers.

    Roof is a single rectangular gable, 46' wide along the ridge, ~38'
    eave-to-eave footprint, 4/12 pitch facing south. Slope length ~19.4'
    so total slope area ~ 1786 sf, divided by 100 -> ~17.9 SQ.
    """
    pitch = 4.0 / 12.0
    width_ft = 46.0
    eave_to_ridge_ft = 19.0  # plan distance from eave to ridge along slope direction
    # Plane normal for south-facing 4/12 panel (down-slope toward +y in our convention)
    # Slope rise per run = 4/12 -> tan(theta) = 4/12. Normal tilts north (-y).
    horiz = math.cos(math.atan(pitch))
    vert = math.sin(math.atan(pitch))
    normal = [0.0, -horiz, vert]  # not unit yet, but rotation_to_horizontal normalizes

    # Plan-view rectangle for the south face. Place ridge along y=0 (north),
    # eave along y=-eave_to_ridge_ft (south).
    # boundary_3d (ridge endpoints + eave endpoints), elevation rises northward.
    ridge_z = eave_to_ridge_ft * pitch
    boundary_3d = [
        [0.0, -eave_to_ridge_ft, 0.0],
        [width_ft, -eave_to_ridge_ft, 0.0],
        [width_ft, 0.0, ridge_z],
        [0.0, 0.0, ridge_z],
    ]

    edges = [
        {"type": "EAVE",   "length_ft": 30.08,
         "p1": boundary_3d[0], "p2": boundary_3d[1]},
        {"type": "GABLE",  "length_ft": 17.83,
         "p1": boundary_3d[1], "p2": boundary_3d[2]},
        {"type": "RIDGE",  "length_ft": 46.0,
         "p1": boundary_3d[2], "p2": boundary_3d[3]},
        {"type": "VALLEY", "length_ft": 12.92,
         "p1": boundary_3d[3], "p2": boundary_3d[0]},
    ]
    # Add a HIP edge to exercise the full edge-code coverage on page 2
    # (the geometry only has 4 edges; HIP just feeds the trim takeoff).
    extra_trim = [{"type": "HIP", "length_ft": 12.75, "p1": [0, 0, 0], "p2": [0, 0, 0]}]

    # 51 panels with lengths totaling ~986.83 ft, between 13'-2" and 22'-0"
    rng = np.random.default_rng(42)
    n_panels = 51
    target_total = 986.833
    raw = rng.uniform(13.167, 22.0, size=n_panels)
    raw *= target_total / raw.sum()
    sheet_lengths = [round(float(x), 3) for x in raw]
    sheets = [
        {"sheet_id": i + 1, "length_ft": L, "run_direction": [0.0, -1.0, 0.0]}
        for i, L in enumerate(sheet_lengths)
    ]

    return {
        "estimate_number": "250610-IME-391",
        "project_name": "LEGACY - 4009 MAVERICK AVE",
        "project_address": "4009 MAVERICK AVE SARASOTA FL",
        "primary_slope": "4/12",
        "secondary_slope": "0/12",
        "coverage_width_in": 24.0,
        "profile": "SV",
        "waste_pct": 11.0,
        "roof_panels": [
            {
                "panel_id": "main_front",
                "plane_normal": normal,
                "plane_centroid": [width_ft / 2, -eave_to_ridge_ft / 2, ridge_z / 2],
                "boundary_3d": boundary_3d,
                "edges": edges + extra_trim,
                "sheets": sheets,
            },
        ],
    }


SAMPLE_ROOF = _build_sample_roof()


# ---------------------------------------------------------------------------
# Adapter: pipeline outputs (polygons + planes) -> roof dict
# ---------------------------------------------------------------------------

def _classify_panel_edges(
    polygon: np.ndarray,
    other_polygons: list[np.ndarray],
    z_min: float,
    z_max: float,
    shared_tol: float = 0.4,
) -> list[str]:
    """Best-effort edge type per polygon edge.

    Decision tree per edge (no semantic knowledge from upstream, just geometry):
      shared with another panel?
        ridge-ish elevation -> RIDGE   (else HIP)
      not shared (perimeter):
        roughly horizontal in 3D and at low z -> EAVE
        roughly horizontal and at high z      -> RIDGE  (unusual on perimeter)
        slope-aligned (significant z-change)  -> GABLE
    """
    n = polygon.shape[0]
    z_span = max(z_max - z_min, 1e-6)
    out: list[str] = []
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        # Check shared-edge: does any other polygon have an edge whose
        # endpoints both fall within shared_tol of (a, b) or (b, a)?
        is_shared = False
        for q in other_polygons:
            m = q.shape[0]
            for j in range(m):
                qa = q[j]
                qb = q[(j + 1) % m]
                d_aa = np.linalg.norm(a - qa)
                d_bb = np.linalg.norm(b - qb)
                d_ab = np.linalg.norm(a - qb)
                d_ba = np.linalg.norm(b - qa)
                if (d_aa < shared_tol and d_bb < shared_tol) or \
                   (d_ab < shared_tol and d_ba < shared_tol):
                    is_shared = True
                    break
            if is_shared:
                break

        z_mid = 0.5 * (a[2] + b[2])
        rel_z = (z_mid - z_min) / z_span
        edge = b - a
        edge_horiz = float(math.hypot(edge[0], edge[1]))
        edge_v = abs(float(edge[2]))
        is_horizontal = edge_horiz > 0 and (edge_v / max(edge_horiz, 1e-6)) < 0.15

        if is_shared:
            out.append("RIDGE" if rel_z > 0.6 else "HIP")
            continue
        if is_horizontal:
            out.append("EAVE" if rel_z < 0.4 else "RIDGE")
        else:
            out.append("GABLE")
    return out


def _layout_sheets(
    polygon: np.ndarray,
    plane: Plane,
    coverage_ft: float,
) -> list[dict]:
    """Generate metal-panel records for one panel using scan-line clipping.

    Sweeps a coverage-wide strip perpendicular to the slope across the
    panel polygon. Each clipped strip's run extent (converted to slope
    length) is the panel length. This gives correct trimmed lengths on
    trapezoidal hip faces -- panels at corners come out shorter than
    panels in the middle, matching what the fabricator actually cuts.
    """
    # Down-slope horizontal direction = -horizontal projection of normal
    nx, ny, _nz = plane.normal
    horiz = math.hypot(nx, ny)
    if horiz < 1e-9:
        run_dir = np.array([1.0, 0.0])
    else:
        run_dir = -np.array([nx, ny]) / horiz

    polys_clip, lengths_ft = _scan_line_sheets(polygon[:, :2], plane.normal, coverage_ft)
    return [
        {
            "sheet_id": i + 1,
            "length_ft": round(length, 3),
            "run_direction": [float(run_dir[0]), float(run_dir[1]), 0.0],
        }
        for i, length in enumerate(lengths_ft)
    ]


def roof_dict_from_pipeline(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
    project_meta: dict,
    coverage_width_in: float = 24.0,
    waste_pct: float = 11.0,
    profile: str = "SV",
) -> dict:
    """Convert pipeline outputs into the ``roof`` dict shape consumed by
    ``generate_shop_drawings``.

    One labeled polygon -> one ``roof_section``. Edge types are classified
    geometrically (eave / ridge / hip / gable) using elevation + adjacency.
    Length values are converted from meters (pipeline) to feet (drawing).
    """
    M_TO_FT = 3.280839895

    # Z-range across the entire roof, used by the eave/ridge classifier
    all_z = np.concatenate([poly[:, 2] for poly in polygons.values()])
    z_min, z_max = float(all_z.min()), float(all_z.max())

    # Average pitch from all panels for the primary_slope label
    rises = []
    for plane in planes.values():
        nx, ny, nz = plane.normal
        if abs(nz) > 1e-9:
            rises.append(round(math.hypot(nx, ny) / abs(nz) * 12))
    primary_rise = int(round(float(np.median(rises)))) if rises else 4
    primary_slope = f"{primary_rise}/12"

    coverage_ft = coverage_width_in / 12.0

    panels = []
    panel_ids = sorted(polygons.keys())
    for pid in panel_ids:
        poly = polygons[pid]
        plane = planes[pid]
        others = [polygons[other] for other in panel_ids if other != pid]
        types = _classify_panel_edges(poly, others, z_min, z_max)

        # Drop degenerate edges (corner-snap can collapse two clicks into
        # one position). Keep boundary vertices and edge labels in lockstep:
        # if edge i is degenerate, vertex i+1 is dropped from boundary_3d.
        MIN_EDGE_FT = 0.25  # 3 inches
        kept_verts: list[np.ndarray] = []
        kept_types: list[str] = []
        n = poly.shape[0]
        for i in range(n):
            a = poly[i]
            b = poly[(i + 1) % n]
            length_ft = float(np.linalg.norm(b - a)) * M_TO_FT
            if length_ft < MIN_EDGE_FT:
                continue
            kept_verts.append(a)
            kept_types.append(types[i])
        if len(kept_verts) < 3:
            log.warning("panel %d collapsed to <3 vertices after degenerate-edge filter; skipping", pid)
            continue

        # Re-emit edges from the cleaned vertex ring
        edges = []
        m = len(kept_verts)
        for i in range(m):
            a = kept_verts[i]
            b = kept_verts[(i + 1) % m]
            length_ft = float(np.linalg.norm(b - a)) * M_TO_FT
            edges.append({
                "type": kept_types[i],
                "length_ft": round(length_ft, 3),
                "p1": [float(a[0]), float(a[1]), float(a[2])],
                "p2": [float(b[0]), float(b[1]), float(b[2])],
            })

        cleaned_poly = np.array(kept_verts)
        boundary_3d = [[float(x), float(y), float(z)] for x, y, z in cleaned_poly]
        centroid = cleaned_poly.mean(axis=0)
        panels.append({
            "panel_id": f"panel_{pid}",
            "plane_normal": [float(x) for x in plane.normal],
            "plane_centroid": [float(centroid[0]), float(centroid[1]), float(centroid[2])],
            "boundary_3d": boundary_3d,
            "edges": edges,
            "sheets": _layout_sheets(cleaned_poly, plane, coverage_ft),
        })

    return {
        "estimate_number": project_meta.get("estimate_number", "AUTO-0001"),
        "project_name": project_meta.get("project_name", "ROOF PROTOTYPE"),
        "project_address": project_meta.get("project_address", "ADDRESS UNKNOWN"),
        "primary_slope": primary_slope,
        "secondary_slope": project_meta.get("secondary_slope", "0/12"),
        "coverage_width_in": coverage_width_in,
        "profile": profile,
        "waste_pct": waste_pct,
        "roof_panels": panels,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    out = generate_shop_drawings(SAMPLE_ROOF, "output/shop_drawings_sample.pdf")
    print(f"wrote {out}")
