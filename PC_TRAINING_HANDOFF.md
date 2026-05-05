# PC Training Handoff

> **You are the PC Claude session.** This document is the full state-of-the-world
> for training the MMR ML pipeline. Read it top-to-bottom before doing anything
> else — it captures every constraint we hit on the M5 laptop, what numbers
> we got, what's broken, what's only half-built, and exactly what to do next
> on the RTX 3060 / Ryzen 7 7700X box.

## Hardware target

- **GPU**: RTX 3060, **12 GB GDDR6 VRAM**, ~13 TFLOPS FP32, full CUDA support
- **CPU**: Ryzen 7 7700X, 8 cores / 16 threads
- **RAM**: 64 GB
- **vs prior M5 laptop**: ~3× faster, **CUDA kernels + dedicated VRAM unlock larger batches and resolutions that OOM'd on MPS**.

## TL;DR — what's already trained, what to do next

| Model | Status | Score | Bottleneck |
|---|---|---|---|
| Edge classifier (XGBoost) | ✅ Trained, artifact in repo | 82.93% ± 2.66% CV | Class imbalance; need more "wall" labels |
| MSGP segmenter (PyTorch) | ✅ Trained on M5, ckpt at `roof_pipeline/msgp/artifacts/model.ckpt` | **IoU 0.601 mean / 0.736 median** on 15-sample val | Capped at 256×256 + no augmentation due to M5 VRAM |
| Auto-segment inference path | 🟡 Half-built — `roof_pipeline/msgp/predict.py` exists | n/a | API route + UI button are TODO (see below) |

**The single biggest win you can ship on the 3060**: re-train MSGP at higher resolution
with random-crop augmentation. ~40 lines of code, expected IoU jump from 0.60 →
0.75+ before adding any new labeled data.

## What was done on the M5

### Edge classifier — done, ship-ready
- Data extractor: `scripts/build_edge_training_set.py`
- Trainer: `roof_pipeline/edge_classifier/train.py` (XGBoost, 5-fold CV)
- Artifact: `roof_pipeline/edge_classifier/artifacts/{model.json, label_encoder.json}`
- Held-out CV mean accuracy: **82.93% ± 2.66%** across 5 classes
  (eave, rake, ridge, hip, valley). Wall dropped (only 14 samples).
- Per-class metrics in the train log; not a confusion matrix yet but the
  printed `classification_report` covers it.

**To promote:** SCP both JSON files to
`/opt/mmr-api/app/roof_pipeline/edge_classifier/artifacts/` on the droplet,
add `EDGE_CLASSIFIER_ENABLED=true` to its `.env`, restart `mmr-api`. The
inference path (`roof_pipeline/edge_classifier/predict.py`) is already
wired into the live pipeline behind the flag.

### MSGP segmenter — trained, but not great yet
- Data extractor: `scripts/msgp_prepare_data.py` (already existed, works)
- Trainer: `roof_pipeline/msgp/train.py`
- Inference helper: `roof_pipeline/msgp/predict.py` (NEW, just added)
- Architecture: `roof_pipeline/msgp/model.py` — multi-scale ConvNeXt-ish
  encoder + multi-head attention bottleneck + skip-connected decoder, 666K params
- Trained on M5 MPS: 25 epochs, batch 4, 256×256, 101 train / 15 val,
  3 min 20 sec wall-clock
- **Final losses**: train 0.108, val 0.122 BCE
- **Real metrics on val set @ threshold 0.5:**
  - Mean IoU: **0.601** (median 0.736, range 0.0 – 0.948)
  - Precision: 0.901 (very confident when it predicts panel)
  - Recall: 0.678 (under-predicts — misses ~32% of true panels)
  - F1: 0.675
- 12/15 val samples produced usable predictions; 3 produced nothing
  (IoU = 0.0 on those — likely the rare/weird ones)

### Why we ended up at 256×256 — the constraint you don't have

