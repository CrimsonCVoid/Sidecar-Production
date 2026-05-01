"""End-to-end smoke test for the Phase 4 edge classifier.

Trains a tiny synthetic XGBoost model in a tmpdir, points the
classifier at it, runs predict_edges over a hand-built polygon/plane
graph, and verifies:

  - classifier_health() flips to loaded=True
  - predict_edges returns one entry per edge
  - each entry is (label, confidence) with conf in [0, 1]
  - classifier_health() counters reflect the call

Skipped (not failed) when xgboost isn't installed locally — the prod
sidecar has it, but local dev environments may not.

Useful for: verifying a fresh checkout's wiring before you commit
training-data extraction work, OR after a refactor to predict.py /
the model loader.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

# These imports must work without xgboost (predict.py defers the
# import). The smoke test itself needs xgboost — we skip the whole
# module when it's missing.
xgboost = pytest.importorskip("xgboost")

from roof_pipeline.edge_classifier import (  # noqa: E402
    classifier_available,
    classifier_health,
    load_model,
    predict_edges,
)
from roof_pipeline.edge_classifier import predict as predict_mod  # noqa: E402


@dataclass
class FakePlane:
    """Stand-in for roof_pipeline.planes.Plane — predict_edges only
    reads .normal off it."""

    normal: tuple[float, float, float]


def _make_synthetic_dataset(n_rows: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """Random feature vectors mapped to one of 7 edge classes via a
    deterministic rule on a few feature columns. The model will pick
    up the rule and predict at >50% accuracy — well above chance."""
    rng = np.random.default_rng(1729)
    n_features = len(predict_mod.FEATURE_COLUMNS)
    X = rng.normal(size=(n_rows, n_features))
    # Pull a couple of feature columns by name so the rule survives a
    # FEATURE_COLUMNS reorder.
    cols = {name: i for i, name in enumerate(predict_mod.FEATURE_COLUMNS)}
    is_horiz = X[:, cols["edge_is_horizontal"]] > 0
    shared = X[:, cols["shared_with_neighbor"]] > 0
    z_min = X[:, cols["edge_z_min"]]
    # 0..6 mapped to LABEL_CLASSES order
    y = np.where(
        shared,
        np.where(z_min > 0, 2, 3),  # ridge | hip
        np.where(is_horiz, 0, 1),  # eave | rake
    )
    return X, y


def _train_and_save(tmpdir: Path) -> None:
    X, y = _make_synthetic_dataset()
    booster = xgboost.XGBClassifier(
        n_estimators=20, max_depth=3, eval_metric="mlogloss"
    )
    booster.fit(X, y)
    tmpdir.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(tmpdir / "model.json"))
    encoder = {
        "classes": predict_mod.LABEL_CLASSES,
        "model_version": "smoke-test-v0",
        "feature_columns": predict_mod.FEATURE_COLUMNS,
    }
    (tmpdir / "label_encoder.json").write_text(json.dumps(encoder))


def _reset_module_state() -> None:
    """Clear predict.py's module-scope cache so each test gets a clean
    load attempt."""
    predict_mod._model = None  # type: ignore[attr-defined]
    predict_mod._label_encoder = None  # type: ignore[attr-defined]
    predict_mod._load_attempted = False  # type: ignore[attr-defined]
    predict_mod._load_succeeded = False  # type: ignore[attr-defined]
    predict_mod._last_predict_at = None  # type: ignore[attr-defined]
    predict_mod._last_predict_latency_ms = None  # type: ignore[attr-defined]
    predict_mod._predict_total_calls = 0  # type: ignore[attr-defined]
    predict_mod._predict_total_edges = 0  # type: ignore[attr-defined]
    predict_mod._predict_high_confidence_edges = 0  # type: ignore[attr-defined]
    predict_mod._load_path = None  # type: ignore[attr-defined]
    predict_mod._model_version = None  # type: ignore[attr-defined]


def test_classifier_health_no_model(tmp_path, monkeypatch):
    """With the env flag off, classifier_health() must report
    loaded=False and never read from disk."""
    _reset_module_state()
    monkeypatch.delenv("EDGE_CLASSIFIER_ENABLED", raising=False)
    health = classifier_health()
    assert health["enabled_flag"] is False
    assert health["loaded"] is False
    assert health["model_version"] is None


def test_round_trip(tmp_path, monkeypatch):
    """End-to-end: train tiny model -> load -> predict -> health
    counters increment."""
    _reset_module_state()
    artifacts = tmp_path / "artifacts"
    _train_and_save(artifacts)
    monkeypatch.setenv("EDGE_CLASSIFIER_ENABLED", "true")
    monkeypatch.setenv("EDGE_CLASSIFIER_MODEL_DIR", str(artifacts))
    # DEFAULT_MODEL_DIR is a module-scope Path constant; reload the
    # module-level value so the env override actually applies.
    predict_mod.DEFAULT_MODEL_DIR = artifacts  # type: ignore[attr-defined]

    assert load_model(artifacts) is True
    assert classifier_available() is True

    # 4-vertex roof panel + a neighbor sharing one edge.
    poly = np.array(
        [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0], [4.0, 3.0, 1.0], [0.0, 3.0, 1.0]]
    )
    neighbor = np.array(
        [[0.0, 3.0, 1.0], [4.0, 3.0, 1.0], [4.0, 6.0, 0.0], [0.0, 6.0, 0.0]]
    )
    polygons = {1: poly, 2: neighbor}
    planes = {
        1: FakePlane(normal=(0.0, -0.32, 0.95)),
        2: FakePlane(normal=(0.0, 0.32, 0.95)),
    }

    preds = predict_edges(1, poly, planes[1], polygons, planes)
    assert preds is not None
    assert len(preds) == poly.shape[0]
    for label, conf in preds:
        assert 0.0 <= conf <= 1.0
        # Empty label is the low-confidence sentinel; non-empty must
        # be one of the classes.
        if label:
            assert label in predict_mod.LABEL_CLASSES

    health = classifier_health()
    assert health["loaded"] is True
    assert health["predict_total_calls"] == 1
    assert health["predict_total_edges"] == poly.shape[0]
    assert health["model_version"] == "smoke-test-v0"
    assert health["last_predict_latency_ms"] is not None
    assert health["last_predict_latency_ms"] > 0
