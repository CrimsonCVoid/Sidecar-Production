"""Bing Maps Bird's Eye oblique imagery fetcher.

Microsoft's Bing Maps Bird's Eye is one of the only widely-available
sources of true oblique aerial imagery (taken from a plane at ~45°,
not synthesized from a top-down ortho). We use it on the cut-sheet
PDF's orthographic-views page so the contractor sees the actual roof
from N/E/S/W angles rather than a polygon mesh colored from above.

Caveats baked into this module:

  - Microsoft announced Bing Maps API sunset in May 2024. New key
    issuance is limited and existing keys may stop responding without
    notice. Every code path here treats "no image" as a normal outcome,
    not an error.
  - Coverage is patchy. Major US metros are mostly covered; rural and
    smaller-town addresses often aren't. The fetcher returns None per
    direction when Bing has no imagery for that orientation.
  - Bird's Eye images are oblique perspective photos, not georeferenced
    orthos. We don't try to overlay panel polygons on them — the photo
    is a visual reference for the contractor, the dimensions live on
    the other PDF pages.

Env var: BING_MAPS_KEY (read via api.config.Settings).
"""

from __future__ import annotations

import logging
from typing import Iterable

import requests

log = logging.getLogger(__name__)


# Bing Bird's Eye REST endpoint. The center point is "lat,lng", the
# zoomLevel sets how tight the crop is (1=world, 21=detail; 19-20 is
# good for a single roof). orientation is 0/90/180/270 — *the direction
# the camera looks toward*. So orientation=0 means the photo was taken
# from the south looking north, etc.
_BIRDSEYE_URL = (
    "https://dev.virtualearth.net/REST/v1/Imagery/Map/Birdseye"
    "/{lat},{lng}/{zoom}"
)
_DEFAULT_ZOOM = 19
_DEFAULT_SIZE = "900,600"  # max landscape size per Bing static-map docs
# Map orientation degree -> short cardinal label used by callers /
# downstream PDF code. orientation degree is the direction the camera
# is looking, so e.g. orientation=0 (looking north) -> the photo
# faces north, which we label "looking_north".
ORIENTATION_TO_LABEL: dict[int, str] = {
    0: "looking_north",
    90: "looking_east",
    180: "looking_south",
    270: "looking_west",
}
DEFAULT_ORIENTATIONS: tuple[int, ...] = (0, 90, 180, 270)


class BirdseyeUnavailable(Exception):
    """Raised when no key is configured. Lets callers no-op cleanly."""


def fetch_birdseye_views(
    lat: float | None,
    lng: float | None,
    bing_key: str,
    *,
    zoom: int = _DEFAULT_ZOOM,
    size: str = _DEFAULT_SIZE,
    orientations: Iterable[int] = DEFAULT_ORIENTATIONS,
    timeout_s: float = 10.0,
) -> dict[str, bytes]:
    """Return {label: png_bytes} for whichever cardinal directions have coverage.

    Empty dict when:
      - bing_key is empty / missing
      - lat/lng are None
      - Bing has no Bird's Eye coverage for this address
      - Network or HTTP error

    Per-direction failures are silent — we just omit that entry from
    the returned dict. The caller decides what to do with each missing
    side (we use a 3D-mesh fallback per cell on the PDF page).
    """
    if not bing_key:
        log.info("birdseye: BING_MAPS_KEY empty, skipping fetch")
        return {}
    if lat is None or lng is None:
        log.info("birdseye: lat/lng missing, skipping fetch")
        return {}

    out: dict[str, bytes] = {}
    base_url = _BIRDSEYE_URL.format(lat=lat, lng=lng, zoom=zoom)

    for orient in orientations:
        label = ORIENTATION_TO_LABEL.get(orient)
        if label is None:
            continue
        try:
            r = requests.get(
                base_url,
                params={
                    "key": bing_key,
                    "orientation": orient,
                    "mapSize": size,
                    "format": "png",
                    # We don't ask Bing to render any pushpins / polylines on
                    # the photo — the panel overlay belongs on a different
                    # page where geometry is precise.
                },
                timeout=timeout_s,
                # Bing returns the binary image directly on success, or a
                # JSON error body on failure. Treat anything not 200 with
                # an image content-type as "no coverage" rather than an
                # error.
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            log.warning("birdseye: %s request failed: %s", label, exc)
            continue
        if r.status_code != 200:
            log.info(
                "birdseye: %s returned HTTP %d (no coverage / deprecated key?)",
                label, r.status_code,
            )
            continue
        ctype = r.headers.get("Content-Type", "")
        if not ctype.startswith("image/"):
            # Bing emits JSON error bodies with 200 OK in some cases.
            # Skip silently.
            log.info(
                "birdseye: %s response not an image (Content-Type=%s)",
                label, ctype,
            )
            continue
        if len(r.content) < 1024:
            # Tiny payloads are usually a "no imagery" placeholder.
            log.info(
                "birdseye: %s payload too small (%d bytes), treating as no coverage",
                label, len(r.content),
            )
            continue
        out[label] = r.content

    if not out:
        log.info("birdseye: no coverage at (%s, %s)", lat, lng)
    else:
        log.info(
            "birdseye: fetched %d/4 directions for (%s, %s)",
            len(out), lat, lng,
        )
    return out