Self-attention is **O(N²)** in spatial tokens after the encoder. The
bottleneck attention layer is at input/4 spatial size:

| Input size | Bottleneck size | Attention tokens | Attention matrix (4 heads, fp32) |
|---|---|---|---|
| 256×256 | 64×64 | 4,096 | ~256 MB / sample |
| 384×384 | 96×96 | 9,216 | ~1.3 GB / sample |
| 512×512 | 128×128 | 16,384 | ~4.1 GB / sample |
| 1000×1000 | 250×250 | 62,500 | **~62 GB / sample** — won't fit anywhere |

M5 OOM'd at batch 8 / 384×384 (saw 22 GB allocated, max 30 GB before kill).
Fell back to batch 4 / 256×256 to fit. **3060 fits 384×384 easily,
512×512 comfortably; 1000×1000 still impossible without architecture
changes (see Recipe C below).**

### Other M5-specific concessions in the code

| File | Hack | Why |
|---|---|---|
| `roof_pipeline/msgp/train.py` `_NpyPairDataset` | `num_workers=0` on both DataLoaders | Local dataset class can't pickle for spawn-context workers on Python 3.13+. On the 3060 with multi-process workers you may want `num_workers=8` for faster I/O, but it requires moving the Dataset class to module scope. |
| `roof_pipeline/msgp/train.py` `_NpyPairDataset.__getitem__` | Bilinear resize to `TARGET_HW = 256` | Solar tiles vary 400×400 – 1000×1000; can't batch variable shapes. **THIS is what to change first on the 3060.** See Recipe B. |

## What's half-built — the auto-segment button

User asked for a "Predict polygons" button visible only to MMR test
accounts (`test@mymetalroofer.com`, `testdev@mymetalroofer.com`). Goal:
labeler tab gets a button → clicks → calls a new endpoint → loads
predicted polygons into the labeler-store as a starting point the user
can then refine.

**Done:** `roof_pipeline/msgp/predict.py` —
- `load_model(path)` — singleton, idempotent
- `predict_polygons(rgb_array, dsm_array, threshold=0.5)` — runs the
  trained model, vectorizes the binary mask via cv2.findContours +
  Ramer-Douglas-Peucker simplification, returns polygons in **native
  pixel coords** (already upsampled back from 256×256)
- `auto_segment_health()` — surface for future health endpoint
- Gated behind `MSGP_AUTO_SEGMENT_ENABLED` env flag

**TODO — pick up here:**

1. **Sidecar API route** — `roof_pipeline/api/auto_segment.py`:
   - `POST /api/v2/auto-segment/{sample_id}` — auth gate via `require_principal`
   - Reuse `verify_sample_access(read_only=True)` so capturers + owners can call it
   - Download `rgb_storage_path` + `dsm_storage_path` from Supabase Storage
   - `from roof_pipeline.msgp.predict import predict_polygons` → run
   - Return `{ polygons: list[list[[x, y]]] }`
   - Mount in `roof_pipeline/api/main.py`: `app.include_router(auto_segment_router, prefix="/api/v2/auto-segment")`
   - Set `MSGP_AUTO_SEGMENT_ENABLED=true` in droplet `.env` after promoting artifact

2. **Website proxy route** — `app/api/projects/[id]/auto-segment/route.ts`:
   - POST handler, auth via `createSupabaseServerClient`
   - **Test-account gate**: refuse unless caller's email is in the allowlist
     `['test@mymetalroofer.com', 'testdev@mymetalroofer.com']` OR
     `users.is_training_capturer = true`
   - Forward request to sidecar `/api/v2/auto-segment/{id}` with
     `X-Internal-API-Key` header
   - Return polygons to the client

3. **UI button** — in `components/labeling/LabelingWorkspace.tsx`:
   - Add a `<Button>` to `EmbeddedLabelingActions` next to Save
   - Show only when caller is a test account (server-passed `isTestAccount` prop)
   - Click → POST `/api/projects/[id]/auto-segment` → on success, replace
     `useLabelerStore.panels` with the predicted polygons
   - Style amber/dashed to make "this is a beta auto-suggestion" obvious

