"""Phase 4: edge-classifier ops surface.

  GET /api/v2/edge-classifier/health   → load + predict stats

Auth: internal-key only. There is no browser-side use case here; ops
hits this from the web v2 proxy or via curl with the shared secret.
The route is intentionally cheap — no model work, just a status
snapshot — so it's safe to poll from a dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..edge_classifier import classifier_health
from .deps import Principal, require_principal

router = APIRouter()


@router.get("/health")
async def get_health(
    _principal: Principal = Depends(require_principal),
) -> dict:
    """Snapshot of the edge classifier's load + per-process prediction
    stats. Counters reset on process restart. Either auth path
    (internal API key or Supabase JWT) is accepted — ops dashboards use
    the JWT path, the web v2 proxy uses the shared secret."""
    return classifier_health()
