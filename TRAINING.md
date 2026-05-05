# Training Pipeline

End-to-end training of the two ML models that consume saved labeled +
polygonal data from Supabase:

| Phase | Model | Architecture | Where it runs |
|-------|-------|-------------|----------------|
| **4** | Edge type classifier | XGBoost multiclass | CPU, ~30s on small set |
| **5** | Panel segmenter (MSGP) | PyTorch U-Net + attention | GPU strongly recommended |

Both pull data from the live Supabase project (`training_labels` +
`training_samples` + Storage). Both data extractors are **resumable** —
re-run after labeling more projects and they'll process only the new
sample IDs.

## Quickstart — train everything end-to-end

```bash
# Required env (live values are in /opt/mmr-api/app/.env on the droplet):
export SUPABASE_URL=https://psdyxmxledojrqvzmdek.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=...

# Smoke test the wiring (5 samples, 1 epoch). ~2 minutes.
./scripts/run_training_pipeline.sh all --smoke

# Real run (every labeled sample). Edge: ~30s. MSGP: minutes-to-hours,
# scaled by labeled-sample count, GPU optional but heavy without one.
./scripts/run_training_pipeline.sh all
```

Or just one model:

```bash
./scripts/run_training_pipeline.sh edge       # Phase 4 only
./scripts/run_training_pipeline.sh msgp       # Phase 5 only
./scripts/run_training_pipeline.sh edge --smoke
```

## Phase 4 — Edge classifier (XGBoost, CPU)

**Data extractor:** [`scripts/build_edge_training_set.py`](scripts/build_edge_training_set.py)

For every `training_labels` row with at least one labeled edge:

1. Downloads the matching DSM from Supabase Storage.
2. Rasterizes the panels onto an integer mask.
3. Fits a plane per panel via the same `fit_plane_ransac` the live
   pipeline uses.
4. Lifts each clicked 2D corner to its plane → 3D polygons.
5. Builds a shared-edge neighbor index across panels.
6. Runs `edge_classifier.predict._featurize_edge` (the **live inference
   feature path** — no train-vs-serve drift) to produce a feature
   vector per labeled edge.
7. Writes one CSV row per edge with the metadata + 17 features +
   normalized label.

Label normalization: maps the labeler's edge-type string to one of
`{eave, rake, ridge, hip, valley, hip_cap, wall}` (the trainer's
canonical class set). New 2026-05 codes (`transition`, `high_side`,
`flying_gable`, `chimney_flashing`) are skipped — too few samples to
learn from yet, the rule-based classifier handles them.

**Trainer:** [`roof_pipeline/edge_classifier/train.py`](roof_pipeline/edge_classifier/train.py)

XGBoost multiclass with stratified k-fold CV (default k=5), prints
held-out accuracy and per-class precision/recall, saves `model.json`
and `label_encoder.json` into `roof_pipeline/edge_classifier/artifacts/`.

**Inference:** [`roof_pipeline/edge_classifier/predict.py`](roof_pipeline/edge_classifier/predict.py)

Loaded via `load_model()` on first call when `EDGE_CLASSIFIER_ENABLED=true`.
Mounts under `/api/v2/edge-classifier/health` for ops introspection.

**Flag-gated:** the classifier is OFF by default in prod (rule-based
fallback runs). Flip on by setting `EDGE_CLASSIFIER_ENABLED=true` in
`.env` and restarting `mmr-api` once you trust the held-out numbers.

### Run it manually

```bash
# 1. Extract
python3 scripts/build_edge_training_set.py \
  --out data/edge_training/edges.csv

# 2. Inspect
head -3 data/edge_training/edges.csv
wc -l data/edge_training/edges.csv

# 3. Train
python3 -m roof_pipeline.edge_classifier.train \
  --data data/edge_training/edges.csv \
  --out roof_pipeline/edge_classifier/artifacts \
  --folds 5
```