4. **Helper** — `lib/test-accounts.ts`:
   ```ts
   export const TEST_ACCOUNT_EMAILS = new Set([
     "test@mymetalroofer.com",
     "testdev@mymetalroofer.com",
   ]);
   export function isTestAccount(email: string | null | undefined): boolean {
     return !!email && TEST_ACCOUNT_EMAILS.has(email.toLowerCase());
   }
   ```
   Use it in both the page server-component (to decide whether to pass
   `isTestAccount={true}` prop down) and the API route (to gate the
   request).

## Setup on the PC

```bash
git clone git@github.com:CrimsonCVoid/Sidecar-Production.git
cd Sidecar-Production
git pull origin main

# Python 3.11 or 3.12 recommended (3.13+ has the dataloader pickle issue
# I worked around with num_workers=0 — fixable on the PC by moving the
# Dataset to module scope, see Recipe B).
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip

# Install CUDA-built PyTorch — pick the right CUDA version for your driver:
#   nvidia-smi    (see "CUDA Version" top-right)
# Common: cu124, cu121, cu118
pip install torch --index-url https://download.pytorch.org/whl/cu124

pip install pytorch-lightning numpy pandas scikit-learn xgboost \
            rasterio opencv-python supabase pillow shapely matplotlib \
            trimesh mapbox-earcut

# Pull the live Supabase env (live + read-only via service role; same project
# as the droplet uses for inference):
scp root@209.97.156.206:/opt/mmr-api/app/.env .env.training
set -a; source .env.training; set +a
```

Sanity check:

```bash
python3 -c "import torch; print('cuda:', torch.cuda.is_available(), 'device:', torch.cuda.get_device_name(0))"
# Expected: cuda: True device: NVIDIA GeForce RTX 3060
```

## Training recipes — pick by ambition

### Recipe A — Minimum change: bump resolution + batch (15 min)

Just edit two lines of `roof_pipeline/msgp/train.py`:

```python
TARGET_HW = 384       # was 256
# in main(): batch_size default → 8 (was 4 implicitly)
```

```bash
./scripts/run_training_pipeline.sh msgp
```

Expected on 3060 / 116-sample dataset:
- Per-epoch time: ~3 sec
- Full 25 epochs: ~75 sec
- Mean IoU: **estimated 0.65 – 0.70** (small bump from spatial detail)
- Memory: ~6 GB VRAM at batch 8 / 384

### Recipe B — Real win: random-crop augmentation (recommended) ⭐

Lets the model train on **native pixel resolution** without OOMing. Each
sample becomes ~6 effective training instances. Expected IoU jump from
0.60 → **0.75+** on the *same* dataset.

