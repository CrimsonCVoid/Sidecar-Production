"""SAM auto-panel service.

Phase 2 of the pipeline upgrade. Runs as a SEPARATE FastAPI process
(NOT mounted into roof_pipeline.api.main:app) on a GPU-equipped host
because SAM ViT-H sits at ~24 GB resident on a CUDA device.

The web proxy in app/api/v2/projects/[id]/auto-panels/route.ts hits this
service directly. The existing mmr-api sidecar never talks to SAM.

Boundaries:
  - main.py     : FastAPI app + POST /api/v2/auto-panels/{sample_id}
  - service.py  : model load (cached in module scope) + inference
  - footprint_projection.py : WGS84 -> image-pixel math, ported from
    lib/footprint-projection.ts so frontend and backend agree on which
    pixels are "inside the footprint".
"""
