"""Run the full pipeline on a real GeoTIFF DSM + a labeled .npy panel mask.

Usage:
    python -m roof_pipeline.run_real path/to/dsm.tif path/to/mask.npy \
        [--out-dir output_real]

Programmatic usage (from API or other callers):
    from roof_pipeline.run_real import run_pipeline, _load_dsm

    dsm, res_m = _load_dsm(Path("dsm.tif"))
    mask = np.load("mask.npy").astype(np.uint8)
    paths = run_pipeline(dsm, mask, res_m, Path("/tmp/out"), use_snap_v2=True)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from io import BytesIO
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
from .panel_snap_v2 import snap_polygons as snap_v2
from .panel_snap_v2.graph import build_feature_graph, print_dryrun

log = logging.getLogger("roof_pipeline.real")


def _load_dsm(path: Path) -> tuple[np.ndarray, float]:
    with rasterio.open(path) as src:
        dsm = src.read(1).astype(np.float32)
        res_m = abs(float(src.transform.a))
        nodata = src.nodata
    if nodata is not None:
        dsm = np.where(dsm == nodata, np.nan, dsm)
    return dsm, res_m


# ---------------------------------------------------------------------------
# Callable pipeline entry point (used by both CLI and API)
# ---------------------------------------------------------------------------

def run_pipeline(
    dsm: np.ndarray,
    mask: np.ndarray,
    res_m: float,
    out_dir: Path,
    *,
    snap_tol: float = 1.0,
    use_snap_v2: bool = False,
    no_clicks: bool = False,
    panels_json_path: Path | None = None,
    project_name: str = "ROOF PROTOTYPE",
    project_address: str = "ADDRESS UNKNOWN",
    estimate_number: str | None = None,
    coverage_in: float = 24.0,
    profile: str = "SV",
    waste_pct: float = 11.0,
    rgb_bytes: bytes | None = None,
    installer_start_edge: str | None = None,
    drawn_by: str | None = None,
) -> dict[str, Path]:
    """Execute the full roof pipeline on pre-loaded data arrays.

    This is the programmatic entry point for the pipeline. The CLI ``main()``
    is a thin wrapper that parses arguments, loads files, and delegates here.
    The FastAPI ``/run-pipeline`` endpoint will also call this function after
    receiving data via HTTP.

    Parameters
    ----------
    dsm : np.ndarray
        Elevation raster (float32, NaN for no-data).
    mask : np.ndarray
        Panel segmentation mask (uint8, 0=background).
    res_m : float
        Spatial resolution in meters per pixel.
    out_dir : Path
        Output directory (created if it does not exist).
    snap_tol : float
        Corner snap tolerance in meters.
    use_snap_v2 : bool
        Use topology-aware snap engine v2 instead of pairwise snap.
    no_clicks : bool
        If True, ignore panels_json_path and extract from mask contours.
    panels_json_path : Path | None
        Path to panels.json (click coordinates). If None or missing, falls
        back to contour extraction from the mask.
    project_name : str
        Project name for shop drawings.
    project_address : str
        Project address for shop drawings.
    estimate_number : str | None
        Estimate number for shop drawings. If None, caller should provide one.
    coverage_in : float
        Panel coverage width in inches for shop drawings.
    profile : str
        Panel profile code for shop drawings.
    waste_pct : float
        Waste percentage for shop drawings.

    Returns
    -------
    dict[str, Path]
        Mapping of output names to file paths:
        ``{"obj", "gltf", "pdf", "json", "ts_pdf", "shop_pdf",
        "features_json" (only when use_snap_v2=True)}``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # NaN-safety: clear mask where DSM has no data so plane fits never see NaN
    mask = np.where(np.isnan(dsm), 0, mask).astype(np.uint8)

    log.info("=== plane fits ===")
    planes = fit_all_panels(dsm, mask, res_m)

    # Prefer the click-coords path -- exactly N vertices, straight edges.
    user_edge_types: dict[int, list[str]] = {}
    panel_run_match: dict[int, int] = {}  # target_pid -> source_pid for run-direction copy
    if panels_json_path is not None and panels_json_path.exists() and not no_clicks:
        log.info("=== boundaries from clicks (%s) ===", panels_json_path.name)
        polygons = polygons_from_clicks(panels_json_path, dsm, res_m, planes)

        # Read user-supplied edge_types out of the same JSON so the shop
        # drawings can prefer the labeler's edge labels over the
        # geometric classifier in roof_dict_from_pipeline. Frontend uses
        # lowercase ("eave", "rake", "ridge", ...); shop_drawings'
        # EDGE_CODE map keys are uppercase ("EAVE", "GABLE", "RIDGE", ...)
        # so we normalize + remap "rake" -> "GABLE" (the renamed display
        # label) and "hip_cap" -> "HIP" here.
        FRONT_TO_SIDECAR = {
            "eave": "EAVE",
            "rake": "GABLE",  # frontend renamed Rake → Gable display
            "ridge": "RIDGE",
            "hip": "HIP",
            "hip_cap": "HIP",  # alias kept for backwards compat
            "valley": "VALLEY",
            "wall": "SIDEWALL",  # closest match in EDGE_CODE
            "transition": "TRANSITION",
            "stucco": "STUCCO",
            "endwall": "ENDWALL",
            "chimney_flashing": "CHIMNEY_FLASHING",
            "high_side": "HIGH_SIDE",
            "flying_gable": "FLYING_GABLE",
        }
        try:
            with open(panels_json_path) as f:
                raw = json.load(f)
            for entry in raw.get("panels", []):
                pid = int(entry.get("id"))
                types = entry.get("edge_types") or []
                if not isinstance(types, list) or not types:
                    continue
                mapped: list[str] = []
                for t in types:
                    if not isinstance(t, str):
                        mapped.append("")
                        continue
                    key = t.lower().strip()
                    if key == "unlabeled" or key == "":
                        mapped.append("")  # falls back to geometric
                    else:
                        mapped.append(FRONT_TO_SIDECAR.get(key, key.upper()))
                user_edge_types[pid] = mapped
                # Per-panel "match my run direction to another panel". Pulled
                # from the same panels.json so a project-level fix can be
                # written once and persisted alongside the labels.
                match = entry.get("match_run_with_panel_id")
                if isinstance(match, int) and match != pid:
                    panel_run_match[pid] = match
            if user_edge_types:
                log.info(
                    "loaded user edge_types for %d panels", len(user_edge_types)
                )
            if panel_run_match:
                log.info(
                    "loaded panel_run_match for %d panels: %s",
                    len(panel_run_match), panel_run_match,
                )
        except Exception as exc:
            log.warning("failed to load edge_types from %s: %s", panels_json_path, exc)
    else:
        log.info("=== boundaries from mask contours (fallback) ===")
        polygons = extract_panel_polygons(mask, dsm, res_m, planes)

    features_path: Path | None = None

    # Preserve the labeler's raw, user-placed corners for the shop-drawings PDF
    # so it renders identically to the frontend Cut Sheet diagram
    # (/api/pipeline/cutsheet-data, which does not run topology snap). The
    # snap engine is still run below to keep the 3D mesh gap-free; it just
    # doesn't get to move the shop-drawings vertices around after the user
    # has already ortho-aligned them in the labeler.
    raw_polygons = {pid: p.copy() for pid, p in polygons.items()}

    if use_snap_v2:
        log.info("=== snap-v2 engine (tol=%.3f m) ===", snap_tol)
        polygons, feature_graph = snap_v2(polygons, planes, tol=snap_tol)

        # Write snap_v2_features.json sidecar (INTG-02)
        features_path = out_dir / "snap_v2_features.json"
        with open(features_path, "w") as f:
            json.dump(feature_graph, f, indent=2, sort_keys=True)
        log.info("wrote snap_v2_features.json: %s", features_path)
    else:
        # Existing v1 snap path (unchanged)
        if panels_json_path is not None and panels_json_path.exists() and not no_clicks:
            # 2D (plan-view) adjacency: two panels are snapped/densified when
            # they overlap in XY regardless of their elevation. Matters for
            # roofs where a low patio abuts a tall main roof.
            log.info("=== corner snapping (XY, tol=%.3f m) ===", snap_tol)
            polygons = snap_shared_corners_xy(polygons, planes, tol=snap_tol)
            log.info("=== edge densification (XY, tol=%.3f m) ===", snap_tol * 0.6)
            polygons = densify_shared_edges_xy(polygons, planes, tol=snap_tol * 0.6)
        else:
            log.info("=== edge snapping (tol=%.3f m) ===", snap_tol)
            polygons = snap_shared_edges(polygons, tol=snap_tol)

    log.info("=== mesh ===")
    mesh = build_roof_mesh(polygons, planes)
    mesh_paths = export_mesh(mesh, out_dir)

    # Cut sheets and TS JSON now render the labeler's raw, user-placed
    # corners instead of the snap-mutated polygons. The labeler produces
    # shared nodes (same vertex shared between adjacent panels), so the
    # snap engine is no longer needed to close gaps in PDF output --
    # running it on already-shared nodes only introduces sub-millimeter
    # drift between what the user drew and what the PDF prints. Shop
    # drawings already used raw_polygons; this brings the other two PDFs
    # into line with that. snap_v2 above is left running so the 3D mesh
    # stays gap-free for any legacy project that doesn't use the
    # shared-node labeler.
    log.info("=== cut sheets (raw labeler polygons) ===")
    pdf_path = write_cutsheets_pdf(
        raw_polygons, planes, mesh, out_dir / "cutsheets.pdf",
        edge_types_by_panel=user_edge_types or None,
    )

    log.info("=== TS exporter JSON (raw labeler polygons) ===")
    json_path = write_ts_json(
        raw_polygons, planes, mesh, out_dir / "cutsheets.ts.json",
    )

    log.info("=== TS-render PDF (mirrors browser output) ===")
    ts_pdf_path = render_pdf_from_json(
        json_path, out_dir / "cutsheets.ts.pdf",
    )

    log.info("=== shop drawings PDF ===")
    project_meta = {
        "estimate_number": estimate_number or "UNKNOWN",
        "project_name": project_name,
        "project_address": project_address,
        # Threaded through to roof_dict_from_pipeline, which prefers
        # these labels over its geometric classifier when present.
        "user_edge_types": user_edge_types or None,
        # Per-panel run-direction match: target_pid -> source_pid.
        "panel_run_match": panel_run_match or None,
        # Title-block "Drawn by" — the project owner's name, resolved by
        # the API layer from auth.users / organizations.
        "drawn_by": drawn_by,
    }
    # Decode RGB ortho if provided. Used by the orthographic-views page
    # to show the actual Google Solar imagery in the AERIAL cell and to
    # color each panel polygon in the top-down 3D plan with the average
    # RGB sampled from the panel's footprint on the ortho.
    rgb_image: np.ndarray | None = None
    if rgb_bytes is not None:
        try:
            with rasterio.open(BytesIO(rgb_bytes)) as src:
                # rasterio reads as (bands, h, w); transpose to (h, w, 3).
                rgb_image = np.moveaxis(src.read(), 0, -1)
                # Trim to 3 channels in case the GeoTIFF includes alpha.
                if rgb_image.shape[-1] > 3:
                    rgb_image = rgb_image[..., :3]
        except Exception as e:
            log.warning("Failed to decode RGB GeoTIFF (%s) — skipping textured 3D views", e)
            rgb_image = None

    roof_dict = roof_dict_from_pipeline(
        raw_polygons, planes, project_meta,
        coverage_width_in=coverage_in,
        waste_pct=waste_pct,
        profile=profile,
        installer_start_edge=installer_start_edge,
    )
    if rgb_image is not None:
        roof_dict["rgb_image"] = rgb_image
        roof_dict["rgb_res_m"] = res_m
    shop_pdf_path = generate_shop_drawings(
        roof_dict, out_dir / "shop_drawings.pdf",
    )

    result: dict[str, Path] = {
        "obj": mesh_paths["obj"],
        "gltf": mesh_paths["gltf"],
        "pdf": pdf_path,
        "json": json_path,
        "ts_pdf": ts_pdf_path,
        "shop_pdf": shop_pdf_path,
    }
    if features_path is not None:
        result["features_json"] = features_path

    log.info("DONE  obj=%s  gltf=%s  pdf=%s  json=%s  ts_pdf=%s  shop_pdf=%s",
             result["obj"], result["gltf"], pdf_path, json_path,
             ts_pdf_path, shop_pdf_path)

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

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
    ap.add_argument("--snap-v2-dryrun", action="store_true",
                    help="print snap-v2 feature graph as JSON and exit")
    ap.add_argument("--snap-v2", action="store_true",
                    help="use topology-aware snap engine v2 instead of pairwise snap")
    args = ap.parse_args()

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

    # CLI-only: snap-v2 dry-run early exit
    if args.snap_v2_dryrun:
        # NaN-safety (same as run_pipeline)
        mask = np.where(np.isnan(dsm), 0, mask).astype(np.uint8)

        log.info("=== snap-v2 dry-run ===")
        planes = fit_all_panels(dsm, mask, res_m)
        # Build polygons from clicks or contours (same as production path)
        panels_json = args.mask.with_suffix(".json")
        if panels_json.exists() and not args.no_clicks:
            polygons = polygons_from_clicks(panels_json, dsm, res_m, planes)
        else:
            polygons = extract_panel_polygons(mask, dsm, res_m, planes)
        graph = build_feature_graph(polygons, planes, tol=args.snap_tol)
        print_dryrun(graph)
        sys.exit(0)

    # Compute panels_json_path for run_pipeline
    panels_json = args.mask.with_suffix(".json")
    panels_json_path: Path | None = None
    if panels_json.exists() and not args.no_clicks:
        panels_json_path = panels_json

    paths = run_pipeline(
        dsm, mask, res_m, args.out_dir,
        snap_tol=args.snap_tol,
        use_snap_v2=args.snap_v2,
        no_clicks=args.no_clicks,
        panels_json_path=panels_json_path,
        project_name=args.project_name,
        project_address=args.project_address,
        estimate_number=args.estimate_number or args.dsm.stem,
        coverage_in=args.coverage_in,
        profile=args.profile,
        waste_pct=args.waste_pct,
    )


if __name__ == "__main__":
    main()
