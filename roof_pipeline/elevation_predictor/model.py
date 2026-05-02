"""Model architecture + hyperparameters for the elevation predictor.

Centralised so train.py and predict.py agree on the feature column
list and the regressor configuration. The CSV header produced by
WebsiteDesign/scripts/build_elevation_training_set.py MUST stay in
lockstep with FEATURE_COLUMNS below — adding/removing a column here
without retraining will silently shift every feature index.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# CSV layout
# ---------------------------------------------------------------------------
# Columns the training script writes, in order. The first three are
# identifiers (dropped before training); target_z / target_delta_z are
# regression targets. Everything in between is a feature.
CSV_ID_COLUMNS = ["sample_id", "panel_id", "corner_idx"]
CSV_TARGET_COLUMNS = ["target_z", "target_delta_z"]

# Features fed to the regressor, in train/inference order. Adding a
# feature requires bumping `MODEL_VERSION` and retraining; predict.py
# refuses to score rows whose dict keys don't cover this list.
#
# Plane parameters (plane_normal_*, plane_d, plane_rms_residual) are
# deliberately NOT here — the regression target is the plane prediction,
# so feeding plane params to the model lets it solve the closed-form
# z = (d - n_x*x - n_y*y) / n_z and adds zero value at inference time
# (the endpoint already has the plane). Dropping them forces the model
# to learn a real correction from raw DSM patch + sibling stats. Keep
# them in the CSV (build_elevation_training_set.py emits them) for
# diagnostic / future-experiment use only.
FEATURE_COLUMNS = [
    "col_px",
    "row_px",
    "panel_corner_count",
    "patch_mean",
    "patch_std",
    "patch_min",
    "patch_p20",
    "patch_p50",
    "patch_p80",
    "patch_max",
    "dsm_z_bilinear",
    "dsm_z_robust",
    "siblings_z_median",
    "siblings_z_std",
    "meters_per_px",
]


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------
# Bumped when the feature set, target definition, or training config
# changes in a way that would invalidate a deployed artifact. The
# value is stamped into elevation_predictor_meta.json so the loader
# can surface it via predictor_health().
MODEL_VERSION = "elevation_predictor_v2"

# Defaults match the spec in the upgrade prompt; train.py CLI flags
# override them when sweeping hyperparameters.
DEFAULT_HYPERPARAMS: dict[str, Any] = {
    "objective": "reg:squarederror",
    "n_estimators": 400,
    "max_depth": 6,
    "learning_rate": 0.05,
    "random_state": 42,
    "eval_metric": "mae",
}


def make_regressor(**overrides: Any) -> Any:
    """Construct an XGBRegressor with the project defaults.

    Importing xgboost lazily so the module can be imported in
    inference-only contexts where xgboost may be absent — predict.py
    handles that case explicitly.
    """
    import xgboost as xgb  # type: ignore

    params = {**DEFAULT_HYPERPARAMS, **overrides}
    return xgb.XGBRegressor(**params)
