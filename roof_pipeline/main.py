"""End-to-end pipeline driver: synthetic DSM -> mesh + cut-sheet PDF."""

from __future__ import annotations

import logging
from pathlib import Path

from .boundaries import extract_panel_polygons
from .cutsheets import write_cutsheets_pdf
from .mesh import build_roof_mesh, export_mesh
from .planes import fit_all_panels
from .snapping import snap_shared_edges
from .synthetic import make_synthetic_gable
from .ts_export import write_ts_json
from .ts_render_pdf import render_pdf_from_json

log = logging.getLogger("roof_pipeline")


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== stage 1: synthetic DSM + mask ===")
    roof = make_synthetic_gable()

    log.info("=== stage 2: per-panel plane fits ===")
    planes = fit_all_panels(roof.dsm, roof.mask, roof.res_m)

    log.info("=== stage 3: boundary extraction + plane projection ===")
    polygons = extract_panel_polygons(roof.mask, roof.dsm, roof.res_m, planes)

    log.info("=== stage 4: edge snapping ===")
    polygons = snap_shared_edges(polygons, tol=0.15)

    log.info("=== stage 5: mesh build + export ===")
    mesh = build_roof_mesh(polygons, planes)
    paths = export_mesh(mesh, out_dir)

    log.info("=== stage 6: cut-sheet PDF ===")
    pdf_path = write_cutsheets_pdf(polygons, planes, mesh, out_dir / "cutsheets.pdf")

    log.info("=== stage 7: TS exporter JSON ===")
    json_path = write_ts_json(polygons, planes, mesh, out_dir / "cutsheets.ts.json")

    log.info("=== stage 8: TS-render PDF (mirrors browser output) ===")
    ts_pdf_path = render_pdf_from_json(json_path, out_dir / "cutsheets.ts.pdf")

    log.info("DONE  obj=%s  gltf=%s  pdf=%s  json=%s  ts_pdf=%s",
             paths["obj"], paths["gltf"], pdf_path, json_path, ts_pdf_path)


if __name__ == "__main__":
    run()
