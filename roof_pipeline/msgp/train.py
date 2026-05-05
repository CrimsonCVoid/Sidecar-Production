"""MSGP training scaffold.

Trains MSGPSegmenter on (RGB+DSM) → roof-panel-mask. PyTorch Lightning
keeps the loop short and lets us swap optimizers/schedulers without
touching the model.

Data assembly (NOT included — out of scope for the scaffold):
  - WHU public dataset for pretraining
  - Our training_samples + training_labels for fine-tuning. The mask
    is built by rasterizing each panel polygon onto a (H, W) tensor.

Run:
    pip install torch pytorch-lightning numpy pillow
    python3 -m roof_pipeline.msgp.train \\
        --data /path/to/dataset \\
        --out /path/to/checkpoints \\
        --max-epochs 50

Reproduces the run on Thunder Compute A100. See README.md.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

LOG = logging.getLogger("msgp.train")


def _build_loaders(data_dir: Path, batch_size: int, val_split: float = 0.1):
    """Build train + val DataLoaders over the .input.npy / .mask.npy
    pairs produced by scripts/msgp_prepare_data.py.

    Layout:
        <data_dir>/<stem>.input.npy   (4, H, W) float32 — RGB[0..1] + norm DSM
        <data_dir>/<stem>.mask.npy    (H, W)    uint8   — binary mask

    Deterministic 90/10 split by sample stem hash so the same split
    survives across runs without an explicit manifest file. Override
    by partitioning <data_dir>/train and <data_dir>/val yourself.
    """
    import hashlib

    import numpy as np
    import torch
    from torch.utils.data import DataLoader, Dataset

    # Solar API tiles vary in size (~400x400 to ~1000x1000 — depends on
    # roof footprint + radius scaling). Resize every sample to a common
    # 256x256 so they batch together. Bilinear for the input, nearest
    # for the mask so we don't synthesize half-pixel labels.
    #
    # Why 256 specifically: the bottleneck attention layer is O(N²) in
    # the spatial size after 2× max-pool. 384 → 96×96 = 9216 tokens →
    # ≈ 22 GB on a single batch on M5 MPS. 256 → 64×64 = 4096 tokens
    # → fits comfortably in 16 GB. Multiple of 16 to keep the pool
    # math clean.
    TARGET_HW = 256

    class _NpyPairDataset(Dataset):
        def __init__(self, paths):
            self.paths = list(paths)

        def __len__(self):
            return len(self.paths)

        def __getitem__(self, idx):
            p = self.paths[idx]
            inp = np.load(p).astype("float32")
            mask = np.load(str(p).replace(".input.npy", ".mask.npy"))
            if mask.ndim == 2:
                mask = mask[None]  # add channel dim

            inp_t = torch.from_numpy(inp).unsqueeze(0)  # (1, C, H, W)
            mask_t = torch.from_numpy(mask).unsqueeze(0).float()  # (1, 1, H, W)
            inp_t = torch.nn.functional.interpolate(
                inp_t, size=(TARGET_HW, TARGET_HW),
                mode="bilinear", align_corners=False,
            ).squeeze(0)
            mask_t = torch.nn.functional.interpolate(
                mask_t, size=(TARGET_HW, TARGET_HW), mode="nearest",
            ).squeeze(0)
            return inp_t, mask_t

    train_dir = data_dir / "train"
    val_dir = data_dir / "val"
    if train_dir.exists() and val_dir.exists():
        train_paths = sorted(train_dir.glob("*.input.npy"))
        val_paths = sorted(val_dir.glob("*.input.npy"))
    else:
        # Hash-based split for cohorts without an explicit manifest.
        all_paths = sorted(data_dir.glob("*.input.npy"))
        if not all_paths:
            raise FileNotFoundError(
                f"No *.input.npy files under {data_dir}. Did you run "
                f"scripts/msgp_prepare_data.py?"
            )
        train_paths, val_paths = [], []
        for p in all_paths:
            digest = int(hashlib.md5(p.stem.encode()).hexdigest(), 16) % 1000
            (val_paths if digest < val_split * 1000 else train_paths).append(p)

    LOG.info(
        "msgp data: %d train + %d val", len(train_paths), len(val_paths)
    )
    train_ds = _NpyPairDataset(train_paths)
    val_ds = _NpyPairDataset(val_paths)
    # num_workers=0 — keeps the local Dataset picklable on Python 3.13+
    # (where spawn-context worker startup tries to pickle the class
    # itself), and at 116 samples the loader isn't the bottleneck.
    return (
        DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0),
        DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0),
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-epochs", type=int, default=50)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--smoke", action="store_true",
                    help="Run a single random batch through the network "
                         "to verify the model + loss assemble. No data.")
    args = ap.parse_args()

    try:
        import torch
        import pytorch_lightning as pl
    except ImportError as e:
        LOG.error("Missing deps. `pip install torch pytorch-lightning`. (%s)", e)
        return 2

    from .model import MSGPSegmenter

    if args.smoke:
        LOG.info("Smoke test: forward + backward on a random batch")
        model = MSGPSegmenter()
        x = torch.randn(2, 4, 256, 256)
        y = (torch.rand(2, 1, 256, 256) > 0.5).float()
        logits = model(x)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, y)
        loss.backward()
        LOG.info("Smoke OK. logits=%s, loss=%.4f", tuple(logits.shape), loss.item())
        return 0

    train_loader, val_loader = _build_loaders(args.data, args.batch_size)

    class _Lit(pl.LightningModule):
        def __init__(self) -> None:
            super().__init__()
            self.net = MSGPSegmenter()
            self.lr = args.lr

        def forward(self, x):
            return self.net(x)

        def training_step(self, batch, _):
            x, y = batch
            logits = self.net(x)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, y)
            self.log("train_loss", loss, prog_bar=True)
            return loss

        def validation_step(self, batch, _):
            x, y = batch
            logits = self.net(x)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, y)
            self.log("val_loss", loss, prog_bar=True)

        def configure_optimizers(self):
            return torch.optim.AdamW(self.parameters(), lr=self.lr)

    args.out.mkdir(parents=True, exist_ok=True)
    trainer = pl.Trainer(
        max_epochs=args.max_epochs,
        default_root_dir=str(args.out),
        log_every_n_steps=10,
    )
    trainer.fit(_Lit(), train_loader, val_loader)
    LOG.info("Saved checkpoints to %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
