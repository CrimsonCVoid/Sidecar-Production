#!/usr/bin/env python3
"""Phase 4 data prep: build the edge classifier training CSV from labeled samples.

For every ``training_labels`` row that has at least one labeled
(non-``unlabeled``) edge, this script:

  1. Downloads the matching DSM from Supabase Storage.
  2. Rasterizes the panel polygons onto a uint8 mask (same as the live
     pipeline).
  3. Fits a plane per panel (RANSAC, mirrors ``run_real.run_pipeline``).
  4. Lifts each clicked 2D corner to its plane to get a 3D polygon.
  5. Builds a shared-edge neighbor index across panels.
  6. For each labeled edge, calls
     ``roof_pipeline.edge_classifier.predict._featurize_edge`` and writes
     a CSV row with the same columns the inference path consumes.

Re-uses the live featurizer so train- and inference-time features can
NEVER drift. If the columns ever need to change, change them in
predict.py and this script picks them up via FEATURE_COLUMNS.

Output:
    <out>/edges.csv  — header row of FEATURE_COLUMNS + sample_id,
                       panel_id, edge_index, label

Usage:
    pip install supabase rasterio numpy opencv-python
    export SUPABASE_URL=...
    export SUPABASE_SERVICE_ROLE_KEY=...
    python3 scripts/build_edge_training_set.py --out data/edge_training/edges.csv

Resumable: skips samples whose rows are already in the CSV (matched by
sample_id). Rerun after labeling more projects to grow the set.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from io import BytesIO
from pathlib import Path

LOG = logging.getLogger("edge_classifier.build_dataset")

# ---------------------------------------------------------------------------
# Constants — keep in sync with edge_classifier/predict.py + train.py.
# These are imported at runtime from predict.py to avoid drift.
# ---------------------------------------------------------------------------
META_COLUMNS = ["sample_id", "panel_id", "edge_index"]
LABEL_COLUMN = "label"

# Edge type aliases tolerate older labeler vocabularies (capturer
# data, legacy projects). Output column matches LABEL_CLASSES from
# the trainer so downstream filtering stays simple.
LABEL_NORMALIZE = {
    "EAVE": "eave",
    "RAKE": "rake",
    "GABLE": "rake",  # labeler-store: rake.label = "Gable"
    "RIDGE": "ridge",
    "HIP": "hip",
    "VALLEY": "valley",
    "HIP_CAP": "hip_cap",
    "WALL": "wall",
    "SIDEWALL": "wall",  # 2026-05 codes — collapse to legacy wall class
    "ENDWALL": "wall",
}
SKIP_LABELS = {"", "UNLABELED", "TRANSITION", "HIGH_SIDE",
               "FLYING_GABLE", "CHIMNEY_FLASHING"}


def _supabase_client():
    url = os.environ.get("SUPABASE_URL") or os.environ.get(
        "NEXT_PUBLIC_SUPABASE_URL"
    )
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error(
            "SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY required "
            "(populate from /opt/mmr-api/app/.env)."
        )
        sys.exit(2)
    from supabase import create_client

    return create_client(url, key)


def _download(sb, path: str) -> bytes | None:
    if not path:
        return None
    for bucket in ("training-data", "pipeline-outputs"):
        try:
            return sb.storage.from_(bucket).download(path)
        except Exception:
            continue
    return None


def _normalize_label(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().upper()
    if key in SKIP_LABELS:
        return None
    return LABEL_NORMALIZE.get(key)


def _processed_sample_ids(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    seen: set[str] = set()
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sid = row.get("sample_id")
            if sid:
                seen.add(sid)
    return seen


def _process_sample(sb, sample_id: str, panels: list[dict]):
    """Yield CSV rows for every labeled edge in the sample.

    Returns a list of dict rows. Empty list when the sample has no DSM,
    no labeled edges, or any pipeline step fails — in which case a
    warning is logged and the caller continues with the next sample.
    """
    import cv2
    import numpy as np
    import rasterio

    # Local imports keep the main module light when supabase deps aren't
    # installed yet — the script's first job is to install/check them.
    from roof_pipeline.planes import fit_all_panels
    from roof_pipeline.boundaries import polygons_from_clicks
    from roof_pipeline.cutsheets import (
        polygon_area_2d,
        rotation_to_horizontal,
        slope_rise_over_12,
    )
    from roof_pipeline.edge_classifier.predict import (
        FEATURE_COLUMNS,
        _build_neighbor_index,
        _featurize_edge,
    )

    M_TO_FT = 3.280839895
    SQM_TO_SQFT = 10.7639

    sample_row = (
        sb.table("training_samples")
        .select("dsm_storage_path, meters_per_px, width_px, height_px")
        .eq("id", sample_id)
        .execute()
    )
    if not sample_row.data:
        LOG.info("  skip %s: no training_samples row", sample_id[:8])
        return []
    sample = sample_row.data[0]
    dsm_path = sample.get("dsm_storage_path") or ""
    res_m = float(sample.get("meters_per_px") or 0.1)

    dsm_bytes = _download(sb, dsm_path)
    if dsm_bytes is None:
        LOG.info("  skip %s: no DSM", sample_id[:8])
        return []

    try:
        with rasterio.open(BytesIO(dsm_bytes)) as ds:
            dsm = ds.read(1).astype("float32")
    except Exception as exc:
        LOG.warning("  dsm decode failed for %s: %s", sample_id[:8], exc)
        return []

    h, w = dsm.shape

    # Rasterize panel polygons onto a per-panel-id mask. Match the
    # numbering scheme in pipeline.py (1-indexed, 0 = background).
    mask = np.zeros((h, w), dtype="uint8")
    panels_json: list[dict] = []
    panel_edge_types: dict[int, list[str]] = {}
    for i, p in enumerate(panels):
        pid = i + 1
        corners = p.get("corners_pix") or []
        if len(corners) < 3:
            continue
        pts = np.asarray(corners, dtype=np.int32)
        cv2.fillPoly(mask, [pts], pid)
        # The clicked corners get re-passed to polygons_from_clicks; it
        # consumes a JSON file so we materialize an in-memory dict here.
        panels_json.append({**p, "id": pid})
        et = p.get("edge_types") or []
        panel_edge_types[pid] = [str(t) if t else "" for t in et]

    if not panels_json:
        return []

    # plane fits per panel — fit_all_panels iterates panel ids in the
    # mask, builds (N, 3) point clouds, and runs RANSAC on each.
    try:
        planes = fit_all_panels(dsm, mask, res_m)
    except Exception as exc:
        LOG.warning("  plane fit failed for %s: %s", sample_id[:8], exc)
        return []
    if not planes:
        return []

    # Lift clicks to plane-projected 3D polygons. polygons_from_clicks
    # accepts an in-memory dict via a temp file path — write to a
    # NamedTemporaryFile so we don't touch the user's filesystem.
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
    ) as tf:
        json.dump({"panels": panels_json}, tf)
        tf_path = Path(tf.name)
    try:
        try:
            polygons_3d = polygons_from_clicks(tf_path, dsm, res_m, planes)
        except Exception as exc:
            LOG.warning("  polygon lift failed for %s: %s", sample_id[:8], exc)
            return []
    finally:
        try:
            tf_path.unlink()
        except OSError:
            pass

    neighbor_index = _build_neighbor_index(polygons_3d, planes)

    rows: list[dict] = []
    for pid, poly3d in polygons_3d.items():
        plane = planes.get(pid)
        if plane is None:
            continue

        # Per-panel derived stats (match _featurize_edge's expected args)
        R = rotation_to_horizontal(plane.normal)
        verts_rot_xy = (poly3d @ R.T)[:, :2]
        area_m2 = polygon_area_2d(verts_rot_xy)
        area_sqft = float(area_m2 * SQM_TO_SQFT)
        z_min = float(np.min(poly3d[:, 2]))
        z_max = float(np.max(poly3d[:, 2]))
        rise = float(slope_rise_over_12(plane.normal))

        edge_types = panel_edge_types.get(pid, [])
        n = poly3d.shape[0]
        if len(edge_types) != n:
            # Old labels without per-edge types — skip rather than guess.
            continue

        for i in range(n):
            label = _normalize_label(edge_types[i])
            if not label:
                continue
            features = _featurize_edge(
                poly=poly3d,
                edge_index=i,
                plane_normal=np.asarray(plane.normal),
                plane_slope_rise=rise,
                panel_z_min=z_min,
                panel_z_max=z_max,
                panel_area_sqft=area_sqft,
                neighbor_index=neighbor_index,
                pid=pid,
                planes=planes,
            )
            row = dict(zip(FEATURE_COLUMNS, features))
            row["sample_id"] = sample_id
            row["panel_id"] = pid
            row["edge_index"] = i
            row["label"] = label
            rows.append(row)

    return rows


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output CSV path (parents created if missing)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max samples to process (0 = all). Useful for smoke tests.",
    )
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sb = _supabase_client()

    # Pull the FEATURE_COLUMNS list at runtime so this script and the
    # trainer never disagree on column order.
    from roof_pipeline.edge_classifier.predict import FEATURE_COLUMNS

    columns = META_COLUMNS + list(FEATURE_COLUMNS) + [LABEL_COLUMN]
    seen = _processed_sample_ids(args.out)
    if seen:
        LOG.info("Resumable: %d sample_ids already in %s", len(seen), args.out)

    label_rows = (
        sb.table("training_labels")
        .select("sample_id, annotations")
        .execute()
    )
    sample_ids: list[tuple[str, list[dict]]] = []
    for r in (label_rows.data or []):
        sid = r.get("sample_id")
        if not sid or sid in seen:
            continue
        ann = r.get("annotations") or {}
        panels = ann.get("panels") or []
        if not panels:
            continue
        # Quick filter — at least one labeled edge across the sample
        any_labeled = False
        for p in panels:
            for t in (p.get("edge_types") or []):
                if _normalize_label(t):
                    any_labeled = True
                    break
            if any_labeled:
                break
        if not any_labeled:
            continue
        sample_ids.append((sid, panels))

    if args.limit > 0:
        sample_ids = sample_ids[: args.limit]
    LOG.info("Will process %d sample_id(s)", len(sample_ids))

    # Open in append mode if the file already exists and matches schema.
    write_header = not args.out.exists() or args.out.stat().st_size == 0
    fh = args.out.open("a", newline="")
    writer = csv.DictWriter(fh, fieldnames=columns)
    if write_header:
        writer.writeheader()

    total_rows = 0
    total_samples_with_rows = 0
    try:
        for sid, panels in sample_ids:
            try:
                rows = _process_sample(sb, sid, panels)
            except Exception as exc:
                LOG.warning("  unhandled error for %s: %s", sid[:8], exc)
                rows = []
            if not rows:
                continue
            for row in rows:
                writer.writerow(row)
            total_rows += len(rows)
            total_samples_with_rows += 1
            LOG.info(
                "  ok   %s — %d edges (running total: %d rows / %d samples)",
                sid[:8], len(rows), total_rows, total_samples_with_rows,
            )
    finally:
        fh.close()

    LOG.info(
        "Done. Wrote %d new edge rows from %d sample(s) into %s",
        total_rows, total_samples_with_rows, args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
