"""Corner-elevation predictor (sibling of edge_classifier).

Tightens the per-corner Z estimate when the user clicks a roof corner
through tree canopy, lifted gutter line, or other DSM contamination.
The model is consulted by the FastAPI corner-check endpoint when
ELEVATION_PREDICTOR_ENABLED=true; otherwise the existing RANSAC-plane
prediction runs unchanged.

Public surface:
    from roof_pipeline.elevation_predictor import (
        load_model, predict_corner_z, predictor_available,
    )
"""

from .predict import (
    load_model,
    predict_corner_z,
    predictor_available,
    predictor_health,
)

__all__ = [
    "load_model",
    "predict_corner_z",
    "predictor_available",
    "predictor_health",
]
