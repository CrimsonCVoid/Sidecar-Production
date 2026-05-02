"""Elevation predictor inference.

Loads the XGBoost regressor + metadata produced by train.py, and
runs feature-vector inference for a single corner click. Returns
`(predicted_z, confidence_proxy)` or None on any failure path.

Designed so that model load failure leaves the predictor disabled:
load_model() never raises; it returns False. Downstream callers
check predictor_available() before trying to use it. The FastAPI
corner-check endpoint is expected to fall back to the existing
RANSAC-plane prediction whenever this module returns None.

Feature layout MUST stay in lockstep with the training script
(WebsiteDesign/scripts/build_elevation_training_set.py). The list
of column names lives in model.FEATURE_COLUMNS — any change there
has to be mirrored in the training script and the model retrained.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from roof_pipeline import telemetry

from .model import FEATURE_COLUMNS, MODEL_VERSION

log = logging.getLogger(__name__)

# In-memory cache of the loaded model + meta. None means we've tried
# to load and failed (or the env flag is off) — don't retry per
# request.
_model: Any = None
_meta: dict[str, Any] | None = None
_load_attempted = False
_load_succeeded = False

# Health telemetry — populated on every predict_corner_z call so an
# operator can ask "is the predictor actually firing" without SSH.
_last_predict_at: float | None = None
_last_predict_latency_ms: float | None = None
_predict_total_calls = 0
_predict_total_high_confidence = 0
_load_path: str | None = None
_model_version: str | None = None
_cv_mae: float | None = None

DEFAULT_MODEL_DIR = Path(
    os.environ.get(
        "ELEVATION_PREDICTOR_MODEL_DIR",
        "/opt/mmr-api/app/roof_pipeline/elevation_predictor/artifacts",
    )
)

# Confidence proxy parameters. The predictor is meant to refine the
# bilinear DSM sample; the further the prediction strays from that
# sample, the less we trust the model. 5 m corresponds to roughly a
# two-storey error which we treat as "complete loss of confidence".
_CONFIDENCE_REFERENCE_M = 5.0


def predictor_available() -> bool:
    """True iff ELEVATION_PREDICTOR_ENABLED is set AND a model loaded."""
    if os.environ.get("ELEVATION_PREDICTOR_ENABLED", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return False
    if not _load_attempted:
        load_model()
    return _load_succeeded


def load_model(model_dir: Path | None = None) -> bool:
    """Load the model + meta from disk. Idempotent: a second call is a
    no-op once the first succeeded. Returns True on success."""
    global _model, _meta, _load_attempted, _load_succeeded
    global _load_path, _model_version, _cv_mae
    _load_attempted = True

    target = model_dir or DEFAULT_MODEL_DIR
    model_path = target / "elevation_model.json"
    meta_path = target / "elevation_predictor_meta.json"

    if not model_path.exists() or not meta_path.exists():
        log.info(
            "Elevation predictor disabled: artifacts not found at %s "
            "(expected elevation_model.json + elevation_predictor_meta.json)",
            target,
        )
        _load_succeeded = False
        return False

    try:
        import xgboost as xgb  # type: ignore
    except ImportError:
        log.warning("Elevation predictor disabled: xgboost not installed")
        _load_succeeded = False
        return False

    try:
        regressor = xgb.XGBRegressor()
        regressor.load_model(str(model_path))
        meta = json.loads(meta_path.read_text())
    except Exception as exc:
        log.warning("Elevation predictor disabled: load failed: %s", exc)
        _load_succeeded = False
        return False

    _model = regressor
    _meta = meta if isinstance(meta, dict) else None
    _load_succeeded = True
    _load_path = str(target.resolve())
    _model_version = (
        _meta.get("model_version", MODEL_VERSION)
        if isinstance(_meta, dict)
        else MODEL_VERSION
    )
    _cv_mae = (
        float(_meta.get("cv_mean_mae"))
        if isinstance(_meta, dict) and _meta.get("cv_mean_mae") is not None
        else None
    )
    log.info(
        "Elevation predictor loaded from %s (version=%s, cv_mae=%s)",
        target,
        _model_version,
        _cv_mae,
    )
    return True


def predictor_health() -> dict[str, Any]:
    """Snapshot of the predictor's current state. Cheap — no model
    work, safe to call from a request path."""
    flag_on = os.environ.get("ELEVATION_PREDICTOR_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }
    target_col = (
        _meta.get("target_column") if isinstance(_meta, dict) else None
    )
    return {
        "enabled_flag": flag_on,
        "loaded": bool(_load_succeeded),
        "load_attempted": _load_attempted,
        "model_path": _load_path,
        "model_version": _model_version,
        "feature_columns": FEATURE_COLUMNS,
        "target_column": target_col,
        "cv_mae": _cv_mae,
        "last_predict_at": _last_predict_at,
        "last_predict_latency_ms": _last_predict_latency_ms,
        "predict_total_calls": _predict_total_calls,
        "predict_total_high_confidence": _predict_total_high_confidence,
    }


def predict_corner_z(
    features: dict[str, Any],
    *,
    sample_id: str | None = None,
    panel_id: int | None = None,
    corner_idx: int | None = None,
) -> tuple[float, float] | None:
    """Predict (corner_z_meters, confidence) for a single corner click.

    Returns None when the predictor isn't available; the caller should
    fall back to the existing RANSAC-plane prediction. When available,
    returns `(predicted_z, confidence_proxy)` where confidence is in
    `[0.0, 1.0]` and falls off as the prediction strays from
    `dsm_z_bilinear` (a stand-in for an actual uncertainty estimate
    until we have enough data to fit a proper one).

    Phase parity with edge_classifier:
      - emits `elevation_predictor.predicted` on success
      - emits `elevation_predictor.fallback` on every short-circuit
    """
    global _last_predict_at, _last_predict_latency_ms
    global _predict_total_calls, _predict_total_high_confidence

    if not predictor_available() or _model is None:
        telemetry.track(
            "elevation_predictor.fallback",
            sample_id=sample_id,
            metadata={
                "reason": "predictor_unavailable",
                "panel_id": panel_id,
                "corner_idx": corner_idx,
                "flag_on": os.environ.get(
                    "ELEVATION_PREDICTOR_ENABLED", ""
                ).lower()
                in {"1", "true", "yes"},
                "loaded": _load_succeeded,
            },
        )
        return None

    missing = [c for c in FEATURE_COLUMNS if c not in features]
    if missing:
        log.warning(
            "Elevation predictor missing %d feature(s): %s",
            len(missing),
            missing,
        )
        telemetry.track(
            "elevation_predictor.fallback",
            sample_id=sample_id,
            metadata={
                "reason": "missing_features",
                "panel_id": panel_id,
                "corner_idx": corner_idx,
                "missing_count": len(missing),
            },
        )
        return None

    started = time.perf_counter()
    try:
        row = np.asarray(
            [[float(features[c]) for c in FEATURE_COLUMNS]],
            dtype=float,
        )
    except (TypeError, ValueError) as exc:
        log.warning("Elevation predictor feature coercion failed: %s", exc)
        telemetry.track(
            "elevation_predictor.fallback",
            sample_id=sample_id,
            metadata={
                "reason": "feature_coercion_failed",
                "panel_id": panel_id,
                "corner_idx": corner_idx,
                "exception": type(exc).__name__,
            },
        )
        return None

    try:
        prediction = float(_model.predict(row)[0])
    except Exception as exc:
        log.warning("Elevation predictor predict failed: %s", exc)
        telemetry.track(
            "elevation_predictor.fallback",
            sample_id=sample_id,
            metadata={
                "reason": "predict_failed",
                "panel_id": panel_id,
                "corner_idx": corner_idx,
                "exception": type(exc).__name__,
            },
        )
        return None

    # If the meta says we trained on delta_z, the model output is a
    # delta and the consumer wants absolute Z. Add the bilinear sample
    # back in so the caller never has to know which target was used.
    bilinear_z = float(features["dsm_z_bilinear"])
    target_col = (
        _meta.get("target_column") if isinstance(_meta, dict) else None
    )
    if target_col == "target_delta_z":
        predicted_z = bilinear_z + prediction
    else:
        predicted_z = prediction

    # Confidence proxy — see _CONFIDENCE_REFERENCE_M. We can swap this
    # for a calibrated quantile model once we have enough labels.
    drift = abs(predicted_z - bilinear_z)
    confidence = max(0.0, 1.0 - min(drift / _CONFIDENCE_REFERENCE_M, 1.0))

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _last_predict_at = time.time()
    _last_predict_latency_ms = elapsed_ms
    _predict_total_calls += 1
    if confidence >= 0.6:
        _predict_total_high_confidence += 1

    telemetry.track(
        "elevation_predictor.predicted",
        sample_id=sample_id,
        duration_ms=elapsed_ms,
        metadata={
            "panel_id": panel_id,
            "corner_idx": corner_idx,
            "predicted_z": round(predicted_z, 4),
            "dsm_z_bilinear": round(bilinear_z, 4),
            "drift_m": round(drift, 4),
            "confidence": round(confidence, 4),
            "model_version": _model_version,
            "target_column": target_col,
        },
    )
    return predicted_z, confidence
