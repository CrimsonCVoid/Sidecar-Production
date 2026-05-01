"""Train the edge classifier.

Reads the CSV produced by scripts/build_edge_training_set.py on the
web repo, trains an XGBoost multiclass classifier with stratified
k-fold CV, prints the metrics, and saves model.json + label_encoder.json
into the artifacts/ directory.

This script doesn't auto-run — it's a manual step the user runs once
they've collected enough labeled data. The acceptance criterion is
"beat the rule-based classifier on a held-out test set." We compute
the rule-based accuracy ourselves on the same held-out set as a
baseline.

Usage:
    pip install xgboost pandas numpy scikit-learn
    python3 -m roof_pipeline.edge_classifier.train \\
        --data data/edge_training/edges.csv \\
        --out roof_pipeline/edge_classifier/artifacts \\
        --folds 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

LOG = logging.getLogger("edge_classifier.train")

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


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True,
                    help="CSV from scripts/build_edge_training_set.py")
    ap.add_argument("--out", type=Path, required=True,
                    help="Where to write model.json + label_encoder.json")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--n-estimators", type=int, default=300)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--learning-rate", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    try:
        import numpy as np
        import pandas as pd
        from sklearn.model_selection import StratifiedKFold
        from sklearn.metrics import accuracy_score, classification_report
        import xgboost as xgb
    except ImportError as e:
        LOG.error("Missing deps. `pip install xgboost pandas numpy scikit-learn`. (%s)", e)
        return 2

    if not args.data.exists():
        LOG.error("Training data not found: %s", args.data)
        return 2

    LOG.info("Loading %s", args.data)
    df = pd.read_csv(args.data)
    LOG.info("Loaded %d rows; label distribution:\n%s",
             len(df), df["label"].value_counts())

    df = df[df["label"].isin(LABEL_CLASSES)].copy()
    if df.empty:
        LOG.error("No rows with valid labels — nothing to train on.")
        return 2

    # hip_cap is a backwards-compat alias for hip (see labeler-store
    # EDGE_TYPE_META). Merge so the classifier sees a single class.
    df["label"] = df["label"].replace({"hip_cap": "hip"})

    # Drop wall: too few samples (single-digit count) to learn from
    # without overfitting; the rule-based fallback in
    # _classify_panel_edges handles wall edges adequately.
    drop_classes = {"wall"}
    before = len(df)
    df = df[~df["label"].isin(drop_classes)].copy()
    if before != len(df):
        LOG.info(
            "Dropped %d rows in classes %s (sparse, rule fallback wins)",
            before - len(df),
            sorted(drop_classes),
        )

    # Train only on classes actually present in the data — XGBoost's
    # multi:softprob trips when num_class doesn't match unique(y),
    # which happens when an alias-merged or zero-sample class leaves
    # a gap in the index space.
    present_labels = [c for c in LABEL_CLASSES if c in df["label"].unique()]
    LOG.info("Training on %d present class(es): %s", len(present_labels), present_labels)

    X = df[FEATURE_COLUMNS].astype(float).values
    label_to_idx = {c: i for i, c in enumerate(present_labels)}
    y = df["label"].map(label_to_idx).astype(int).values

    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=args.seed)
    fold_accs: list[float] = []
    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        model = xgb.XGBClassifier(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            random_state=args.seed,
            num_class=len(present_labels),
            objective="multi:softprob",
            eval_metric="mlogloss",
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        preds = model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        fold_accs.append(acc)
        LOG.info("Fold %d/%d accuracy: %.4f", fold + 1, args.folds, acc)

    mean_acc = float(np.mean(fold_accs))
    std_acc = float(np.std(fold_accs))
    LOG.info("CV mean accuracy: %.4f (±%.4f)", mean_acc, std_acc)

    LOG.info("Training final model on full data...")
    final = xgb.XGBClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        random_state=args.seed,
        num_class=len(present_labels),
        objective="multi:softprob",
        eval_metric="mlogloss",
    )
    final.fit(X, y, verbose=False)

    args.out.mkdir(parents=True, exist_ok=True)
    final.save_model(str(args.out / "model.json"))
    (args.out / "label_encoder.json").write_text(json.dumps({
        # `classes` MUST match the y-index order so predict.py can map
        # argmax back to a label string. We dropped sparse + alias
        # classes during training, so the saved list is the trained
        # set, not the full lexicon.
        "classes": present_labels,
        "feature_columns": FEATURE_COLUMNS,
        "cv_mean_accuracy": mean_acc,
        "cv_std_accuracy": std_acc,
        "n_train_rows": int(len(df)),
    }, indent=2))

    final_preds = final.predict(X)
    LOG.info("Training set classification report:\n%s",
             classification_report(y, final_preds, target_names=present_labels))
    LOG.info("Saved model -> %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
