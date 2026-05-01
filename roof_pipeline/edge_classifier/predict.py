"""Edge classifier inference.

Loads the XGBoost model + label encoder produced by train.py, and
runs feature extraction + inference on a panel's edges. Returns a list
of (label, confidence) tuples, one per edge.

Designed so that model load failure leaves the classifier disabled:
the load_model() function never raises; it returns None. Downstream
callers check classifier_available() before trying to use it.

Feature layout MUST stay in lockstep with the training script
(scripts/build_edge_training_set.py on the web repo). The list of
column names lives in FEATURE_COLUMNS below — any change there has to
be mirrored in the training script and the model retrained.
"""

from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from roof_pipeline import telemetry

log = logging.getLogger(__name__)

# In-memory cache of the loaded model + label encoder. None means we've
# tried to load and failed (or the env flag is off) — don't retry per
# request.
_model: Any = None
_label_encoder: Any = None
_load_attempted = False
_load_succeeded = False

# Health telemetry — populated on every predict_edges call so the
# /api/v2/edge-classifier/health endpoint can report freshness without
# touching the model itself.
_last_predict_at: float | None = None
_last_predict_latency_ms: float | None = None
_predict_total_calls = 0
_predict_total_edges = 0
_predict_high_confidence_edges = 0
_load_path: str | None = None
_model_version: str | None = None


# Must mirror scripts/build_edge_training_set.py FEATURE_COLUMNS
# excluding the metadata columns (sample_id, indices) and label.
FEATURE_COLUMNS = [
    "edge_length_ft",
    "edge_dx",
    "edge_dy",
    "edge_z_min",
    "edge_z_max",
    "edge_z_delta",
    "panel_area_sqft",
    "panel_z_min",
    "panel_z_max",
    "panel_normal_x",
    "panel_normal_y",
    "panel_normal_z",
    "panel_slope_rise",
    "edge_is_horizontal",
    "edge_is_steep_diag",
    "shared_with_neighbor",
    "neighbor_normal_dot",
]

LABEL_CLASSES = ["eave", "rake", "ridge", "hip", "valley", "hip_cap", "wall"]

DEFAULT_MODEL_DIR = Path(
    os.environ.get(
        "EDGE_CLASSIFIER_MODEL_DIR",
        "/opt/mmr-api/app/roof_pipeline/edge_classifier/artifacts",
    )
)


