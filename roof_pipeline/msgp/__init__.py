"""MSGP-style segmenter (Phase 5 of the pipeline upgrade).

Research scaffold ONLY. Nothing here is wired into the production
pipeline. No endpoint exposes it. The training pipeline is documented
in README.md so it can be reproduced on the Thunder Compute A100.

Per the upgrade prompt's hard constraint #4, this module reimplements
the multi-scale + transformer + decoder architecture from the Nature
paper using only public PyTorch primitives. Do not import from the
paper's reference repo (license is CC-BY-NC-ND 4.0).
"""

__version__ = "0.0.1-scaffold"
