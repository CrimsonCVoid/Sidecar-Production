"""MSGP evaluation.

Runs a trained MSGPSegmenter checkpoint on a held-out directory and
prints pixel IoU, pixel F1, boundary F1, and per-sample latency.
Same metrics format we'll use to evaluate SAM, so the two are
apples-to-apples on Phase 5's acceptance criterion.

Held-out directory layout (matches the data-prep script's output):
    <data_dir>/
        <sample_id>.input.npy   # float32 (4, H, W)  RGB[0..1] + normalized DSM
        <sample_id>.mask.npy    # uint8   (H, W)     binary roof-panel mask

Usage:
    python3 -m roof_pipeline.msgp.evaluate \\
        --checkpoint runs/finetune/last.ckpt \\
        --data data/msgp_holdout \\
        --threshold 0.5 \\
        > eval_results.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

LOG = logging.getLogger("msgp.evaluate")


def _load_pair(input_path: Path):
    import numpy as np

    inp = np.load(input_path).astype("float32")
    mask = np.load(str(input_path).replace(".input.npy", ".mask.npy"))
    if mask.ndim == 3:
        mask = mask[0]
    return inp, mask.astype("uint8")


def _binary_metrics(pred: "np.ndarray", gt: "np.ndarray") -> dict:
    """Pixel-level IoU + precision/recall/F1 for a single binary mask
    pair. Both inputs are uint8 (0/1) of the same shape."""
    pred_b = pred.astype(bool)
    gt_b = gt.astype(bool)
    inter = int((pred_b & gt_b).sum())
    union = int((pred_b | gt_b).sum())
    pred_pos = int(pred_b.sum())
    gt_pos = int(gt_b.sum())
    iou = inter / union if union > 0 else 1.0
    precision = inter / pred_pos if pred_pos > 0 else 1.0
    recall = inter / gt_pos if gt_pos > 0 else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "iou": iou,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "pixels_pred": pred_pos,
        "pixels_gt": gt_pos,
    }


def _boundary_f1(
    pred: "np.ndarray", gt: "np.ndarray", radius_px: int = 2
) -> float:
    """Boundary F1 score with a `radius_px` tolerance. A pred-boundary
    pixel counts as a TP if any GT-boundary pixel sits within radius_px;
    likewise a GT-boundary counts as recovered if any pred-boundary
    sits within radius_px. Cheap, no scipy dependency — uses a simple
    max-pool dilation."""
    import numpy as np

    def edges(m: np.ndarray) -> np.ndarray:
        m = m.astype(bool)
        # 4-connected boundary: any pixel that's interior but has a
        # zero neighbour. Faster than a real edge filter, fine for
        # the dilation test below.
        b = np.zeros_like(m)
        b[1:, :] |= m[1:, :] & ~m[:-1, :]
        b[:-1, :] |= m[:-1, :] & ~m[1:, :]
        b[:, 1:] |= m[:, 1:] & ~m[:, :-1]
        b[:, :-1] |= m[:, :-1] & ~m[:, 1:]
        return b

    def dilate(b: np.ndarray, r: int) -> np.ndarray:
        out = b.copy()
        for _ in range(r):
            shifted = np.zeros_like(out)
            shifted[1:, :] |= out[:-1, :]
            shifted[:-1, :] |= out[1:, :]
            shifted[:, 1:] |= out[:, :-1]
            shifted[:, :-1] |= out[:, 1:]
            out |= shifted
        return out

    pred_b = edges(pred)
    gt_b = edges(gt)
    if pred_b.sum() == 0 and gt_b.sum() == 0:
        return 1.0
    if pred_b.sum() == 0 or gt_b.sum() == 0:
        return 0.0
    pred_d = dilate(pred_b, radius_px)
    gt_d = dilate(gt_b, radius_px)
    tp_p = int((pred_b & gt_d).sum())
    tp_r = int((gt_b & pred_d).sum())
    precision = tp_p / int(pred_b.sum())
    recall = tp_r / int(gt_b.sum())
    return (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Held-out sample directory (see module docstring for layout)",
    )
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument(
        "--boundary-radius",
        type=int,
        default=2,
        help="Boundary-F1 dilation radius in pixels",
    )
    ap.add_argument(
        "--device", default="auto", help="cpu, cuda, or auto (default)"
    )
    args = ap.parse_args()

    try:
        import numpy as np
        import torch
    except ImportError as exc:
        LOG.error("Missing deps. `pip install torch numpy`. (%s)", exc)
        return 2

    from .model import MSGPSegmenter

    device = (
        args.device
        if args.device != "auto"
        else ("cuda" if torch.cuda.is_available() else "cpu")
    )

    model = MSGPSegmenter()
    state = torch.load(args.checkpoint, map_location=device)
    if "state_dict" in state:
        prefix = "net."
        clean = {
            k[len(prefix):]: v
            for k, v in state["state_dict"].items()
            if k.startswith(prefix)
        }
        model.load_state_dict(clean)
    else:
        model.load_state_dict(state)
    model.to(device).eval()

    samples = sorted(args.data.glob("*.input.npy"))
    if not samples:
        LOG.error("No samples found under %s (looking for *.input.npy)", args.data)
        return 2
    LOG.info("Evaluating %d samples on device=%s", len(samples), device)

    per_sample = []
    sigmoid = torch.nn.Sigmoid()
    with torch.no_grad():
        for path in samples:
            inp, gt = _load_pair(path)
            x = torch.from_numpy(inp).unsqueeze(0).to(device)
            t0 = time.perf_counter()
            logits = model(x)
            probs = sigmoid(logits)[0, 0].cpu().numpy()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            pred = (probs >= args.threshold).astype("uint8")
            metrics = _binary_metrics(pred, gt)
            metrics["boundary_f1"] = _boundary_f1(pred, gt, args.boundary_radius)
            metrics["latency_ms"] = round(elapsed_ms, 2)
            metrics["sample"] = path.stem.replace(".input", "")
            per_sample.append(metrics)
            LOG.info(
                "  %s  IoU=%.3f  F1=%.3f  bF1=%.3f  %.1fms",
                metrics["sample"],
                metrics["iou"],
                metrics["f1"],
                metrics["boundary_f1"],
                metrics["latency_ms"],
            )

    def _avg(key: str) -> float:
        return sum(s[key] for s in per_sample) / len(per_sample)

    summary = {
        "n_samples": len(per_sample),
        "mean_iou": round(_avg("iou"), 4),
        "mean_f1": round(_avg("f1"), 4),
        "mean_precision": round(_avg("precision"), 4),
        "mean_recall": round(_avg("recall"), 4),
        "mean_boundary_f1": round(_avg("boundary_f1"), 4),
        "mean_latency_ms": round(_avg("latency_ms"), 2),
        "threshold": args.threshold,
        "boundary_radius_px": args.boundary_radius,
        "device": device,
    }
    print(json.dumps({"summary": summary, "per_sample": per_sample}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
