#!/usr/bin/env python3
"""Audit: do polygon edges and DSM gradients live in the same coordinate frame?

For every labeled face in production, compute:
  - The bearing (mod π) of the longest polygon edge in plan view
  - The bearing (mod π) of the DSM gradient direction at the face centroid

On a tilted roof face, the gradient points down-slope, which is
*perpendicular* to the eave/ridge, which usually IS the longest edge.
So the two bearings should be roughly perpendicular: |bearing_diff - 90°|
should center near zero with noise on top.

If the median |diff - 90°| is near zero → coord frame is consistent.
If it's near 90° → polygon and DSM disagree by a 90° rotation, i.e.
there's a CRS bug (rows-vs-cols swap, axis sign flip, or similar).

Read-only: hits Supabase REST API + Storage. No DB writes.

Usage:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
      python3 scripts/audit_polygon_dsm_alignment.py [--limit N]

Prints a histogram of angular offsets and a verdict.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
from pathlib import Path

import numpy as np
import rasterio
from supabase import create_client


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def longest_edge_bearing_mod_pi(polygon_xy: np.ndarray) -> float | None:
    if polygon_xy.shape[0] < 2:
        return None
    best_len = 0.0
    best_bearing = None
    for i in range(polygon_xy.shape[0]):
        a = polygon_xy[i]
        b = polygon_xy[(i + 1) % polygon_xy.shape[0]]
        dx, dy = float(b[0] - a[0]), float(b[1] - a[1])
        L = math.hypot(dx, dy)
        if L > best_len:
            best_len = L
            best_bearing = math.atan2(dy, dx) % math.pi
    return best_bearing


def gradient_bearing_mod_pi(dsm: np.ndarray, col: float, row: float) -> float | None:
    h, w = dsm.shape
    c = max(1, min(w - 2, int(round(col))))
    r = max(1, min(h - 2, int(round(row))))
    # Central differences
    dz_dx = float(dsm[r, c + 1] - dsm[r, c - 1])
    dz_dy = float(dsm[r + 1, c] - dsm[r - 1, c])
    if abs(dz_dx) < 1e-9 and abs(dz_dy) < 1e-9:
        return None
    # Down-slope direction in pixel space — ignore sign for bearing-mod-π
    # comparison.
    return math.atan2(dz_dy, dz_dx) % math.pi


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=200,
                   help="Max number of faces to sample")
    args = p.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 2
    sb = create_client(url, key)

    labels = (
        sb.table("training_labels")
        .select("sample_id, annotations, status")
        .eq("status", "complete")
        .execute()
        .data
    )
    diffs: list[float] = []  # absolute |bearing_diff - 90°| in degrees
    examined = 0

    for lbl in labels:
        if examined >= args.limit:
            break
        sid = lbl["sample_id"]
        panels = (lbl.get("annotations") or {}).get("panels") or []
        if not panels:
            continue

        sr = (
            sb.table("training_samples")
            .select("dsm_storage_path")
            .eq("id", sid)
            .execute()
            .data
        )
        if not sr or not sr[0].get("dsm_storage_path"):
            continue
        try:
            dsm_bytes = None
            for bucket in ["pipeline-outputs", "training-data", "training-samples"]:
                try:
                    dsm_bytes = sb.storage.from_(bucket).download(sr[0]["dsm_storage_path"])
                    if dsm_bytes:
                        break
                except Exception:
                    continue
            if not dsm_bytes:
                continue
            with rasterio.open(io.BytesIO(dsm_bytes)) as ds:
                dsm = ds.read(1).astype(np.float64)
        except Exception:
            continue

        for panel in panels:
            corners = panel.get("corners_pix") or []
            if len(corners) < 3:
                continue
            poly = np.asarray(corners, dtype=float)
            edge_b = longest_edge_bearing_mod_pi(poly)
            if edge_b is None:
                continue
            cen = poly.mean(axis=0)
            grad_b = gradient_bearing_mod_pi(dsm, cen[0], cen[1])
            if grad_b is None:
                continue
            # Acute angle between the two lines, in degrees, in [0, 90]
            d = abs(edge_b - grad_b) % math.pi
            d_deg = math.degrees(min(d, math.pi - d))
            # Distance from "perpendicular" (90°). On a tilted face the
            # longest edge IS usually the eave/ridge so we expect the
            # gradient to be ~perpendicular → diff close to 90°.
            diffs.append(abs(d_deg - 90.0))
            examined += 1
            if examined >= args.limit:
                break

    if not diffs:
        print("no usable faces sampled — nothing to report")
        return 1

    arr = np.array(diffs)
    print(f"sampled {len(arr)} faces")
    print(f"  median |diff - 90°|: {np.median(arr):6.2f}°")
    print(f"  mean   |diff - 90°|: {np.mean(arr):6.2f}°")
    print(f"  p95    |diff - 90°|: {np.percentile(arr, 95):6.2f}°")
    # Histogram in 10-degree bins
    bins = list(range(0, 95, 10))
    hist, _ = np.histogram(arr, bins=bins + [180])
    print()
    print("Histogram (deg):")
    for lo, count in zip(bins, hist):
        bar = "#" * int(50 * count / max(hist.sum(), 1))
        print(f"  {lo:>3}–{lo+10:<3}: {count:4d}  {bar}")
    print()
    median = float(np.median(arr))
    if median < 15.0:
        print("VERDICT: polygons and DSM share a coordinate frame (median offset "
              f"{median:.1f}° from 90°-expectation, well within roof-pitch noise).")
    elif 75.0 < median < 105.0:
        print("VERDICT: 90° rotation between polygons and DSM. Likely a CRS bug "
              "(rows/cols swapped or an axis sign flipped). Investigate "
              "boundaries.polygons_from_clicks coordinate convention.")
    else:
        print(f"VERDICT: ambiguous — median offset {median:.1f}° is neither aligned "
              "(<15°) nor a 90°-flip. Could be heavy roof-pitch variation, lots of "
              "low-slope faces, or a partial CRS bug. Re-run with --limit higher.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
