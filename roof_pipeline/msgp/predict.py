"""MSGP inference path — checkpoint loader + polygon vectorizer.

Wraps the trained MSGPSegmenter for live inference:
  1. Lazy-load the Lightning checkpoint into a plain MSGPSegmenter
     (Lightning's ``_Lit`` wrapper is unwrapped via the ``net.`` prefix).
  2. Run RGB+DSM tensors through the model at 256×256 to match training,
     scale results back up to original imagery dimensions.
  3. Vectorize the binary mask into polygons via OpenCV's contour finder
     and Ramer-Douglas-Peucker simplification — same approach as the
     existing rule-based polygonization, so downstream consumers don't
     care which path produced the polygon list.

Output shape mirrors what the labeler stores in ``training_labels.
annotations.panels[].corners_pix``: a list of polygons, each polygon
is a list of (x, y) integer pixel coordinates. The labeler can drop
this directly into its Zustand store and render.

Gated behind ``MSGP_AUTO_SEGMENT_ENABLED`` so the model file doesn't
get probed on every cold start. Health endpoint reports whether the
checkpoint loaded successfully.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


_DEFAULT_CKPT = Path(
    os.environ.get(
        "MSGP_CHECKPOINT_PATH",
        "/opt/mmr-api/app/roof_pipeline/msgp/artifacts/model.ckpt",
    )
)

_TARGET_HW = 256
_MIN_AREA_PX = 200  # under this, drop the polygon (mask noise / dormer stub)
_RDP_EPSILON_FRAC = 0.005  # fraction of perimeter — RDP simplification tolerance

# Cached singleton — load on first call, reuse across requests.
_model: Any = None
_model_load_path: str | None = None
_load_attempted = False
_load_succeeded = False
_last_predict_at: float | None = None
_total_predict_calls = 0


def auto_segment_available() -> bool:
    """True iff the env flag is on AND the checkpoint loaded."""
    if os.environ.get("MSGP_AUTO_SEGMENT_ENABLED", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return False
    if not _load_attempted:
        load_model()
    return _load_succeeded


def load_model(ckpt_path: Path | None = None) -> bool:
    """Idempotent loader. Reads the Lightning checkpoint, strips the
    ``net.`` prefix, loads into a plain MSGPSegmenter. Returns True on
    success, False otherwise (and logs the reason)."""
    global _model, _model_load_path, _load_attempted, _load_succeeded
    _load_attempted = True

    target = ckpt_path or _DEFAULT_CKPT
    if not target.exists():
        log.info("MSGP auto-segment disabled: no checkpoint at %s", target)
        _load_succeeded = False
        return False

    try:
        import torch
        from roof_pipeline.msgp.model import MSGPSegmenter
    except ImportError as exc:
        log.warning("MSGP auto-segment disabled: torch / model import failed: %s", exc)
        _load_succeeded = False
        return False

    try:
        ckpt = torch.load(str(target), map_location="cpu", weights_only=False)
        model = MSGPSegmenter()
        if isinstance(ckpt, dict) and "state_dict" in ckpt:
            prefix = "net."
            clean = {
                k[len(prefix):]: v
                for k, v in ckpt["state_dict"].items()
                if k.startswith(prefix)
            }
            model.load_state_dict(clean)
        else:
            model.load_state_dict(ckpt)
        model.eval()
    except Exception as exc:
        log.warning("MSGP auto-segment disabled: checkpoint load failed: %s", exc)
        _load_succeeded = False
        return False

    _model = model
    _model_load_path = str(target.resolve())
    _load_succeeded = True
    log.info("MSGP auto-segment loaded from %s", _model_load_path)
    return True


def predict_polygons(
    rgb_array: np.ndarray,
    dsm_array: np.ndarray,
    *,
    threshold: float = 0.5,
) -> list[list[tuple[int, int]]]:
    """Run the trained model on a (H, W, 3) RGB array + (H, W) DSM array
    and return a list of polygons in original-image pixel coordinates.

    The model was trained at 256×256; we resize input down for inference,
    threshold the sigmoid output, then scale contours back up to the
    original imagery dimensions before vectorizing.
    """
    global _last_predict_at, _total_predict_calls
    if _model is None:
        if not load_model():
            return []
    assert _model is not None  # for type checkers

    import cv2
    import torch

    if rgb_array.ndim != 3 or rgb_array.shape[2] != 3:
        raise ValueError(f"expected RGB (H, W, 3); got {rgb_array.shape}")
    if dsm_array.ndim != 2:
        raise ValueError(f"expected DSM (H, W); got {dsm_array.shape}")

    orig_h, orig_w = rgb_array.shape[:2]

    # Build the (4, H, W) tensor in the same way msgp_prepare_data does
    # so train and inference agree on channel order + normalization.
    rgb_f = rgb_array.astype("float32") / 255.0
    rgb_chw = np.transpose(rgb_f, (2, 0, 1))  # HWC -> CHW
    dsm_f = dsm_array.astype("float32")
    mean = float(dsm_f.mean()) if dsm_f.size else 0.0
    std = float(dsm_f.std()) if dsm_f.size else 1.0
    if std < 1e-6:
        std = 1.0
    dsm_norm = (dsm_f - mean) / std
    inp = np.concatenate([rgb_chw, dsm_norm[None, ...]], axis=0)

    x = torch.from_numpy(inp).unsqueeze(0)  # (1, 4, H, W)
    x = torch.nn.functional.interpolate(
        x, size=(_TARGET_HW, _TARGET_HW),
        mode="bilinear", align_corners=False,
    )
    t0 = time.perf_counter()
    with torch.no_grad():
        logits = _model(x)
    probs = torch.sigmoid(logits)[0, 0].cpu().numpy()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    mask_small = (probs >= threshold).astype("uint8")

    # Upsample mask back to original imagery dims with nearest so the
    # 0/1 boundary stays clean. Then run findContours on the upsampled
    # mask — gives polygons in original pixel coords directly.
    mask_full = cv2.resize(
        mask_small, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST,
    )
    contours, _ = cv2.findContours(
        mask_full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE,
    )
    polygons: list[list[tuple[int, int]]] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < _MIN_AREA_PX:
            continue
        epsilon = _RDP_EPSILON_FRAC * cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, epsilon, True).reshape(-1, 2)
        # cv2 returns (col, row) → (x, y). Cast to int.
        polygons.append([(int(p[0]), int(p[1])) for p in approx])

    _last_predict_at = time.time()
    _total_predict_calls += 1
    log.info(
        "msgp.predict: %d polygons (%.0fms, threshold=%.2f, %dx%d)",
        len(polygons), elapsed_ms, threshold, orig_w, orig_h,
    )
    return polygons


def auto_segment_health() -> dict[str, Any]:
    """Snapshot of loader state — surfaced via the auto-segment health
    endpoint without forcing a model load on every probe."""
    return {
        "enabled_flag": os.environ.get("MSGP_AUTO_SEGMENT_ENABLED", "").lower()
        in {"1", "true", "yes"},
        "loaded": bool(_load_succeeded),
        "load_attempted": _load_attempted,
        "checkpoint_path": _model_load_path,
        "total_predict_calls": _total_predict_calls,
        "last_predict_at": _last_predict_at,
    }
