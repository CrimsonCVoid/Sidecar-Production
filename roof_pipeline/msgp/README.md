# MSGP Segmenter — Research Scaffold

Phase 5 of the pipeline upgrade. Multi-scale + attention + decoder
roof-panel segmenter, reimplemented with public PyTorch primitives
only (the Nature paper's reference repo is CC-BY-NC-ND 4.0,
incompatible with our commercial use per the upgrade prompt's hard
constraint #4).

**Status: scaffold only.** No production endpoint. No labeler
integration. No swap-in until evaluation says it beats SAM on our
internal validation set.

## Files

| File | What |
|---|---|
| `model.py` | `MSGPSegmenter` — encoder (3 ConvBlock + 2 MaxPool) + attention bottleneck + decoder (2 ConvTranspose2d with skip connections) + 1-channel logits head |
| `train.py` | PyTorch Lightning training loop. Includes a `--smoke` flag that pushes a random batch through the model to verify the wiring without any data. |
| `evaluate.py` | Runs a checkpoint on a held-out set. Stub for the loop; metrics format is locked to match SAM eval. |

## Reproduce a smoke run

On any box with PyTorch installed (CPU is fine):

```bash
cd ~/Mymetalrooferbackupmvp-firstcommit
pip install torch pytorch-lightning numpy
python3 -m roof_pipeline.msgp.train --data /tmp --out /tmp/msgp_runs --smoke
```

Should print something like:

```
Smoke OK. logits=(2, 1, 256, 256), loss=0.69xx
```

That confirms the architecture assembles and gradients flow, with no
data dependency.

## Reproduce a real run on Thunder Compute A100

1. SSH to the A100:
   ```bash
   ssh ubuntu@154.54.100.231       # confirm IP/user with the team
   ```
2. Clone the sidecar repo and install:
   ```bash
   git clone https://github.com/CrimsonCVoid/Mymetalrooferbackupmvp.git
   cd Mymetalrooferbackupmvp
   python3 -m venv venv && source venv/bin/activate
   pip install torch pytorch-lightning numpy pillow rasterio
   ```
3. Build the dataset. Two parts:
   - **Pretraining**: WHU Building Extraction dataset, public download
   - **Fine-tuning**: pull `training_labels.annotations` + matching
     `training_samples.rgb_storage_path` / `dsm_storage_path` from
     Supabase Storage; rasterize each panel polygon to a per-sample
     mask. The data-loader stub in `train._build_loaders` is the spot
     to wire this; it raises NotImplementedError today on purpose.
4. Pretrain on WHU:
   ```bash
   python3 -m roof_pipeline.msgp.train \
       --data /path/to/whu \
       --out runs/pretrain \
       --max-epochs 30
   ```
5. Fine-tune on our data:
   ```bash
   python3 -m roof_pipeline.msgp.train \
       --data /path/to/our_dataset \
       --out runs/finetune \
       --max-epochs 50
   ```
6. Evaluate:
   ```bash
   python3 -m roof_pipeline.msgp.evaluate \
       --checkpoint runs/finetune/lightning_logs/version_0/checkpoints/last.ckpt \
       --data /path/to/our_holdout \
       > eval_results.txt
   ```

## Acceptance criteria

Per the upgrade prompt's Phase 5 acceptance:

- [x] A training run completes end-to-end on a small subset of data
      (smoke test path validates this without data)
- [ ] Evaluation script outputs metrics in a comparable format to
      whatever we are using for SAM evaluation (stub today; real
      metrics come once the data loader is wired)
- [x] README is clear enough that someone else on the team could
      reproduce the run

## Why this is scaffold-not-shipped

The prompt explicitly requires this:

> **No production endpoint. No labeler integration. No swap-in until
> evaluation says it wins.**

The point of Phase 5 is having infrastructure ready so when we want to
experiment we don't lose a week on setup. It's not a tipping point for
production behavior. SAM (Phase 2) handles auto-panels production-side
until and unless this beats it on our held-out set.
