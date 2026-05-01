#!/usr/bin/env python3
"""Rule-vs-classifier edge-label diff for the Phase 4 model.

Validation tool, run after a training pass. Loads polygons + planes
from the live pipeline for a benchmark sample, runs both the rule-
based `_classify_panel_edges` and the trained `predict_edges`, and
prints a per-edge side-by-side. Use it to answer:

    "Does my newly-trained classifier agree with the rule on simple
     cases (eaves on a clean gable) and disagree productively on
     hard cases (hips and valleys on the complex sample)?"

Usage:
    # 1. Train as usual:
    python3 -m roof_pipeline.edge_classifier.train \
        --data ../WebsiteDesign-MMR/data/edge_training/edges.csv \
        --out roof_pipeline/edge_classifier/artifacts \
        --folds 5

    # 2. Run the diff against a benchmark sample:
    EDGE_CLASSIFIER_MODEL_DIR=$PWD/roof_pipeline/edge_classifier/artifacts \
    DATABASE_URL=postgres://... \
    python3 scripts/edge_classifier_diff.py 99572f04-68ef-4ad5-8394-864b7b55d177

The classifier runs regardless of EDGE_CLASSIFIER_ENABLED — this
script forces it on. Production behavior is unchanged.

Requires: xgboost, supabase, rasterio, scipy (already in the sidecar
venv's requirements.txt).
"""

from __future__ import annotations

import argparse
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np

# Make sure we can import roof_pipeline when run from the sidecar root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _force_load_classifier() -> bool:
    """Load the model regardless of EDGE_CLASSIFIER_ENABLED. Returns
    True on success — the diff only makes sense if the model loaded."""
    from roof_pipeline.edge_classifier import load_model
    from roof_pipeline.edge_classifier import predict as predict_mod

    if not load_model():
        print(
            "ERROR: edge classifier failed to load. Verify "
            "EDGE_CLASSIFIER_MODEL_DIR points at a directory that "
            "contains model.json + label_encoder.json, and that "
            "xgboost is installed.",
            file=sys.stderr,
        )
        return False
    # Bypass the env-flag gate for this run.
    predict_mod._load_succeeded = True  # type: ignore[attr-defined]
    return True


def _supabase_client():
    url = os.environ.get("SUPABASE_URL") or os.environ.get(
        "NEXT_PUBLIC_SUPABASE_URL"
    )
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print(
            "ERROR: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY must be set "
            "(populate from /opt/mmr-api/app/.env on the sidecar host).",
            file=sys.stderr,
        )
        sys.exit(2)
    from supabase import create_client

    return create_client(url, key)


def _build_polygons_and_planes(sample_id: str) -> tuple[
    dict[int, np.ndarray], dict[int, Any], float, float
]:
    """Replays the polygon → plane-fit half of cutsheet-data so we
    don't have to expose it as an endpoint. Returns
    (polygons, planes, z_min, z_max) where polygons[id] is an (N, 3)
    ndarray in meters (xyz). Roughly mirrors api/pipeline.py:808."""
    import rasterio

    from roof_pipeline.boundaries import polygons_from_clicks
    from roof_pipeline.planes import Plane, fit_plane

    sb = _supabase_client()

    labels = (
        sb.table("training_labels")
        .select("annotations")
        .eq("sample_id", sample_id)
        .execute()
    )
    if not labels.data:
        print(f"ERROR: no labels found for {sample_id}", file=sys.stderr)
        sys.exit(2)
    panels_raw = (labels.data[0].get("annotations") or {}).get("panels", [])
    if not panels_raw:
        print(f"ERROR: labels for {sample_id} have no panels", file=sys.stderr)
        sys.exit(2)

    sample = (
        sb.table("training_samples")
        .select(
            "dsm_storage_path, meters_per_px, width_px, height_px"
        )
        .eq("id", sample_id)
        .execute()
    )
    if not sample.data:
        print(f"ERROR: sample {sample_id} not found", file=sys.stderr)
        sys.exit(2)
    dsm_path = sample.data[0].get("dsm_storage_path")
    if not dsm_path:
        print(f"ERROR: sample {sample_id} has no DSM", file=sys.stderr)
        sys.exit(2)

    dsm_bytes: bytes | None = None
    for bucket in ("training-data", "pipeline-outputs"):
        try:
            dsm_bytes = sb.storage.from_(bucket).download(dsm_path)
            break
        except Exception:
            continue
    if dsm_bytes is None:
        print(f"ERROR: could not download DSM at {dsm_path}", file=sys.stderr)
        sys.exit(2)

    with rasterio.open(BytesIO(dsm_bytes)) as ds:
        dsm_arr = ds.read(1).astype(np.float64)
        res_m = abs(ds.res[0]) if ds.res else float(
            sample.data[0].get("meters_per_px") or 0.25
        )

    polys_3d = polygons_from_clicks(panels_raw, dsm_arr, res_m)
    planes_by_id: dict[int, Plane] = {}
    z_values: list[float] = []
    for pid, poly in polys_3d.items():
        planes_by_id[pid] = fit_plane(poly)
        z_values.extend(poly[:, 2].tolist())
    z_min = float(min(z_values)) if z_values else 0.0
    z_max = float(max(z_values)) if z_values else 0.0
    return polys_3d, planes_by_id, z_min, z_max


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sample_id", help="UUID of a training_samples row")
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Classifier confidence floor (matches predict_edges default)",
    )
    args = ap.parse_args()

    if not _force_load_classifier():
        return 1

    from roof_pipeline.edge_classifier import predict_edges
    from roof_pipeline.shop_drawings import _classify_panel_edges

    polygons, planes, z_min, z_max = _build_polygons_and_planes(args.sample_id)

    print(f"\nSample {args.sample_id}")
    print(f"  panels: {len(polygons)}, z range: [{z_min:.2f}, {z_max:.2f}]")

    total = 0
    agreements = 0
    low_conf = 0
    for pid in sorted(polygons.keys()):
        poly = polygons[pid]
        plane = planes[pid]
        others = [polygons[o] for o in polygons if o != pid]
        rule = _classify_panel_edges(poly, others, z_min, z_max)
        clf = predict_edges(
            pid, poly, plane, polygons, planes,
            confidence_threshold=args.threshold,
        )
        print(f"\n  Panel {pid} ({poly.shape[0]} edges)")
        print(f"  {'edge':<5}  {'rule':<8}  {'classifier':<22}  match")
        n = poly.shape[0]
        if clf is None:
            print("    (classifier returned None — see logs)")
            continue
        for i in range(n):
            r = rule[i]
            label, conf = clf[i]
            label_disp = label or "(low conf)"
            shown_clf = f"{label_disp.upper():<8} {conf:.3f}"
            ok = label.upper() == r if label else None
            marker = "✓" if ok else ("·" if ok is None else "✗")
            print(f"    {i:<5}  {r:<8}  {shown_clf:<22}  {marker}")
            total += 1
            if ok:
                agreements += 1
            if not label:
                low_conf += 1

    print(f"\nSummary: {agreements}/{total} agree  ({low_conf} below threshold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
