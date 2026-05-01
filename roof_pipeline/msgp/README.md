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
| `evaluate.py` | Runs a checkpoint on a held-out set. Reports pixel IoU + pixel F1 + boundary F1 (with configurable dilation radius) + per-sample latency. JSON output, ready to diff vs a SAM eval run. |

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
   - **Fine-tuning**: use the data-prep script:
     ```bash
     export SUPABASE_URL=https://...
     export SUPABASE_SERVICE_ROLE_KEY=...
     python3 scripts/msgp_prepare_data.py --out data/msgp/train
     # Materialize a holdout split disjoint from train:
     ls data/msgp/train/*.input.npy | sed 's/.*\///; s/.input.npy$//' \
       > /tmp/used_ids.txt
     python3 scripts/msgp_prepare_data.py --out data/msgp/val \
       --exclude-sample-ids /tmp/used_ids.txt --limit 30
     ```
     Each sample becomes a (4, H, W) input.npy + (H, W) mask.npy
     pair under the output dir. The script is resumable — re-running
     skips samples that already have outputs.
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
- [x] Evaluation script outputs metrics in a comparable format to
      whatever we are using for SAM evaluation (pixel IoU + F1 +
      boundary F1 + latency, JSON output)
- [x] README is clear enough that someone else on the team could
      reproduce the run

## Production readiness checklist

These are the gates between "scaffold" and "candidate for replacing or
complementing the SAM auto-panel service":

- [ ] **Real training data** at scale. Phase 4's persistence-bug fix
      means edge_types finally round-trips on saves; same fix
      applies here for the panel masks, but the bigger gate is
      sample count. Aim for at least 200 labeled projects before a
      real fine-tune; today's count is closer to a dozen.
- [ ] **WHU pretraining pass** producing a checkpoint. WHU is public
      so this is a Thunder Compute time decision, not data ops.
- [ ] **Fine-tune** on our data, beating SAM on the holdout's mean
      IoU AND mean boundary F1. Either-or isn't enough — SAM's
      panel-fit story is good but its boundary precision is what
      makes review-mode painful.
- [ ] **Per-class output** (not just binary mask). The current head
      is 1-channel binary "is panel". For drop-in replacement of
      SAM the head needs to emit instance masks (one channel per
      panel id, or an instance-segmentation head). Bigger change
      than the eval/data work.
- [ ] **Production endpoint** mirroring the SAM service skeleton:
      separate FastAPI process on the GPU host, `/api/v2/msgp/segment/
      {sample_id}` writing back to `training_samples.auto_panels` so
      the labeler's review mode picks it up unchanged. systemd unit
      + deploy README mirroring `roof_pipeline/sam_service/`.
- [ ] **License audit**. Phase 5 reimplemented the architecture from
      public PyTorch primitives; verify no upstream WHU pretraining
      checkpoint we use carries non-commercial terms. Trained
      weights become a derivative work of the pretraining data, so
      the data's license bounds the model's.
- [ ] **A/B harness**: shadow-mode the MSGP service alongside SAM in
      the snapshot kickoff path so we collect side-by-side
      `auto_panels` outputs without affecting users. Run for ~2
      weeks of real traffic before any cutover.

## Why this is scaffold-not-shipped

The prompt explicitly requires this:

> **No production endpoint. No labeler integration. No swap-in until
> evaluation says it wins.**

The point of Phase 5 is having infrastructure ready so when we want to
experiment we don't lose a week on setup. It's not a tipping point for
production behavior. SAM (Phase 2) handles auto-panels production-side
until and unless this beats it on our held-out set.
