#!/usr/bin/env python3
"""Phase 5 data prep: build the MSGP training set from labeled samples.

Pulls every `training_labels` row with non-empty `annotations.panels`,
downloads matching RGB + DSM from Supabase Storage, rasterizes the
panel polygons onto a binary mask, and writes a (4, H, W) input tensor
+ (H, W) mask as paired .npy files. Output layout matches what
roof_pipeline.msgp.train + evaluate consume.

Output:
    <out>/<sample_id>.input.npy   float32 (4, H, W)
        channels: R, G, B (each in [0, 1]), DSM-normalized to mean 0, std 1
    <out>/<sample_id>.mask.npy    uint8   (H, W)   binary roof-panel mask

Usage:
    pip install supabase rasterio Pillow numpy
    export SUPABASE_URL=https://psdyxmxledojrqvzmdek.supabase.co
    export SUPABASE_SERVICE_ROLE_KEY=...
    python3 scripts/msgp_prepare_data.py --out data/msgp/all
    python3 scripts/msgp_prepare_data.py --out data/msgp/holdout --limit 20

Splits: pass `--out data/msgp/train` and `--out data/msgp/val` in
separate runs with disjoint `--exclude-sample-ids` to materialize a
deterministic train/val split. The training loader's hash-based
fallback also works if you'd rather not partition by hand.

Resumable: skips samples whose .input.npy already exists. Run again
after labeling more projects to grow the dataset incrementally.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from io import BytesIO
from pathlib import Path

LOG = logging.getLogger("msgp.prepare_data")


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


def _rasterize_mask(panels: list[dict], h: int, w: int):
    """Fill polygon interiors using cv2.fillPoly. Returns uint8 (H, W)."""
    import cv2
    import numpy as np

    mask = np.zeros((h, w), dtype="uint8")
    for panel in panels:
        corners = panel.get("corners_pix") or []
        if len(corners) < 3:
            continue
        pts = np.asarray(corners, dtype=np.int32)
        cv2.fillPoly(mask, [pts], 1)
    return mask


def _build_input(rgb_arr, dsm_arr):
    """RGB float32 in [0, 1] + DSM normalized to (mean 0, std 1) →
    stacked (4, H, W). Matches the channel order MSGPSegmenter expects."""
    import numpy as np

    rgb_f = rgb_arr.astype("float32") / 255.0
    if rgb_f.ndim == 3 and rgb_f.shape[-1] == 3:
        rgb_f = rgb_f.transpose(2, 0, 1)  # HWC -> CHW
    if rgb_f.shape[0] != 3:
        raise ValueError(f"Unexpected RGB shape {rgb_f.shape}")
    dsm_f = dsm_arr.astype("float32")
    mean = float(dsm_f.mean()) if dsm_f.size else 0.0
    std = float(dsm_f.std()) if dsm_f.size else 1.0
    if std < 1e-6:
        std = 1.0
    dsm_norm = (dsm_f - mean) / std
    return np.concatenate([rgb_f, dsm_norm[None, ...]], axis=0)


def _process_sample(sb, sample_id: str, out_dir: Path) -> str:
    """Returns one of: 'ok', 'skipped:no_panels', 'skipped:no_dsm',
    'skipped:no_rgb', 'skipped:exists', 'error'."""
    import numpy as np
    import rasterio
    from PIL import Image

    target_input = out_dir / f"{sample_id}.input.npy"
    target_mask = out_dir / f"{sample_id}.mask.npy"
    if target_input.exists() and target_mask.exists():
        return "skipped:exists"

    label_row = (
        sb.table("training_labels")
        .select("annotations")
        .eq("sample_id", sample_id)
        .execute()
    )
    if not label_row.data:
        return "skipped:no_panels"
    panels = (label_row.data[0].get("annotations") or {}).get("panels", [])
    if not panels:
        return "skipped:no_panels"

    sample_row = (
        sb.table("training_samples")
        .select("rgb_storage_path, dsm_storage_path, width_px, height_px")
        .eq("id", sample_id)
        .execute()
    )
    if not sample_row.data:
        return "skipped:no_panels"
    sample = sample_row.data[0]

    rgb_bytes = _download(sb, sample.get("rgb_storage_path") or "")
    if rgb_bytes is None:
        return "skipped:no_rgb"
    dsm_bytes = _download(sb, sample.get("dsm_storage_path") or "")
    if dsm_bytes is None:
        return "skipped:no_dsm"

    try:
        rgb = np.asarray(Image.open(BytesIO(rgb_bytes)).convert("RGB"))
    except Exception as exc:
        LOG.warning("rgb decode failed for %s: %s", sample_id, exc)
        return "error"
    try:
        with rasterio.open(BytesIO(dsm_bytes)) as ds:
            dsm = ds.read(1).astype("float32")
    except Exception as exc:
        LOG.warning("dsm decode failed for %s: %s", sample_id, exc)
        return "error"

    h, w = rgb.shape[:2]
    if dsm.shape != (h, w):
        # Resize DSM to RGB dims with nearest-neighbour. Real prod
        # data usually matches; this is a fallback so we don't drop
        # samples on a 1-pixel mismatch.
        try:
            from PIL import Image as PIL

            dsm_img = PIL.fromarray(dsm)
            dsm = np.asarray(dsm_img.resize((w, h), PIL.NEAREST), dtype="float32")
        except Exception as exc:
            LOG.warning("dsm resize failed for %s: %s", sample_id, exc)
            return "error"

    inp = _build_input(rgb, dsm)
    mask = _rasterize_mask(panels, h, w)
    np.save(target_input, inp)
    np.save(target_mask, mask)
    return "ok"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True, help="Output dir")
    ap.add_argument(
        "--limit", type=int, default=0, help="Max samples (0 = all)"
    )
    ap.add_argument(
        "--exclude-sample-ids",
        type=Path,
        default=None,
        help="Optional file with one sample_id per line to skip — "
             "useful for materializing a holdout split disjoint from "
             "an earlier train run.",
    )
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    sb = _supabase_client()

    excluded: set[str] = set()
    if args.exclude_sample_ids and args.exclude_sample_ids.exists():
        excluded = {
            line.strip()
            for line in args.exclude_sample_ids.read_text().splitlines()
            if line.strip()
        }
        LOG.info("Excluding %d sample_ids from --exclude-sample-ids", len(excluded))

    rows = (
        sb.table("training_labels")
        .select("sample_id")
        .execute()
    )
    sample_ids = [r["sample_id"] for r in (rows.data or []) if r.get("sample_id")]
    sample_ids = [sid for sid in sample_ids if sid not in excluded]
    if args.limit > 0:
        sample_ids = sample_ids[: args.limit]
    LOG.info("Processing %d sample_ids", len(sample_ids))

    counts: dict[str, int] = {}
    for sid in sample_ids:
        try:
            outcome = _process_sample(sb, sid, args.out)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("unhandled error for %s: %s", sid, exc)
            outcome = "error"
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome == "ok":
            LOG.info("  ok      %s", sid)
        elif outcome == "skipped:exists":
            pass  # quiet on resumable skips
        else:
            LOG.info("  %-7s %s", outcome.split(":")[-1], sid)

    LOG.info("Done. Outcomes: %s", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
