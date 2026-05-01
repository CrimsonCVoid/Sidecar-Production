"""Edge-type classifier (Phase 4 of the pipeline upgrade).

Replaces the geometric `_classify_panel_edges` rule in shop_drawings.py
with a model trained on every edge type any user ever saved. The
classifier runs only when EDGE_CLASSIFIER_ENABLED=true; otherwise the
existing rule path runs unchanged.

Public surface:
    from roof_pipeline.edge_classifier import (
        load_model, predict_edges, classifier_available,
    )
"""

from .predict import (
    load_model,
    predict_edges,
    classifier_available,
)

__all__ = [
    "load_model",
    "predict_edges",
    "classifier_available",
]
