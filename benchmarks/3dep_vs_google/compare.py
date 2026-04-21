"""Phase 4 — Compare Google vs 3DEP plane fits for a single roof.

Preconditions (you enforce these manually before running):
  • Both sample_ids exist in training_samples.
  • Both have a training_labels row with identical panel topology.
  • Panel 1 in sample A is the same physical roof face as panel 1 in sample B.

The script re-runs the production plane-fit path (rasterise polygon → erode
to skip edge bleed → SVD plane via ``fit_plane``) for each label set, and
additionally runs a NO-erosion variant on the 3DEP side — because the whole
premise of the spike is that LiDAR might make the erosion trick obsolete.

Everything imported from ``roof_pipeline`` is imported read-only: we do not
modify a single line of pipeline code.

CLI:
    python benchmarks/3dep_vs_google/compare.py \\
        --google-sample-id <uuid> \\
        --3dep-sample-id   <uuid> \\
        --output-report benchmarks/3dep_vs_google/results/
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio

from common import env_required, load_project_env, slugify

log = logging.getLogger("bench.compare")

# Match the constants used in roof_pipeline/api/pipeline.py. They are local
# to a function there, so we duplicate the VALUES (not the code) so a
# benchmark re-run reproduces the production behaviour exactly.
EDGE_BLEED_ERODE_PX = 2
MIN_INTERIOR_PIXELS = 8
MAX_SANE_RISE_OVER_12 = 18

M_TO_FT = 3.280839895
SQM_TO_SQFT = 10.7639104


# ---------------------------------------------------------------------------
# Dataclasses for per-panel results
# ---------------------------------------------------------------------------


@dataclass
class PanelFit:
    """Outcome of fitting one panel against one DSM."""

    panel_id: int
    pixel_count: int
    used_erosion: bool
    rms_residual_m: float
    slope_rise_over_12: float
    area_sqft: float
    normal: tuple[float, float, float]
    warning: str = ""


@dataclass
class PanelCompare:
    google: PanelFit
    three_dep: PanelFit
    three_dep_no_erode: PanelFit


# ---------------------------------------------------------------------------
# Supabase + Storage helpers
# ---------------------------------------------------------------------------


def _client():
    from supabase import create_client  # type: ignore

    url = env_required("SUPABASE_URL")
    key = env_required("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _fetch_sample_row(client, sample_id: str) -> dict:
    res = (
        client.table("training_samples").select("*").eq("id", sample_id)
        .maybe_single().execute()
    )
    if not res or not res.data:
        raise SystemExit(f"ERROR: no training_samples row for id={sample_id}")
    return res.data


def _fetch_labels(client, sample_id: str) -> list[dict]:
    res = (
        client.table("training_labels").select("annotations")
        .eq("sample_id", sample_id).execute()
    )
    if not res.data:
        raise SystemExit(
            f"ERROR: no training_labels row for sample_id={sample_id}. "
            "Label the sample in the UI before running compare."
        )
    ann = res.data[0].get("annotations") or {}
    panels = ann.get("panels") or []
    if not panels:
        raise SystemExit(
            f"ERROR: training_labels row for {sample_id} has zero panels. "
            "Re-save labels in the UI."
        )
    return panels


def _download_dsm(client, bucket: str, storage_path: str) -> tuple[np.ndarray, float]:
    log.info("downloading %s/%s", bucket, storage_path)
    data = client.storage.from_(bucket).download(storage_path)
    with rasterio.open(BytesIO(data)) as ds:
        arr = ds.read(1).astype(np.float32)
        res_m = float(abs(ds.res[0]))
        # Normalize nodata to NaN regardless of how the source flagged it.
        if ds.nodata is not None and not np.isnan(ds.nodata):
            arr = np.where(arr == ds.nodata, np.nan, arr)
    return arr, res_m


# ---------------------------------------------------------------------------
# Plane fit — mirrors the production pipeline but takes a `use_erosion` flag
# ---------------------------------------------------------------------------


def _fit_panel(
    dsm: np.ndarray,
    corners_pix: list[list[float]],
    res_m: float,
    use_erosion: bool,
) -> PanelFit | None:
    """Return a PanelFit for one user polygon on one DSM.

    Mirrors ``roof_pipeline/api/pipeline.py:638-750`` verbatim in behaviour:
    rasterise the polygon with skimage, drop NaN DSM cells, optionally
    erode by ``EDGE_BLEED_ERODE_PX``, then call ``fit_plane`` from
    ``roof_pipeline.planes``. We don't import that function's wrapper code
    because that module is tangled into FastAPI; we just reproduce the
    ~20 lines of polygon-to-plane math.
    """
    from scipy.ndimage import binary_erosion
    from skimage.draw import polygon as draw_polygon

    from roof_pipeline.planes import fit_plane  # type: ignore — read-only import

    h, w = dsm.shape
    if len(corners_pix) < 3:
        return None

    cols_px = np.array([float(c[0]) for c in corners_pix])
    rows_px = np.array([float(c[1]) for c in corners_pix])
    rr, cc = draw_polygon(rows_px, cols_px, shape=(h, w))
    if rr.size == 0:
        return None

    full_mask = np.zeros((h, w), dtype=bool)
    full_mask[rr, cc] = True
    full_mask &= ~np.isnan(dsm)

    used_erosion = False
    warning = ""
    if use_erosion:
        eroded = binary_erosion(full_mask, iterations=EDGE_BLEED_ERODE_PX)
        if eroded.sum() >= MIN_INTERIOR_PIXELS:
            sample_mask = eroded
            used_erosion = True
        elif full_mask.sum() >= MIN_INTERIOR_PIXELS:
            sample_mask = full_mask
            warning = "erosion emptied mask; fell back to unfilled"
        else:
            return None
    else:
        if full_mask.sum() < MIN_INTERIOR_PIXELS:
            return None
        sample_mask = full_mask

    rows, cols = np.where(sample_mask)
    x = cols * res_m
    y = rows * res_m
    z = dsm[rows, cols]
    pts = np.stack([x, y, z], axis=1).astype(np.float64)

    plane = fit_plane(pts)
    nx, ny, nz = plane.normal

    # Slope in rise-over-12 form: rise/run where run=12. tan(pitch)*12.
    if abs(nz) < 1e-9:
        slope_rise = 99.0
    else:
        slope_rise = float(np.hypot(nx, ny) / nz) * 12.0

    if slope_rise > MAX_SANE_RISE_OVER_12:
        warning = (warning + "; " if warning else "") + f">{MAX_SANE_RISE_OVER_12}/12 sanity warning"

    # Surface area = plan-view area / |nz|. Plan area via the shoelace on
    # the user corners (in meters), then divide by nz to get true surface area.
    xs_m = cols_px * res_m
    ys_m = rows_px * res_m
    plan_area_m2 = 0.5 * abs(np.sum(
        xs_m * np.roll(ys_m, -1) - np.roll(xs_m, -1) * ys_m
    ))
    if abs(nz) < 1e-6:
        surface_m2 = plan_area_m2
    else:
        surface_m2 = plan_area_m2 / abs(nz)
    area_sqft = float(surface_m2 * SQM_TO_SQFT)

    return PanelFit(
        panel_id=0,  # filled in by caller
        pixel_count=int(sample_mask.sum()),
        used_erosion=used_erosion,
        rms_residual_m=float(plane.rms_residual),
        slope_rise_over_12=float(slope_rise),
        area_sqft=area_sqft,
        normal=(float(nx), float(ny), float(nz)),
        warning=warning,
    )


# ---------------------------------------------------------------------------
# Comparison + report rendering
# ---------------------------------------------------------------------------


def _validate_topology(google_panels: list[dict], dep_panels: list[dict]) -> None:
    if len(google_panels) != len(dep_panels):
        raise SystemExit(
            f"ERROR: panel counts differ — google has {len(google_panels)}, "
            f"3DEP has {len(dep_panels)}. Re-label so both samples have the "
            "same topology."
        )
    mismatches: list[str] = []
    for i, (gp, dp) in enumerate(zip(google_panels, dep_panels)):
        gc = len(gp.get("corners_pix", []))
        dc = len(dp.get("corners_pix", []))
        if abs(gc - dc) > 1:
            mismatches.append(
                f"panel {i + 1}: google has {gc} corners, 3DEP has {dc}"
            )
    if mismatches:
        raise SystemExit(
            "ERROR: corner counts differ beyond the ±1 tolerance:\n  "
            + "\n  ".join(mismatches)
        )


def _compare_panels(
    google_dsm: np.ndarray,
    dep_dsm: np.ndarray,
    google_panels: list[dict],
    dep_panels: list[dict],
    google_res: float,
    dep_res: float,
) -> list[PanelCompare]:
    out: list[PanelCompare] = []
    for i, (gp, dp) in enumerate(zip(google_panels, dep_panels)):
        pid = i + 1
        g = _fit_panel(google_dsm, gp["corners_pix"], google_res, use_erosion=True)
        d = _fit_panel(dep_dsm, dp["corners_pix"], dep_res, use_erosion=True)
        d_ne = _fit_panel(dep_dsm, dp["corners_pix"], dep_res, use_erosion=False)
        if g is None or d is None or d_ne is None:
            raise SystemExit(
                f"ERROR: panel {pid} could not be fit on one of the DSMs "
                "(too few interior pixels). Re-label so both polygons cover "
                "enough of each DSM."
            )
        g.panel_id = d.panel_id = d_ne.panel_id = pid
        out.append(PanelCompare(google=g, three_dep=d, three_dep_no_erode=d_ne))
    return out


def _load_ground_truth(address: str) -> dict | None:
    slug = slugify(address)
    path = Path(__file__).parent / "ground_truth" / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        log.warning("ground-truth file %s failed to load: %s", path, e)
        return None


def _render_report(
    google_row: dict,
    dep_row: dict,
    per_panel: list[PanelCompare],
    ground_truth: dict | None,
) -> str:
    """Build the Markdown report body."""
    lines: list[str] = []
    lines.append(f"# 3DEP vs Google DSM — {google_row.get('formatted_address', '?')}")
    lines.append("")
    lines.append(
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}"
    )
    lines.append("")
    lines.append("## Samples")
    lines.append("")
    lines.append(
        f"- **Google**: `{google_row['id']}` — "
        f"{google_row.get('width_px')}×{google_row.get('height_px')} px, "
        f"{google_row.get('meters_per_px')} m/px"
    )
    dep_meta = dep_row.get("building_insights") or {}
    if isinstance(dep_meta, str):
        try:
            dep_meta = json.loads(dep_meta)
        except Exception:
            dep_meta = {}
    lines.append(
        f"- **3DEP**:   `{dep_row['id']}` — "
        f"{dep_row.get('width_px')}×{dep_row.get('height_px')} px, "
        f"{dep_row.get('meters_per_px')} m/px, "
        f"capture={dep_meta.get('capture_date', '?')}, "
        f"QL={dep_meta.get('ql_level', '?')}, "
        f"density={dep_meta.get('point_density_per_m2', '?')} pts/m²"
    )
    lines.append("")

    # Per-panel table
    lines.append("## Per-panel comparison")
    lines.append("")
    header = ("| Panel | Google slope | 3DEP slope | 3DEP no-erode | Δ slope "
              "| Google RMS (m) | 3DEP RMS (m) | Δ RMS | Google area | "
              "3DEP area | Δ area |")
    sep = ("|---|---|---|---|---|---|---|---|---|---|---|")
    lines.append(header)
    lines.append(sep)
    for pc in per_panel:
        g, d, dne = pc.google, pc.three_dep, pc.three_dep_no_erode
        dslope = d.slope_rise_over_12 - g.slope_rise_over_12
        drms_pct = ((d.rms_residual_m - g.rms_residual_m)
                    / max(g.rms_residual_m, 1e-6)) * 100
        darea_pct = ((d.area_sqft - g.area_sqft)
                     / max(g.area_sqft, 1e-6)) * 100
        lines.append(
            f"| {g.panel_id} "
            f"| {g.slope_rise_over_12:.2f}/12 "
            f"| {d.slope_rise_over_12:.2f}/12 "
            f"| {dne.slope_rise_over_12:.2f}/12 "
            f"| {dslope:+.2f} "
            f"| {g.rms_residual_m:.3f} "
            f"| {d.rms_residual_m:.3f} "
            f"| {drms_pct:+.0f}% "
            f"| {g.area_sqft:.0f} sqft "
            f"| {d.area_sqft:.0f} sqft "
            f"| {darea_pct:+.1f}% |"
        )

    # Warnings
    warnings = [
        (pc.google.panel_id, "google", pc.google.warning) for pc in per_panel
        if pc.google.warning
    ] + [
        (pc.three_dep.panel_id, "3dep", pc.three_dep.warning) for pc in per_panel
        if pc.three_dep.warning
    ] + [
        (pc.three_dep_no_erode.panel_id, "3dep-noerode", pc.three_dep_no_erode.warning)
        for pc in per_panel if pc.three_dep_no_erode.warning
    ]
    if warnings:
        lines.append("")
        lines.append("### Warnings")
        for pid, src, msg in warnings:
            lines.append(f"- panel {pid} ({src}): {msg}")

    # Aggregate stats
    n = len(per_panel)
    mean_rms_reduction = float(np.mean([
        (g.rms_residual_m - d.rms_residual_m) / max(g.rms_residual_m, 1e-6)
        for pc in per_panel
        for g, d in [(pc.google, pc.three_dep)]
    ])) * 100
    google_sanity = sum(
        1 for pc in per_panel
        if pc.google.slope_rise_over_12 > MAX_SANE_RISE_OVER_12
    )
    dep_sanity = sum(
        1 for pc in per_panel
        if pc.three_dep.slope_rise_over_12 > MAX_SANE_RISE_OVER_12
    )
    mean_abs_slope_delta = float(np.mean([
        abs(pc.three_dep.slope_rise_over_12 - pc.google.slope_rise_over_12)
        for pc in per_panel
    ]))
    erode_obsolete = all(
        abs(pc.three_dep.slope_rise_over_12 - pc.three_dep_no_erode.slope_rise_over_12)
        <= 0.2 for pc in per_panel
    )

    lines.append("")
    lines.append("## Aggregate stats")
    lines.append("")
    lines.append(f"- Panels compared: **{n}**")
    lines.append(f"- Mean RMS residual reduction (3DEP vs Google): **{mean_rms_reduction:+.1f}%**")
    lines.append(f"- Mean |Δ slope|: **{mean_abs_slope_delta:.2f}/12**")
    lines.append(f"- Google panels triggering >18/12 sanity warning: **{google_sanity}/{n}**")
    lines.append(f"- 3DEP panels triggering >18/12 sanity warning: **{dep_sanity}/{n}**")
    lines.append(
        f"- Erosion obsolete for LiDAR on this roof? "
        f"**{'yes' if erode_obsolete else 'no'}** "
        "(all panels within 0.2/12 between with-erode and no-erode 3DEP)"
    )

    # Verdict
    if (mean_rms_reduction > 40
            and all(
                abs(pc.three_dep.slope_rise_over_12 - pc.google.slope_rise_over_12) <= 2
                or pc.three_dep.slope_rise_over_12 <= pc.google.slope_rise_over_12
                for pc in per_panel
            )
            and dep_sanity == 0):
        verdict = "3DEP wins"
    elif mean_rms_reduction < 20 or dep_sanity > google_sanity:
        verdict = "Google wins"
    else:
        verdict = "Mixed"

    lines.append("")
    lines.append(f"## Verdict: **{verdict}**")
    lines.append("")

    # Optional ground-truth comparison
    if ground_truth and ground_truth.get("panels"):
        lines.append("## Ground-truth delta (from "
                     f"`ground_truth/{slugify(google_row.get('formatted_address',''))}.json`)")
        lines.append("")
        lines.append(f"Source: {ground_truth.get('source', '?')}")
        lines.append("")
        lines.append("| Panel | GT slope | Google Δ | 3DEP Δ | GT area | Google Δ% | 3DEP Δ% |")
        lines.append("|---|---|---|---|---|---|---|")
        gt_by_id = {p["id"]: p for p in ground_truth["panels"]}
        for pc in per_panel:
            gt = gt_by_id.get(pc.google.panel_id)
            if not gt:
                continue
            gt_slope = gt["slope_rise_over_12"]
            gt_area = gt["area_sqft"]
            g_dslope = pc.google.slope_rise_over_12 - gt_slope
            d_dslope = pc.three_dep.slope_rise_over_12 - gt_slope
            g_darea = (pc.google.area_sqft - gt_area) / max(gt_area, 1e-6) * 100
            d_darea = (pc.three_dep.area_sqft - gt_area) / max(gt_area, 1e-6) * 100
            lines.append(
                f"| {pc.google.panel_id} | {gt_slope:.2f}/12 "
                f"| {g_dslope:+.2f} | {d_dslope:+.2f} "
                f"| {gt_area:.0f} sqft "
                f"| {g_darea:+.1f}% | {d_darea:+.1f}% |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # argparse can't have a flag starting with a digit, so we pre-munge the
    # "--3dep-sample-id" arg the brief asks for into "--threedep-sample-id".
    argv = list(argv if argv is not None else sys.argv[1:])
    argv = ["--threedep-sample-id" if a == "--3dep-sample-id" else a for a in argv]

    parser = argparse.ArgumentParser(description="Compare Google vs 3DEP plane fits")
    parser.add_argument("--google-sample-id", required=True)
    parser.add_argument("--threedep-sample-id", required=True,
                        help="(also accepted as --3dep-sample-id)")
    parser.add_argument("--output-report", type=Path,
                        default=Path(__file__).parent / "results",
                        help="directory to write the Markdown report into")
    parser.add_argument("--bucket", default="training-data")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_project_env()
    client = _client()

    google_row = _fetch_sample_row(client, args.google_sample_id)
    dep_row = _fetch_sample_row(client, args.threedep_sample_id)

    # Defensive: confirm they were tagged with the expected source. A missing
    # `source` column means migration 020 hasn't been applied — in which
    # case we fall back to a gentle warning rather than hard-failing.
    if "source" in google_row and google_row["source"] not in (None, "google"):
        log.warning("google sample id=%s has source=%r",
                    args.google_sample_id, google_row["source"])
    if "source" in dep_row and dep_row["source"] not in (None, "3dep"):
        log.warning("3dep sample id=%s has source=%r",
                    args.threedep_sample_id, dep_row["source"])

    google_panels = _fetch_labels(client, args.google_sample_id)
    dep_panels = _fetch_labels(client, args.threedep_sample_id)
    _validate_topology(google_panels, dep_panels)

    google_dsm, google_res = _download_dsm(
        client, args.bucket, google_row["dsm_storage_path"],
    )
    dep_dsm, dep_res = _download_dsm(
        client, args.bucket, dep_row["dsm_storage_path"],
    )

    per_panel = _compare_panels(
        google_dsm, dep_dsm, google_panels, dep_panels, google_res, dep_res,
    )

    gt = _load_ground_truth(google_row.get("formatted_address", ""))
    report = _render_report(google_row, dep_row, per_panel, gt)

    args.output_report.mkdir(parents=True, exist_ok=True)
    slug = slugify(google_row.get("formatted_address", "unknown"))
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = args.output_report / f"{ts}_{slug}.md"
    out_path.write_text(report)

    # Echo the verdict line + path so batch runners can scrape it.
    verdict_line = next(
        (ln for ln in report.splitlines() if ln.startswith("## Verdict")),
        "## Verdict: (unknown)",
    )
    print(f"\n{verdict_line}\nReport: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