def classifier_available() -> bool:
    """True iff EDGE_CLASSIFIER_ENABLED is set AND a model loaded."""
    if os.environ.get("EDGE_CLASSIFIER_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return False
    if not _load_attempted:
        load_model()
    return _load_succeeded


def load_model(model_dir: Path | None = None) -> bool:
    """Load the model + label encoder from disk. Idempotent: a second
    call is a no-op once the first succeeded. Returns True on success."""
    global _model, _label_encoder, _load_attempted, _load_succeeded
    global _load_path, _model_version
    _load_attempted = True

    target = model_dir or DEFAULT_MODEL_DIR
    model_path = target / "model.json"
    encoder_path = target / "label_encoder.json"

    if not model_path.exists() or not encoder_path.exists():
        log.info(
            "Edge classifier disabled: artifacts not found at %s "
            "(expected model.json + label_encoder.json)",
            target,
        )
        _load_succeeded = False
        return False

    try:
        import xgboost as xgb  # type: ignore
    except ImportError:
        log.warning("Edge classifier disabled: xgboost not installed")
        _load_succeeded = False
        return False

    try:
        booster = xgb.XGBClassifier()
        booster.load_model(str(model_path))
        import json
        encoder = json.loads(encoder_path.read_text())
    except Exception as exc:
        log.warning("Edge classifier disabled: load failed: %s", exc)
        _load_succeeded = False
        return False

    _model = booster
    _label_encoder = encoder
    _load_succeeded = True
    _load_path = str(target.resolve())
    # Version stamp lives in the encoder so retraining without bumping
    # the model_version bumps something visible to ops.
    _model_version = (
        encoder.get("model_version") if isinstance(encoder, dict) else None
    )
    log.info(
        "Edge classifier loaded from %s (version=%s)", target, _model_version
    )
    return True


def classifier_health() -> dict[str, Any]:
    """Snapshot of the classifier's current state. Used by the
    /api/v2/edge-classifier/health route — never blocks on model work,
    safe to call from a request path."""
    flag_on = os.environ.get("EDGE_CLASSIFIER_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }
    return {
        "enabled_flag": flag_on,
        "loaded": bool(_load_succeeded),
        "load_attempted": _load_attempted,
        "model_path": _load_path,
        "model_version": _model_version,
        "feature_columns": FEATURE_COLUMNS,
        "label_classes": LABEL_CLASSES,
        "last_predict_at": _last_predict_at,
        "last_predict_latency_ms": _last_predict_latency_ms,
        "predict_total_calls": _predict_total_calls,
        "predict_total_edges": _predict_total_edges,
        "predict_high_confidence_edges": _predict_high_confidence_edges,
    }


def _quantize(x: float, y: float, precision: float = 0.05) -> tuple[int, int]:
    """Bucket a 3D point's xy to a tuple. Used to detect shared edges
    between adjacent panels (same logic as shop_drawings._shared_edge_key)."""
    return (int(round(x / precision)), int(round(y / precision)))


def _edge_key(a: np.ndarray, b: np.ndarray) -> tuple:
    qa = _quantize(float(a[0]), float(a[1]))
    qb = _quantize(float(b[0]), float(b[1]))
    return (min(qa, qb), max(qa, qb))


def _build_neighbor_index(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Any],
) -> dict[tuple, list[int]]:
    index: dict[tuple, list[int]] = {}
    for pid, poly in polygons.items():
        if pid not in planes:
            continue
        n = poly.shape[0]
        for i in range(n):
            k = _edge_key(poly[i], poly[(i + 1) % n])
            index.setdefault(k, []).append(pid)
    return index


def _featurize_edge(
    poly: np.ndarray,
    edge_index: int,
    plane_normal: np.ndarray,
    plane_slope_rise: float,
    panel_z_min: float,
    panel_z_max: float,
    panel_area_sqft: float,
    neighbor_index: dict[tuple, list[int]],
    pid: int,
    planes: dict[int, Any],
) -> list[float]:
    M_TO_FT = 3.280839895
    n = poly.shape[0]
    a = poly[edge_index]
    b = poly[(edge_index + 1) % n]
    dx, dy, dz = float(b[0] - a[0]), float(b[1] - a[1]), float(b[2] - a[2])
    length_m = math.sqrt(dx * dx + dy * dy + dz * dz)
    length_ft = length_m * M_TO_FT
    horiz_len = max(math.hypot(dx, dy), 1e-9)
    unit_x = dx / horiz_len
    unit_y = dy / horiz_len
    z_min = float(min(a[2], b[2]))
    z_max = float(max(a[2], b[2]))
    z_delta = z_max - z_min
    is_horizontal = 1 if abs(z_delta) < 0.05 else 0
    pitch_deg = math.degrees(math.atan2(abs(dz), horiz_len))
    is_steep_diag = 1 if pitch_deg > 30 else 0

    k = _edge_key(a, b)
    owners = neighbor_index.get(k, [])
    others = [o for o in owners if o != pid]
    shared = 1 if others else 0
    if shared:
        other_plane = planes.get(others[0])
        if other_plane is not None:
            other_n = np.asarray(other_plane.normal)
            neighbor_dot = float(np.dot(plane_normal, other_n))
        else:
            neighbor_dot = -1.0
    else:
        neighbor_dot = -1.0

    return [
        round(length_ft, 4),
        round(unit_x, 4),
        round(unit_y, 4),
        round(z_min, 4),
        round(z_max, 4),
        round(z_delta, 4),
        round(panel_area_sqft, 2),
        round(panel_z_min, 4),
        round(panel_z_max, 4),
        round(float(plane_normal[0]), 4),
        round(float(plane_normal[1]), 4),
        round(float(plane_normal[2]), 4),
        round(plane_slope_rise, 2),
        is_horizontal,
        is_steep_diag,
        shared,
        round(neighbor_dot, 4),
    ]


def predict_edges(
    pid: int,
    poly: np.ndarray,
    plane: Any,
    polygons: dict[int, np.ndarray],
    planes: dict[int, Any],
    *,
    confidence_threshold: float = 0.6,
    sample_id: str | None = None,
) -> list[tuple[str, float]] | None:
    """Predict (edge_type, confidence) for every edge on a panel.

    Returns None when the classifier isn't available; the caller should
    fall back to the geometric rule. When available, returns a list of
    length poly.shape[0]. Per the spec, edges where confidence falls
    below confidence_threshold get None for the type so the downstream
    fallback can fill those in per-edge.

    Phase 4 telemetry: emits one `edge_classifier.predicted` per panel
    with confidence quantiles + counts. Falls through to
    `edge_classifier.fallback` with a reason on every short-circuit
    path so the prod telemetry surface answers "is the classifier
    actually firing on production traffic" without SSH.
    """
    global _last_predict_at, _last_predict_latency_ms
    global _predict_total_calls, _predict_total_edges
    global _predict_high_confidence_edges

    if not classifier_available() or _model is None or _label_encoder is None:
        telemetry.track(
            "edge_classifier.fallback",
            sample_id=sample_id,
            metadata={
                "reason": "classifier_unavailable",
                "panel_id": pid,
                "flag_on": os.environ.get(
                    "EDGE_CLASSIFIER_ENABLED", ""
                ).lower()
                in {"1", "true", "yes"},
                "loaded": _load_succeeded,
            },
        )
        return None

    started = time.perf_counter()
    M_TO_FT = 3.280839895

    # Panel-level features
    z_vals = poly[:, 2]
    panel_z_min = float(z_vals.min())
    panel_z_max = float(z_vals.max())
    # Approximate sloped area using shoelace in panel's plane basis is
    # overkill here — we use plan-view area * M_TO_FT^2 for the
    # tabular feature. The classifier has access to the slope so it
    # can correct internally.
    xs = poly[:, 0]
    ys = poly[:, 1]
    area_m2 = 0.5 * abs(
        sum(
            xs[i] * ys[(i + 1) % len(xs)] - xs[(i + 1) % len(xs)] * ys[i]
            for i in range(len(xs))
        )
    )
    panel_area_sqft = area_m2 * (M_TO_FT**2)

    plane_n = np.asarray(plane.normal)
    nx, ny, nz = plane_n
    plane_slope_rise = (
        math.hypot(nx, ny) / max(abs(nz), 1e-9) * 12.0
    )

    neighbor_index = _build_neighbor_index(polygons, planes)

    n = poly.shape[0]
    rows: list[list[float]] = []
    for i in range(n):
        rows.append(
            _featurize_edge(
                poly, i, plane_n, plane_slope_rise,
                panel_z_min, panel_z_max, panel_area_sqft,
                neighbor_index, pid, planes,
            )
        )
    X = np.asarray(rows, dtype=float)

    try:
        proba = _model.predict_proba(X)
    except Exception as exc:
        log.warning("Edge classifier predict_proba failed: %s", exc)
        telemetry.track(
            "edge_classifier.fallback",
            sample_id=sample_id,
            metadata={
                "reason": "predict_proba_failed",
                "panel_id": pid,
                "exception": type(exc).__name__,
            },
        )
        return None

    classes = _label_encoder.get("classes", LABEL_CLASSES)
    out: list[tuple[str, float]] = []
    confidences: list[float] = []
    high_count = 0
    for i in range(n):
        row = proba[i]
        idx = int(np.argmax(row))
        confidence = float(row[idx])
        confidences.append(confidence)
        if confidence < confidence_threshold:
            # Sentinel: caller falls back to rule for this edge.
            out.append(("", confidence))
        else:
            label = classes[idx] if idx < len(classes) else ""
            out.append((label, confidence))
            high_count += 1

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _last_predict_at = time.time()
    _last_predict_latency_ms = elapsed_ms
    _predict_total_calls += 1
    _predict_total_edges += n
    _predict_high_confidence_edges += high_count

    sorted_conf = sorted(confidences)
    p50 = sorted_conf[len(sorted_conf) // 2] if sorted_conf else 0.0
    p95 = sorted_conf[max(0, int(len(sorted_conf) * 0.95) - 1)] if sorted_conf else 0.0
    telemetry.track(
        "edge_classifier.predicted",
        sample_id=sample_id,
        duration_ms=elapsed_ms,
        metadata={
            "panel_id": pid,
            "edge_count": n,
            "high_confidence_count": high_count,
            "low_confidence_count": n - high_count,
            "confidence_p50": round(p50, 4),
            "confidence_p95": round(p95, 4),
            "model_version": _model_version,
            "threshold": confidence_threshold,
        },
    )
    return out
