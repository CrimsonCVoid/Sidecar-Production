"""Run the full pipeline on a real GeoTIFF DSM + a labeled .npy panel mask.

Usage:
    python -m roof_pipeline.run_real path/to/dsm.tif path/to/mask.npy \
        [--out-dir output_real]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import rasterio

from .boundaries import extract_panel_polygons, polygons_from_clicks
from .cutsheets import write_cutsheets_pdf
from .mesh import build_roof_mesh, export_mesh
from .planes import fit_all_panels
from .snapping import (
    densify_shared_edges_xy,
    snap_shared_corners_xy,
    snap_shared_edges,
)
from .ts_export import write_ts_json
from .ts_render_pdf import render_pdf_from_json
from .shop_drawings import generate_shop_drawings, roof_dict_from_pipeline

log = logging.getLogger("roof_pipeline.real")


def _load_dsm(path: Path) -> tuple[np.ndarray, float]:
    with rasterio.open(path) as src:
        dsm = src.read(1).astype(np.float32)
        res_m = abs(float(src.transform.a))
        nodata = src.nodata
    if nodata is not None:
        dsm = np.where(dsm == nodata, np.nan, dsm)
    return dsm, res_m


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("dsm", type=Path)
    ap.add_argument("mask", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("output_real"))
    ap.add_argument("--snap-tol", type=float, default=1.0,
                    help="corner snap tolerance in meters (clicks within this merge)")
    ap.add_argument("--no-clicks", action="store_true",
                    help="ignore panels.json and re-trace contours from the mask")
    ap.add_argument("--project-name", default="ROOF PROTOTYPE")
    ap.add_argument("--project-address", default="ADDRESS UNKNOWN")
    ap.add_argument("--estimate-number", default=None,
                    help="defaults to the DSM filename stem")
    ap.add_argument("--coverage-in", type=float, default=24.0)
    ap.add_argument("--profile", default="SV")
    ap.add_argument("--waste-pct", type=float, default=11.0)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    log.info("loading DSM %s", args.dsm)
    dsm, res_m = _load_dsm(args.dsm)
    log.info("DSM: shape=%s, res=%.3f m/px, nan=%.1f%%",
             dsm.shape, res_m, 100.0 * np.isnan(dsm).mean())

    log.info("loading mask %s", args.mask)
    mask = np.load(args.mask).astype(np.uint8)
    if mask.shape != dsm.shape:
        raise ValueError(f"mask shape {mask.shape} != dsm shape {dsm.shape}")
    panel_ids = sorted(int(i) for i in np.unique(mask) if i != 0)
    log.info("mask: %d panels (ids: %s)", len(panel_ids), panel_ids)

    # NaN-safety: clear mask where DSM has no data so plane fits never see NaN
    mask = np.where(np.isnan(dsm), 0, mask).astype(np.uint8)

    log.info("=== plane fits ===")
    planes = fit_all_panels(dsm, mask, res_m)

    # Prefer the click-coords path -- exactly N vertices, straight edges.
    panels_json = args.mask.with_suffix(".json")
    if panels_json.exists() and not args.no_clicks:
        log.info("=== boundaries from clicks (%s) ===", panels_json.name)
        polygons = polygons_from_clicks(panels_json, dsm, res_m, planes)
        # 2D (plan-view) adjacency: two panels are snapped/densified when
        # they overlap in XY regardless of their elevation. Matters for
        # roofs where a low patio abuts a tall main roof.
        log.info("=== corner snapping (XY, tol=%.3f m) ===", args.snap_tol)
        polygons = snap_shared_corners_xy(polygons, planes, tol=args.snap_tol)
        log.info("=== edge densification (XY, tol=%.3f m) ===", args.snap_tol * 0.6)
        polygons = densify_shared_edges_xy(polygons, planes, tol=args.snap_tol * 0.6)
    else:
        log.info("=== boundaries from mask contours (fallback) ===")
        polygons = extract_panel_polygons(mask, dsm, res_m, planes)
        log.info("=== edge snapping (tol=%.3f m) ===", args.snap_tol)
        polygons = snap_shared_edges(polygons, tol=args.snap_tol)

    log.info("=== mesh ===")
    mesh = build_roof_mesh(polygons, planes)
    paths = export_mesh(mesh, args.out_dir)

    log.info("=== cut sheets ===")
    pdf_path = write_cutsheets_pdf(
        polygons, planes, mesh, args.out_dir / "cutsheets.pdf",
    )

    log.info("=== TS exporter JSON ===")
    json_path = write_ts_json(
        polygons, planes, mesh, args.out_dir / "cutsheets.ts.json",
    )

    log.info("=== TS-render PDF (mirrors browser output) ===")
    ts_pdf_path = render_pdf_from_json(
        json_path, args.out_dir / "cutsheets.ts.pdf",
    )

    log.info("=== shop drawings PDF (Integrity-Metals format) ===")
    project_meta = {
        "estimate_number": args.estimate_number or args.dsm.stem,
        "project_name": args.project_name,
        "project_address": args.project_address,
    }
    roof_dict = roof_dict_from_pipeline(
        polygons, planes, project_meta,
        coverage_width_in=args.coverage_in,
        waste_pct=args.waste_pct,
        profile=args.profile,
    )
    shop_pdf_path = generate_shop_drawings(
        roof_dict, args.out_dir / "shop_drawings.pdf",
    )

    log.info("DONE  obj=%s  gltf=%s  pdf=%s  json=%s  ts_pdf=%s  shop_pdf=%s",
             paths["obj"], paths["gltf"], pdf_path, json_path,
             ts_pdf_path, shop_pdf_path)


if __name__ == "__main__":
    main()
