"""Python renderer that mirrors the TS PDF_Exporter to validate the JSON.

Reads ``cutsheets.ts.json`` (produced by ``ts_export.py``) and writes a PDF
using the SAME coordinate convention as the TS class:

    pageX = z * scale + 300
    pageY = -x * scale + 400          (PDF Y axis = up, matches pdf-lib)
    pageSize = 600 x 800

Text follows the AddTextAtV3 rule: rotate += 90 degrees, anchor offset so
the text is centered on its placement point.

Use this to preview locally what the browser-side PDF will look like.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont  # noqa: F401  (kept for future use)
from reportlab.pdfgen import canvas as pdfcanvas

log = logging.getLogger(__name__)

PAGE_W, PAGE_H = 600.0, 800.0
SCALE = 0.5
FONT = "Helvetica"


def _to_page(pt: dict) -> tuple[float, float]:
    """TS DrawLineFromV3 transform."""
    return pt["z"] * SCALE + 300.0, -pt["x"] * SCALE + 400.0


def _polyline(c: pdfcanvas.Canvas, pts: list[dict], rgba: dict, thickness: float):
    if len(pts) < 2:
        return
    c.saveState()
    c.setStrokeColorRGB(rgba["r"], rgba["g"], rgba["b"])
    c.setStrokeAlpha(rgba.get("a", 1.0))
    c.setLineWidth(thickness)
    c.setLineCap(1)  # round, matches TS LineCapStyle.Round
    n = len(pts)
    for i in range(n):
        if i == 1 and i == n - 1:
            continue  # matches the TS skip for the degenerate 2-point closing edge
        x0, y0 = _to_page(pts[i])
        x1, y1 = _to_page(pts[(i + 1) % n])
        c.line(x0, y0, x1, y1)
    c.restoreState()


def _centered_text(
    c: pdfcanvas.Canvas,
    text: str,
    page_x: float,
    page_y: float,
    rotate_deg: float,
    size: float,
    add_height: float,
    rgba: dict,
):
    """Replicates TS AddText: text centered on (page_x, page_y) with rotation
    applied around that anchor (so add_height shifts in the rotated frame)."""
    width = pdfmetrics.stringWidth(text, FONT, size)
    # ReportLab text origin is the baseline-left; we want anchor at center.
    # Build a transform that rotates around (page_x, page_y) and offsets the
    # text so its midpoint sits there, with `add_height` perpendicular shift.
    c.saveState()
    c.translate(page_x, page_y)
    c.rotate(rotate_deg)
    c.translate(-width / 2.0, -size / 2.0 + add_height)
    c.setFillColorRGB(rgba["r"], rgba["g"], rgba["b"])
    c.setFillAlpha(rgba.get("a", 1.0))
    c.setFont(FONT, size)
    c.drawString(0, 0, text)
    c.restoreState()


def _centered_text_at_v3(
    c: pdfcanvas.Canvas,
    text: str,
    pt: dict,
    rotate_deg: float,
    size: float,
    add_height: float,
    rgba: dict,
):
    """Mirror of TS AddTextAtV3: same +90 deg offset and same scale on size/height."""
    page_x, page_y = _to_page(pt)
    _centered_text(
        c, text, page_x, page_y,
        rotate_deg + 90.0,
        size * SCALE,
        add_height * SCALE,
        rgba,
    )


def _centroid(pts: list[dict]) -> dict:
    n = len(pts)
    return {
        "x": sum(p["x"] for p in pts) / n,
        "z": sum(p["z"] for p in pts) / n,
    }


def render_pdf_from_json(json_path: str | Path, out_path: str | Path) -> Path:
    json_path = Path(json_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(json_path) as f:
        data = json.load(f)

    page_count = int(data["page_count"])
    draw_types = sorted(data["draw_types"], key=lambda d: d["order"])

    c = pdfcanvas.Canvas(str(out_path), pagesize=(PAGE_W, PAGE_H))

    # We render page-by-page so we don't have to flush+rebuild canvas state.
    # For each page index, walk DrawTypes in order, then their draws that
    # target this page (via the type's `layers` list).
    for page_idx in range(page_count):
        page_meta = next(
            (m for m in data.get("page_meta", []) if m.get("page") == page_idx),
            {"type": "?"},
        )

        # Faint header so you can see which page is which while previewing
        c.setFont(FONT, 8)
        c.setFillGray(0.5)
        c.drawString(15, PAGE_H - 18, f"page {page_idx} ({page_meta.get('type', '?')})")

        for dt in draw_types:
            if page_idx not in dt.get("layers", []):
                continue
            rgba = dt["color"]
            text_size = dt.get("text_size", 8.0)
            add_h = dt.get("text_height_offset", 0.0)

            for d in dt["draws"]:
                pts = d["points"]
                _polyline(c, pts, rgba, thickness=2.0 * SCALE)
                if d.get("text") is not None and pts:
                    anchor = _centroid(pts) if len(pts) > 1 else pts[0]
                    _centered_text_at_v3(
                        c, d["text"], anchor,
                        d.get("text_rotate", 0.0),
                        text_size, add_h,
                        {"r": rgba["r"], "g": rgba["g"], "b": rgba["b"], "a": 0.5},
                    )

        c.showPage()

    c.save()
    log.info("rendered %s from %s (%d pages)", out_path, json_path, page_count)
    return out_path


def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("json", type=Path, help="cutsheets.ts.json path")
    ap.add_argument("--out", type=Path, default=None,
                    help="output PDF path (defaults to <json>.pdf)")
    args = ap.parse_args()
    out = args.out or args.json.with_suffix(".pdf")
    render_pdf_from_json(args.json, out)


if __name__ == "__main__":
    main()