## Phase 5 — Panel segmenter (PyTorch, GPU recommended)

**Data extractor:** [`scripts/msgp_prepare_data.py`](scripts/msgp_prepare_data.py)

For every labeled sample, downloads RGB + DSM, normalizes both, builds
a binary roof-panel mask by rasterizing the polygons, writes:

```
<out>/<sample_id>.input.npy   float32 (4, H, W)   RGB[0..1] + DSM (mean=0,std=1)
<out>/<sample_id>.mask.npy    uint8   (H, W)      binary roof-panel mask
```

**Trainer:** [`roof_pipeline/msgp/train.py`](roof_pipeline/msgp/train.py)

PyTorch Lightning loop. 90/10 train/val split, BCEWithLogitsLoss,
AdamW + cosine schedule. Saves checkpoints under `--out`.

**Architecture:** [`roof_pipeline/msgp/model.py`](roof_pipeline/msgp/model.py)

Three-scale ConvNeXt-ish encoder, multi-head attention bottleneck,
skip-connected decoder. ~1.3M params at default settings — small enough
to fit a 24GB GPU at batch size 8.

### Deploying to the GPU host

The droplet at `209.97.156.206` is CPU-only (~2 vCPU, 2 GB RAM).
Phase 5 training there is slow but possible for smoke tests.
For real runs use the SAM-service GPU host at `154.54.100.231`:

```bash
# On a workstation with SSH access:
ssh root@154.54.100.231
cd /path/to/Sidecar-Production
git pull origin main
pip install torch pytorch-lightning numpy pillow rasterio supabase opencv-python

# Source env from the droplet's copy of .env (same Supabase project):
scp root@209.97.156.206:/opt/mmr-api/app/.env .env.training
set -a; source .env.training; set +a

./scripts/run_training_pipeline.sh msgp
```

After training, copy the checkpoint back into the sidecar's artifacts
path on the prod droplet:

```bash
scp data/msgp/checkpoints/<best>.ckpt \
    root@209.97.156.206:/opt/mmr-api/app/roof_pipeline/msgp/artifacts/model.ckpt
ssh root@209.97.156.206 systemctl restart mmr-api
```

## Promotion — turning a trained model on in prod

1. Run the held-out evaluation suite (`roof_pipeline/msgp/evaluate.py` or
   the CV report from `edge_classifier.train`).
2. Compare against the existing baseline. Refuse to promote if metrics
   regressed against the rule-based / random baseline.
3. SCP the artifact into `/opt/mmr-api/app/roof_pipeline/{edge_classifier,msgp}/artifacts/`.
4. Set the feature flag in the droplet's `.env`:
   - Edge classifier: `EDGE_CLASSIFIER_ENABLED=true`
   - MSGP: see `roof_pipeline/msgp/README.md` for the integration flag (still scaffold).
5. `systemctl restart mmr-api`.

## Iterating

- **Add more labeled data** — the data extractors are resumable. Re-run
  the pipeline after a labeling batch and the new samples flow in.
- **Add new features** — edit `_featurize_edge` in
  `roof_pipeline/edge_classifier/predict.py`. The trainer reads
  `FEATURE_COLUMNS` from that file at import time, so train and serve
  can never drift.
- **Add new edge types** — extend `LABEL_NORMALIZE` in
  `scripts/build_edge_training_set.py` and `LABEL_CLASSES` in
  `roof_pipeline/edge_classifier/train.py`. Re-run the pipeline.

## Cost / footprint

| Component | Cost |
|---|---|
| Edge data extract | ~1s per labeled sample (DSM download dominates) |
| Edge train (CPU) | ~30s for hundreds of samples / thousands of edges |
| MSGP data extract | ~3-5s per sample (RGB+DSM download + decode) |
| MSGP train (1× A100) | ~1-2 min/epoch on 100 samples; scales linearly |
| Disk | ~5 MB per MSGP sample (.input + .mask), trivial for edge CSV |
