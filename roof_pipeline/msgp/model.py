"""Multi-Scale Generic Pretraining (MSGP) segmenter — research scaffold.

Architecture mirrors the public description of the Nature paper:
  - Multi-scale convolutional backbone (3 scales, simple ConvNeXt-ish blocks)
  - Transformer attention layer over flattened feature maps
  - Refinement decoder (skip connections + ConvTranspose2d)

Implemented with vanilla PyTorch primitives only — no copied code from
the paper's reference repo (CC-BY-NC-ND, incompatible with commercial
use).

This is a STARTER implementation, not a faithful reproduction. The
goal is to have something runnable end-to-end so we can sanity-check
the training loop and the data pipeline. Architectural fidelity is a
follow-up once we have baseline numbers.
"""

from __future__ import annotations

import torch
from torch import nn


class _ConvBlock(nn.Module):
    """Two 3x3 convs + GroupNorm + GELU. Building block for the encoder."""

    def __init__(self, in_ch: int, out_ch: int) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1),
            nn.GroupNorm(num_groups=8, num_channels=out_ch),
            nn.GELU(),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.GroupNorm(num_groups=8, num_channels=out_ch),
            nn.GELU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.body(x)


class _AttentionBlock(nn.Module):
    """Single multi-head self-attention over flattened feature maps."""

    def __init__(self, channels: int, heads: int = 4) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(channels)
        self.attn = nn.MultiheadAttention(
            embed_dim=channels, num_heads=heads, batch_first=True,
        )
        self.ffn = nn.Sequential(
            nn.LayerNorm(channels),
            nn.Linear(channels, channels * 4),
            nn.GELU(),
            nn.Linear(channels * 4, channels),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, C, H, W) -> (B, H*W, C) for attention
        b, c, h, w = x.shape
        flat = x.flatten(2).transpose(1, 2)
        normed = self.norm(flat)
        attended, _ = self.attn(normed, normed, normed)
        flat = flat + attended
        flat = flat + self.ffn(flat)
        return flat.transpose(1, 2).reshape(b, c, h, w)


class MSGPSegmenter(nn.Module):
    """Multi-scale roof-panel segmenter.

    Input:  (B, 4, H, W) — RGB + DSM elevation channel
    Output: (B, 1, H, W) — sigmoid-pre-activation logits for "is roof
    panel"

    For multi-class (per-panel-id) segmentation, swap the head's output
    channels and the loss in train.py.
    """

    def __init__(self, in_channels: int = 4, base_channels: int = 32) -> None:
        super().__init__()
        c1, c2, c3 = base_channels, base_channels * 2, base_channels * 4

        # Encoder, three scales
        self.enc1 = _ConvBlock(in_channels, c1)
        self.pool1 = nn.MaxPool2d(2)
        self.enc2 = _ConvBlock(c1, c2)
        self.pool2 = nn.MaxPool2d(2)
        self.enc3 = _ConvBlock(c2, c3)

        # Bottleneck: attention over the deepest feature map
        self.bottleneck_attn = _AttentionBlock(c3, heads=4)

        # Decoder, with skip connections
        self.up2 = nn.ConvTranspose2d(c3, c2, 2, stride=2)
        self.dec2 = _ConvBlock(c3, c2)  # c2 from skip + c2 from up
        self.up1 = nn.ConvTranspose2d(c2, c1, 2, stride=2)
        self.dec1 = _ConvBlock(c2, c1)

        # Output head
        self.head = nn.Conv2d(c1, 1, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool1(e1))
        e3 = self.enc3(self.pool2(e2))
        b = self.bottleneck_attn(e3)
        d2 = self.dec2(torch.cat([self.up2(b), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))
        return self.head(d1)
