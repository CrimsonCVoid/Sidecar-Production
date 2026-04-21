# 3DEP LiDAR vs Google Solar DSM benchmark

Standalone spike that answers one question: **does a USGS 3DEP LiDAR DSM
produce meaningfully better plane fits than Google Solar's photogrammetric
DSM for residential roofs in the Triangle / Apex NC service area?**

This directory is self-contained. It imports `fit_plane` and related helpers
from the live `roof_pipeline` package **without modifying them**. It adds
exactly one schema change upstream: a nullable `source` column on
`training_samples`, via the migration in
`/Users/carterbrady/WebsiteDesign-MMR/migrations/020_add_source_to_training_samples.sql`.

## Workflow

For each test address, you do this:

```bash
# 1. Pull the 3DEP DSM, rasterize to a Google-Solar-shaped GeoTIFF,
#    upload to Supabase as a new training_samples row (source='3dep').
python benchmarks/3dep_vs_google/fetch_3dep.py \
  --address "123 Main St, Apex NC" \
  --radius 75 --resolution 0.1
python benchmarks/3dep_vs_google/upload_sample.py \
  --input-dir benchmarks/3dep_vs_google/output/<slug>/

# 2. Pull the same address through the production Google Solar ingest
#    so the twin is exactly what a customer would see.
python benchmarks/3dep_vs_google/fetch_google_twin.py \
  --address "123 Main St, Apex NC"

# 3. Label both samples in the existing UI (identical panel topology).
#    Each upload step prints the exact URL to open.
#    -> http://localhost:3000/labeling/<sample_id>

# 4. Once both are labeled, run the comparison.
python benchmarks/3dep_vs_google/compare.py \
  --google-sample-id <uuid1> \
  --3dep-sample-id   <uuid2> \
  --output-report benchmarks/3dep_vs_google/results/
```

The final step writes a Markdown report with per-panel deltas and a verdict
line: *"3DEP wins"*, *"Google wins"*, or *"Mixed"*.

## Setup

1. **Install benchmark-only deps** in the same virtualenv as roof_pipeline:

   ```bash
   pip install -r benchmarks/3dep_vs_google/requirements.txt
   ```

   Adds `laspy[lazrs]`, `pyproj`, `tqdm`. No system libraries required —
   LAZ reads go through the pure-Python `lazrs` backend.

2. **Apply the migration** once, against your Supabase instance:

   ```sql
   -- see /Users/carterbrady/WebsiteDesign-MMR/migrations/020_add_source_to_training_samples.sql
   ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS source TEXT;
   ```

   Apply it via the migration runner the WebsiteDesign-MMR repo already uses,
   or paste into the Supabase SQL editor once.

3. **Make sure the Next.js labeler is running** on port 3000 (inline
   `./frontend` app, not WebsiteDesign-MMR — only that app serves the
   `/labeling/<sample_id>` route).

   ```bash
   cd frontend && npm run dev
   ```

4. **Make sure the FastAPI sidecar is running** on port 8000:

   ```bash
   uvicorn roof_pipeline.api.main:app --reload --host 127.0.0.1 --port 8000
   ```

   The Google-twin fetcher hits `POST /api/solar/ingest` via loopback,
   which triggers the `dev_allow_unauth` bypass already configured in
   `.env` for this repo.

## Files in this directory

| Script | Phase | Purpose |
|---|---|---|
| `common.py` | shared | Deterministic sample IDs, UTM inference, env loader |
| `fetch_3dep.py` | 1 | Geocode → TNM query → download LAZ → rasterize → write GeoTIFFs |
| `upload_sample.py` | 2 | Upload the three GeoTIFFs + insert `training_samples` row |
| `fetch_google_twin.py` | 3 | Call the production `/api/solar/ingest` + flag `source='google'` |
| `compare.py` | 4 | Pull both label sets, re-run the plane fit, emit Markdown delta |
| `run_batch.py` | 5 | Optional — runs phases 1-4 over a CSV of addresses |
| `requirements.txt` | - | Isolated deps |

Also:

| Directory | Purpose |
|---|---|
| `output/<slug>/` | One subdir per fetched 3DEP sample. Ignored by git. |
| `results/` | Markdown comparison reports, one per run. |
| `ground_truth/<slug>.json` | Optional MRQ ground truth (per-panel slope/area). |

## Ground-truth JSON schema (optional, Phase 4)

If `ground_truth/<address_slug>.json` exists when you run `compare.py`, the
report gains a "vs ground truth" column per panel. Shape:

```json
{
  "address": "123 Main St, Apex NC",
  "source": "MRQ tape-measure survey 2026-03-18",
  "panels": [
    {"id": 1, "slope_rise_over_12": 4.0, "area_sqft": 312.0},
    {"id": 2, "slope_rise_over_12": 4.0, "area_sqft": 148.0}
  ]
}
```

Missing file → skipped silently, no error.

## What "wins" means

- **3DEP wins** — mean RMS-residual reduction >40% AND no slope Δ >2/12 in
  the wrong direction AND zero panels triggering the >18/12 sanity warning
  on the 3DEP side.
- **Google wins** — 3DEP RMS is not meaningfully lower (<20% reduction) OR
  3DEP introduces slope errors Google didn't have.
- **Mixed** — anything else. The report surfaces *which* roof topologies
  favor which source so the batch run can be mined for patterns.

## What this spike explicitly does not do

- No changes to `roof_pipeline/api/`, `roof_pipeline/snapping*`,
  `roof_pipeline/cutsheets*`, `roof_pipeline/mesh*`, `roof_pipeline/planes*`.
  The benchmark imports `fit_plane` from `roof_pipeline.planes` — that's it.
- No production 3DEP fetcher. That's a follow-up milestone if the spike wins.
- No changes to the labeling UI.
- No new top-level production dependencies.
