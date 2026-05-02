# Elevation Predictor

Sibling of `edge_classifier`. Produces a tightened roof-elevation
estimate for a single corner click when the raw DSM sample is
contaminated by tree canopy, lifted gutter line, or noise.

## Why this exists

When a labeler clicks a panel corner, the existing pipeline samples
the DSM at the click and snaps the click to the panel's RANSAC-fit
plane. That works on clean roofs and breaks on roofs with overhanging
canopy: the DSM bilinear sample reads the tree, not the eave, and the
panel plane drags the corner upward to match. The fix on the
labelling side is the new `/api/labels/check-corner` endpoint, which
asks this module for a per-click correction. When the model is
disabled or absent, the endpoint falls back to the existing
RANSAC-plane prediction — production behaviour is unchanged.

## Status

Scaffold only. The model file `artifacts/elevation_model.json` does
not ship in the repo. Until it's produced and the env flag is
flipped, the existing RANSAC-plane path runs unchanged.

## Pipeline

1. **Extract training data** (web repo):
   ```bash
   cd ~/WebsiteDesign-MMR
   export DATABASE_URL="postgres://..."
   python3 scripts/build_elevation_training_set.py
   ```
   Writes `data/edge_training/elevations.csv`. One row per labeled
   corner across every project. Skip-listed for git via `.gitignore`.

2. **Train**:
   ```bash
   cd ~/Mymetalrooferbackupmvp-firstcommit
   pip install xgboost pandas numpy scikit-learn
   python3 -m roof_pipeline.elevation_predictor.train \
       --data ../WebsiteDesign-MMR/data/edge_training/elevations.csv \
       --out roof_pipeline/elevation_predictor/artifacts \
       --folds 5
   ```
   Writes `artifacts/elevation_model.json` +
   `artifacts/elevation_predictor_meta.json`. Prints fold MAE and the
   two naive baselines (always-predict `dsm_z_bilinear`,
   always-predict `dsm_z_robust`) so you can see how much value the
   model adds. Add `--target delta_z` to predict the offset from the
   bilinear sample instead of absolute Z; the meta file records which
   target the artifact was trained on and `predict_corner_z` adds the
   sample back in transparently.

3. **Commit + deploy**:
   ```bash
   git add roof_pipeline/elevation_predictor/artifacts/elevation_model.json \
           roof_pipeline/elevation_predictor/artifacts/elevation_predictor_meta.json
   git commit -m "elevation_predictor: retrain (cv_mae=...)"
   git push
   ssh root@209.97.156.206
   cd /opt/mmr-api/app && git pull && systemctl restart mmr-api
   ```
   Same convention as `edge_classifier`: artifacts are tracked in git
   for reproducible production rollouts. For testing without a commit,
   `rsync artifacts/* root@.../roof_pipeline/elevation_predictor/artifacts/`
   then restart the service.

4. **Enable**:
   Add `ELEVATION_PREDICTOR_ENABLED=true` to `/opt/mmr-api/app/.env`
   and restart `mmr-api`. Without that env var,
   `predictor_available()` returns False and the corner-check endpoint
   falls back to RANSAC.

## How the FastAPI integration falls back

The `/api/labels/check-corner` endpoint calls
`predict_corner_z(features, sample_id=..., panel_id=..., corner_idx=...)`.

- **Predictor available** (artifacts present, env flag on, xgboost
  installed): the call returns `(predicted_z, confidence)`. The
  endpoint reports both back to the labeler UI; the UI decides
  whether to suggest the correction based on confidence.
- **Predictor unavailable** (artifacts missing, env flag off, xgboost
  not installed, feature dict missing a column, predict crashes):
  `predict_corner_z` returns `None`, `elevation_predictor.fallback`
  is emitted with a reason, and the endpoint replies with the
  existing RANSAC-plane prediction.

The fallback path is the production path today, so disabling the
flag is a clean rollback.

## Confidence proxy

Until we have enough labels to fit a proper uncertainty model, the
returned confidence is a heuristic:

```
confidence = 1 - clamp(|predicted_z - dsm_z_bilinear| / 5.0, 0, 1)
```

Rationale: the predictor is meant to *refine* the bilinear DSM
sample. The further it strays, the less we trust it. 5 m
(roughly two storeys) maps to zero confidence. Swap this for a
calibrated quantile estimate as soon as the dataset supports it.

## Ops surface

| Path | Purpose |
|---|---|
| `predictor_health()` | In-process snapshot dict: `loaded`, `model_version`, `cv_mae`, last predict latency, totals (calls, high-confidence) since process start. The corner-check endpoint can expose this via a sibling `/health` route. |
| `pipeline_events` event names | `elevation_predictor.predicted` (per call: predicted_z, dsm_z_bilinear, drift_m, confidence, duration), `elevation_predictor.fallback` (reason) |

## Feature design notes

The 20-feature vector mirrors the columns
`build_elevation_training_set.py` writes (everything between the
identifier columns and the target columns). The CSV header MUST stay
in lockstep with `model.FEATURE_COLUMNS`.

| Feature | Why |
|---|---|
| col_px, row_px | Pixel coords on the source raster — lets the model learn raster-edge artifacts |
| panel_corner_count | Calibrates plane-fit features against panel complexity |
| patch_mean / std / min / p20 / p50 / p80 / max | DSM patch summary around the click — robust shape signal vs single-pixel sampling |
| dsm_z_bilinear | The naive sample we're trying to beat; also anchors the confidence proxy |
| dsm_z_robust | Patch-robust sample — strong baseline on contaminated tiles |
| plane_normal_x / y / z, plane_d | RANSAC plane fit for the panel — current production prediction |
| plane_rms_residual | Plane-fit quality — high RMS means the plane is unreliable, model should weight DSM more |
| siblings_z_median, siblings_z_std | Z stats from the same panel's other corner clicks — neighbours constrain the answer |
| meters_per_px | Raster scale — features that encode pixel distances need it to generalise across projects |

Adding features later requires retraining and bumping
`MODEL_VERSION` in `model.py` — the predict.py loader will refuse to
score rows whose dict is missing any FEATURE_COLUMNS entry.
