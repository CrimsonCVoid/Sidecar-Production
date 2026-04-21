"""Phase 3 — Pull the production Google Solar twin for an address.

Hits the same ``POST /api/solar/ingest`` endpoint the live product uses, so
the Google-side sample is apples-to-apples with what a customer would get.
After ingest succeeds, stamps ``source='google'`` on the new
``training_samples`` row so Phase 4 can tell it apart from the 3DEP twin.

CLI:
    python benchmarks/3dep_vs_google/fetch_google_twin.py \\
        --address "123 Main St, Apex NC"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import httpx

from common import env_required, load_project_env

log = logging.getLogger("bench.gtwin")


def _post_ingest(api_base: str, address: str) -> dict:
    """Call the Solar ingest endpoint. Localhost bypasses auth via dev flag."""
    # If we're hitting localhost and the repo is configured with
    # DEV_ALLOW_UNAUTH=true (recon confirmed this is the current state),
    # the sidecar accepts the call without a JWT. If we add an internal
    # API key for hardening later, we can drop it in here.
    headers = {"Content-Type": "application/json"}
    internal_key = os.environ.get("INTERNAL_API_KEY", "")
    if internal_key:
        headers["X-Internal-API-Key"] = internal_key

    log.info("POST %s/api/solar/ingest  address=%r", api_base, address)
    try:
        r = httpx.post(
            f"{api_base}/api/solar/ingest",
            json={"address": address},
            headers=headers,
            timeout=120,
        )
    except httpx.HTTPError as e:
        raise SystemExit(
            f"ERROR: couldn't reach FastAPI sidecar at {api_base}. "
            f"Is uvicorn running? ({e})"
        ) from None

    if r.status_code == 404:
        raise SystemExit(
            "ERROR: Google Solar returned 404 for this address — no DSM "
            "coverage. Skip this address in the batch; the comparison "
            "would be meaningless without a twin."
        )
    if r.status_code == 401:
        raise SystemExit(
            "ERROR: Solar ingest returned 401. Either the FastAPI sidecar "
            "has DEV_ALLOW_UNAUTH disabled, or it's not listening on "
            "localhost. Export INTERNAL_API_KEY or enable dev auth."
        )
    if r.status_code >= 400:
        raise SystemExit(
            f"ERROR: Solar ingest failed with HTTP {r.status_code}: "
            f"{r.text[:300]}"
        )
    return r.json()


def _mark_source_google(sample_id: str) -> None:
    """UPDATE training_samples SET source='google' WHERE id = sample_id."""
    from supabase import create_client  # type: ignore

    url = env_required("SUPABASE_URL")
    key = env_required("SUPABASE_SERVICE_ROLE_KEY")
    client = create_client(url, key)
    try:
        client.table("training_samples").update(
            {"source": "google"}
        ).eq("id", sample_id).execute()
    except Exception as e:
        msg = str(e)
        if "source" in msg and "column" in msg.lower():
            raise SystemExit(
                "ERROR: the 'source' column doesn't exist yet. Apply "
                "migration 020 (add_source_to_training_samples) and re-run. "
                f"The new Google sample {sample_id} was still ingested."
            ) from None
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull a Google Solar twin")
    parser.add_argument("--address", required=True,
                        help='e.g. "123 Main St, Apex NC"')
    parser.add_argument("--api-base", default="http://127.0.0.1:8000",
                        help="FastAPI sidecar base URL")
    parser.add_argument("--frontend-base", default="http://localhost:3000",
                        help="Labeling UI base URL")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_project_env()

    result = _post_ingest(args.api_base, args.address)
    sample_id = result["sample_id"]
    formatted = result.get("formatted_address", args.address)

    _mark_source_google(sample_id)

    url = f"{args.frontend_base}/labeling/{sample_id}"
    print(
        f"\nGoogle Solar twin ingested. Label this roof at:\n  {url}\n"
        f"  Address:      {formatted}\n"
        f"  Sample ID:    {sample_id}\n"
        f"  Source:       google\n\n"
        "IMPORTANT: label with the *same* panel topology as the 3DEP twin "
        "so compare.py can pair panels 1:1.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
