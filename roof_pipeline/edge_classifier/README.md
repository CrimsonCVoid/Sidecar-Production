# Edge Classifier

Phase 4 of the pipeline upgrade. Replaces the geometric
`_classify_panel_edges` rule in `shop_drawings.py` with an XGBoost
classifier trained on every edge type any user has ever saved.

## Status

Scaffold only. The model file `artifacts/model.json` does not ship
in the repo. Until it's produced and the env flag is flipped, the
existing rule path runs unchanged.

## Pipeline

1. **Extract training data** (web repo):
   ```bash
   cd ~/WebsiteDesign-MMR
   export DATABASE_URL="postgres://..."
   python3 scripts/build_edge_training_set.py
   ```
   Writes `data/edge_training/edges.csv`. One row per labeled edge
   across every project. Skip-listed for git via `.gitignore`.

2. **Train**:
   ```bash
   cd ~/Mymetalrooferbackupmvp-firstcommit
   pip install xgboost pandas numpy scikit-learn
   python3 -m roof_pipeline.edge_classifier.train \
       --data ../WebsiteDesign-MMR/data/edge_training/edges.csv \
       --out roof_pipeline/edge_classifier/artifacts \
       --folds 5
   ```
   Writes `artifacts/model.json` + `artifacts/label_encoder.json`.
   Prints fold accuracies and a final classification report.

3. **Deploy**:
   ```bash
   ssh root@209.97.156.206
   cd /opt/mmr-api/app && git pull
   # Either commit artifacts/ to the repo (preferred for traceable
   # production rollouts) or rsync them in by hand for testing:
   #   rsync artifacts/* root@209.97.156.206:/opt/mmr-api/app/roof_pipeline/edge_classifier/artifacts/
   systemctl restart mmr-api
   ```

4. **Enable**:
   Add `EDGE_CLASSIFIER_ENABLED=true` to `/opt/mmr-api/app/.env` and
   restart `mmr-api`. Without that env var, `classifier_available()`
   returns False and the existing rule path runs.

## How the integration falls back

`shop_drawings.roof_dict_from_pipeline` calls
`predict_edges(pid, poly, plane, polygons, planes)` first. The
classifier returns a list of `(label, confidence)` tuples, one per
edge. Per the upgrade spec:

- **High-confidence edges** (default threshold 0.6): use the model's
  prediction.
- **Low-confidence edges**: model returns `("", confidence)` and the
  caller falls back to `_classify_panel_edges` for THAT edge only,
  not the whole panel.
- **Model unavailable** (artifacts missing, env flag off, xgboost not
  installed): `predict_edges` returns `None`; the caller falls back
  entirely to the rule.

User edge_types from `panels.json` (set in the labeler) ALWAYS win,
regardless of model output. That's existing behavior preserved.

## Acceptance for production rollout

Per the upgrade prompt's Phase 4 section:

> With the flag on, three benchmark projects produce PDFs that either
> match the benchmark or differ in ways we can manually verify as
> improvements.

To test:
```bash
EDGE_CLASSIFIER_ENABLED=true \
INTERNAL_API_KEY=... \
python3 ../WebsiteDesign-MMR/scripts/regression_check.py
```

A failure here doesn't necessarily mean roll back — the differences
might be improvements. Visually compare the PDFs in
`tests/benchmarks/pdfs/` against fresh exports before deciding.

## Feature design notes

The 17-feature vector is designed to capture every signal the rule
classifier uses, plus a few it can't:

| Feature | Why |
|---|---|
| edge_length_ft | Eaves are usually long, hip caps short |
| edge_dx, edge_dy | Direction (panel-local) — eaves run along one axis |
| edge_z_min, edge_z_max, edge_z_delta | Eave = low Z; ridge = high Z; hip = both, sloped |
| panel_area_sqft | Calibrates length features against panel size |
| panel_normal_xyz, panel_slope_rise | Steep panel = different priors than low-slope |
| edge_is_horizontal | Hard signal for eave vs ridge vs hip |
| shared_with_neighbor | Ridges/hips/valleys are always shared; eaves aren't |
| neighbor_normal_dot | Two parallel panels meeting = ridge; perpendicular = transition |

Adding features later requires retraining and bumping the version
string in `label_encoder.json` — the predict.py loader will warn but
still attempt inference if columns mismatch.