Replace `_NpyPairDataset` in `roof_pipeline/msgp/train.py` (move it to
module scope while you're at it so you can use `num_workers=8`):

```python
import random

class NpyCropDataset(torch.utils.data.Dataset):
    """Random 384×384 crops at training time — preserves native pixel
    resolution while keeping memory bounded. Inference uses sliding-window
    via roof_pipeline.msgp.predict.predict_polygons (already native-res
    aware via the upsample-back-to-original logic)."""

    CROP_HW = 384

    def __init__(self, paths, mode="train"):
        self.paths = list(paths)
        self.mode = mode  # "train" = random crop; "val" = center crop

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx):
        p = self.paths[idx]
        inp = np.load(p).astype("float32")          # (4, H, W)
        mask = np.load(str(p).replace(".input.npy", ".mask.npy"))  # (H, W)
        if mask.ndim == 2:
            mask = mask[None]
        c, h, w = inp.shape

        # If the sample is smaller than CROP_HW, pad with zeros first.
        if h < self.CROP_HW or w < self.CROP_HW:
            pad_h = max(0, self.CROP_HW - h)
            pad_w = max(0, self.CROP_HW - w)
            inp = np.pad(inp, ((0, 0), (0, pad_h), (0, pad_w)))
            mask = np.pad(mask, ((0, 0), (0, pad_h), (0, pad_w)))
            h, w = inp.shape[1], inp.shape[2]

        if self.mode == "train":
            top = random.randint(0, h - self.CROP_HW)
            left = random.randint(0, w - self.CROP_HW)
            # Random horizontal/vertical flip — free 4× augmentation
            do_hflip = random.random() < 0.5
            do_vflip = random.random() < 0.5
        else:
            top = (h - self.CROP_HW) // 2
            left = (w - self.CROP_HW) // 2
            do_hflip = do_vflip = False

        inp_c = inp[:, top:top + self.CROP_HW, left:left + self.CROP_HW]
        mask_c = mask[:, top:top + self.CROP_HW, left:left + self.CROP_HW]
        if do_hflip:
            inp_c = inp_c[:, :, ::-1].copy()
            mask_c = mask_c[:, :, ::-1].copy()
        if do_vflip:
            inp_c = inp_c[:, ::-1, :].copy()
            mask_c = mask_c[:, ::-1, :].copy()

        return torch.from_numpy(inp_c), torch.from_numpy(mask_c.astype("float32"))
```

Then in `_build_loaders` use `NpyCropDataset(train_paths, mode="train")`
and `NpyCropDataset(val_paths, mode="val")`, and bump `num_workers=8`.

Inference at native resolution already works via `predict.py`'s
upscale-mask-then-vectorize path — no changes needed there.

Expected on 3060: ~5 sec/epoch, **IoU 0.72 – 0.80** estimated, 50 epochs
in ~4 min. The big jump comes from (a) native-pixel detail in training
and (b) effective dataset size.

### Recipe C — Architecture change: drop attention, train at full native (experimental)

Pure U-Net at any resolution. Comment out `self.bottleneck_attn(e3)` in
`model.py:107` (replace with `b = e3`). Memory is now O(N), so 1000×1000
batch 4 fits easily on the 3060.

Cost: lose long-range spatial reasoning. At 116 samples that's probably
not doing anything anyway. Worth comparing IoU against Recipe B.

### Recipe D — More data > better architecture

The single biggest gain available isn't on either side of the pipeline:
**get more labeled samples.** Currently 116. Adding capture-mode data
(testdev's silent forks, gated by `vetted=true` after migration 028)
will double or triple the corpus. Once you're at 300+ samples,
Recipe B at 384×384 should land 0.85+ IoU.

After re-training, the new artifact replaces
`roof_pipeline/msgp/artifacts/model.ckpt` and is what the auto-segment
button serves.

## Data quality checklist (worth a one-time pass)

- [ ] **Filter to `vetted=true`**: edit `scripts/msgp_prepare_data.py` and
      `scripts/build_edge_training_set.py` to add a JOIN on `projects`
      and filter `WHERE projects.vetted = true`. Cleaner labels = higher
      IoU at no compute cost.
- [ ] **Class weighting on edge classifier**: `eave` (411) outweighs
      `valley` (159) ~3×. Pass `sample_weight` proportional to
      `total_class_n / class_n` in the XGBoost fit call. Tightens
      per-class recall.
- [ ] **More edge types in the labeler**: 6 new types shipped (transition,
      high_side, flying_gable, sidewall, endwall, chimney_flashing) — the
      training script currently *skips* them as too sparse. Once any has
      ≥ 30 examples, add to `LABEL_NORMALIZE` in
      `scripts/build_edge_training_set.py`.
- [ ] **Boundary-aware loss for MSGP**: BCE over-rewards getting the
      interior right and is lenient on edges. Try Dice loss or
      BCE + boundary-loss combo. A few lines in `_Lit.training_step`.
- [ ] **Color jitter, random rotation** in addition to flips — another
      effective 2-3× dataset multiplier.

## Promotion to prod (when a model is good enough)

```bash
# Edge classifier
scp roof_pipeline/edge_classifier/artifacts/model.json \
    roof_pipeline/edge_classifier/artifacts/label_encoder.json \
    root@209.97.156.206:/opt/mmr-api/app/roof_pipeline/edge_classifier/artifacts/
# Then: ssh root@209.97.156.206
#   echo 'EDGE_CLASSIFIER_ENABLED=true' >> /opt/mmr-api/app/.env
#   systemctl restart mmr-api

# MSGP (after wiring auto-segment API route — see TODOs above)
scp roof_pipeline/msgp/artifacts/model.ckpt \
    root@209.97.156.206:/opt/mmr-api/app/roof_pipeline/msgp/artifacts/
# Then: ssh root@209.97.156.206
#   echo 'MSGP_AUTO_SEGMENT_ENABLED=true' >> /opt/mmr-api/app/.env
#   systemctl restart mmr-api
```

## Where everything lives

| Path | What |
|---|---|
| `scripts/build_edge_training_set.py` | Edge classifier data extractor |
| `scripts/msgp_prepare_data.py` | MSGP data extractor |
| `scripts/run_training_pipeline.sh` | One-button orchestrator (`./scripts/run_training_pipeline.sh all`) |
| `roof_pipeline/edge_classifier/{predict,train}.py` | Edge classifier |
| `roof_pipeline/edge_classifier/artifacts/` | Trained edge model (committed) |
| `roof_pipeline/msgp/{model,train,evaluate,predict}.py` | MSGP segmenter |
| `roof_pipeline/msgp/artifacts/model.ckpt` | First trained MSGP checkpoint (committed, IoU 0.601) |
| `data/msgp/all/` | Extracted training tensors (gitignored) |
| `data/edge_training/edges.csv` | Extracted edge CSV (gitignored) |
| `TRAINING.md` | The original training guide (this is the deeper handoff) |

## Sanity checks before you start

```bash
# 1. Verify checkpoint loads cleanly
python3 -c "
from pathlib import Path
import torch
from roof_pipeline.msgp.model import MSGPSegmenter
ckpt = torch.load('roof_pipeline/msgp/artifacts/model.ckpt', map_location='cpu', weights_only=False)
m = MSGPSegmenter()
clean = {k.replace('net.', '', 1): v for k, v in ckpt['state_dict'].items() if k.startswith('net.')}
m.load_state_dict(clean)
print('Checkpoint loads cleanly. Params:', sum(p.numel() for p in m.parameters()))
"

# 2. Eval the existing checkpoint on whatever val set you have
python3 -m roof_pipeline.msgp.evaluate \
    --checkpoint roof_pipeline/msgp/artifacts/model.ckpt \
    --data data/msgp/all   # uses all samples — for quick sanity only

# 3. Smoke test the auto-segment predict module
python3 -c "
from roof_pipeline.msgp.predict import load_model, predict_polygons, auto_segment_health
import numpy as np
load_model()
print(auto_segment_health())
# Fake input: 800x600 RGB + DSM
rgb = (np.random.rand(600, 800, 3) * 255).astype(np.uint8)
dsm = np.random.rand(600, 800).astype(np.float32) * 5.0
polys = predict_polygons(rgb, dsm)
print(f'Returned {len(polys)} polygons')
"
```

If any of those fails, that's the first thing to fix.

---

## What this commit contains

- `roof_pipeline/msgp/predict.py` — auto-segment inference module (loader +
  vectorizer). API route + UI not yet wired.
- `roof_pipeline/msgp/artifacts/model.ckpt` — first trained MSGP
  checkpoint from the M5 run (IoU 0.601 mean / 0.736 median on 15-sample
  val). 7.7 MB. Replace as you re-train.
- `PC_TRAINING_HANDOFF.md` — this document.

After re-training on the PC, replace `model.ckpt` and update this doc's
TL;DR table with the new numbers.
