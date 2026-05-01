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


def _build_loaders(data_dir: Path, batch_size: int):
    # Stub — real loader builds (RGB+DSM, mask) pairs.
    # Returns (train_loader, val_loader). Implement once we wire data.
    raise NotImplementedError(
        "Data loader stub. Implement after wiring training_labels -> mask "
        "assembly per the README. WHU public dataset can warm-start without "
        "any private-data dependency."
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
