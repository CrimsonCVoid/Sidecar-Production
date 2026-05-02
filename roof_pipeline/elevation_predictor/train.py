"""Train the corner-elevation predictor.

Reads the CSV produced by WebsiteDesign/scripts/build_elevation_training_set.py,
trains an XGBoost regressor with k-fold CV, prints fold MAE plus
naive baselines (always-predict dsm_z_bilinear, always-predict
dsm_z_robust), then saves elevation_model.json +
elevation_predictor_meta.json into the artifacts directory.

The script doesn't auto-run — it's a manual step the user runs once
they've collected enough labeled corner-click data. The acceptance
criterion is "beat the naive DSM samples on a held-out fold." The
two baselines are reported in the same units as the model so the
operator can read off how much value the model adds.

Usage:
    pip install xgboost pandas numpy scikit-learn
    python3 -m roof_pipeline.elevation_predictor.train \\
        --data ../WebsiteDesign/data/edge_training/elevations.csv \\
        --out roof_pipeline/elevation_predictor/artifacts \\
        --folds 5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from .model import (
    CSV_ID_COLUMNS,
    DEFAULT_HYPERPARAMS,
    FEATURE_COLUMNS,
    MODEL_VERSION,
)

LOG = logging.getLogger("elevation_predictor.train")

TARGET_CHOICES = {
    # CLI flag value -> CSV column name
    "z": "target_z",
    "delta_z": "target_delta_z",
}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data",
        type=Path,
        required=True,
        help="CSV from WebsiteDesign/scripts/build_elevation_training_set.py",
    )
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Where to write elevation_model.json + elevation_predictor_meta.json",
    )
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument(
        "--target",
        choices=list(TARGET_CHOICES.keys()),
        default="z",
        help="Predict absolute roof Z ('z', default) or delta from "
             "dsm_z_bilinear ('delta_z'). The artifact stamps which one.",
    )
    ap.add_argument("--n-estimators", type=int,
                    default=DEFAULT_HYPERPARAMS["n_estimators"])
    ap.add_argument("--max-depth", type=int,
                    default=DEFAULT_HYPERPARAMS["max_depth"])
    ap.add_argument("--learning-rate", type=float,
                    default=DEFAULT_HYPERPARAMS["learning_rate"])
    ap.add_argument("--seed", type=int,
                    default=DEFAULT_HYPERPARAMS["random_state"])
    args = ap.parse_args()

    try:
        import numpy as np
        import pandas as pd
        from sklearn.metrics import mean_absolute_error
        from sklearn.model_selection import KFold
        import xgboost as xgb  # noqa: F401  (validate import early)
    except ImportError as e:
        LOG.error(
            "Missing deps. `pip install xgboost pandas numpy scikit-learn`. (%s)",
            e,
        )
        return 2

    if not args.data.exists():
        LOG.error("Training data not found: %s", args.data)
        return 2

    LOG.info("Loading %s", args.data)
    df = pd.read_csv(args.data)
    LOG.info("Loaded %d rows", len(df))

    target_col = TARGET_CHOICES[args.target]
    missing_features = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing_features:
        LOG.error(
            "CSV is missing %d expected feature column(s): %s. "
            "Re-run build_elevation_training_set.py against the latest "
            "FEATURE_COLUMNS in roof_pipeline/elevation_predictor/model.py.",
            len(missing_features),
            missing_features,
        )
        return 2
    if target_col not in df.columns:
        LOG.error(
            "CSV is missing the requested target column '%s'. "
            "Available columns: %s",
            target_col,
            list(df.columns),
        )
        return 2

    # Drop rows where the target is null — likely dropped corners or
    # extraction failures upstream.
    before = len(df)
    df = df.dropna(subset=[target_col, *FEATURE_COLUMNS]).copy()
    if before != len(df):
        LOG.info("Dropped %d row(s) with null target/feature values",
                 before - len(df))
    if df.empty:
        LOG.error("No usable rows after null filter — nothing to train on.")
        return 2

    X = df[FEATURE_COLUMNS].astype(float).values
    y = df[target_col].astype(float).values

    # Naive baselines — what does the model need to beat?
    bilinear = df["dsm_z_bilinear"].astype(float).values
    robust = df["dsm_z_robust"].astype(float).values
    if args.target == "z":
        baseline_bilinear_mae = float(mean_absolute_error(y, bilinear))
        baseline_robust_mae = float(mean_absolute_error(y, robust))
    else:
        # delta_z target = target_z - dsm_z_bilinear, so the equivalent
        # naive is "predict 0 delta" (i.e. trust the bilinear sample).
        baseline_bilinear_mae = float(mean_absolute_error(y, np.zeros_like(y)))
        baseline_robust_mae = float(
            mean_absolute_error(y, robust - bilinear)
        )
    LOG.info("Baseline MAE (always dsm_z_bilinear): %.4f m",
             baseline_bilinear_mae)
    LOG.info("Baseline MAE (always dsm_z_robust):   %.4f m",
             baseline_robust_mae)

    kf = KFold(n_splits=args.folds, shuffle=True, random_state=args.seed)
    fold_maes: list[float] = []
    for fold, (train_idx, test_idx) in enumerate(kf.split(X)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        model = _build_model(args)
        model.fit(X_train, y_train,
                  eval_set=[(X_test, y_test)], verbose=False)
        preds = model.predict(X_test)
        mae = float(mean_absolute_error(y_test, preds))
        fold_maes.append(mae)
        LOG.info("Fold %d/%d MAE: %.4f m", fold + 1, args.folds, mae)

    cv_mae = float(np.mean(fold_maes))
    cv_std = float(np.std(fold_maes))
    LOG.info("CV mean MAE: %.4f m (+/- %.4f)", cv_mae, cv_std)
    LOG.info(
        "Lift over dsm_z_bilinear: %.4f m (lower model MAE = better). "
        "Lift over dsm_z_robust: %.4f m.",
        baseline_bilinear_mae - cv_mae,
        baseline_robust_mae - cv_mae,
    )

    LOG.info("Training final model on full data...")
    final = _build_model(args)
    final.fit(X, y, verbose=False)

    args.out.mkdir(parents=True, exist_ok=True)
    final.save_model(str(args.out / "elevation_model.json"))
    meta = {
        "model_version": MODEL_VERSION,
        "training_date": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "target_column": target_col,
        "feature_columns": FEATURE_COLUMNS,
        "hyperparameters": {
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "learning_rate": args.learning_rate,
            "random_state": args.seed,
            "objective": DEFAULT_HYPERPARAMS["objective"],
        },
        "cv_mean_mae": cv_mae,
        "cv_std_mae": cv_std,
        "baseline_mae_bilinear": baseline_bilinear_mae,
        "baseline_mae_robust": baseline_robust_mae,
        "n_train_rows": int(len(df)),
        "id_columns": CSV_ID_COLUMNS,
    }
    (args.out / "elevation_predictor_meta.json").write_text(
        json.dumps(meta, indent=2)
    )

    LOG.info("Saved model -> %s", args.out)
    return 0


def _build_model(args: argparse.Namespace):
    # Defer to model.make_regressor so the project defaults stay
    # centralised; CLI overrides flow through here.
    from .model import make_regressor

    return make_regressor(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        random_state=args.seed,
    )


if __name__ == "__main__":
    sys.exit(main())
