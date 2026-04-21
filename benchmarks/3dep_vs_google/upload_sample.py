"""Phase 2 — Upload a 3DEP sample (Phase 1 output) to Supabase.

Reads the ``{dsm,rgb,mask}.tif`` triple + ``metadata.json`` produced by
``fetch_3dep.py``, uploads the three rasters to the ``training-data``
bucket under ``samples/{sample_id}/``, and upserts a row into
``training_samples`` with ``source='3dep'``.

Everything is idempotent via the deterministic sample_id: re-running this
on the same input dir overwrites the Storage objects and updates the row
in place, rather than spawning a new training_samples record.

CLI:
    python benchmarks/3dep_vs_google/upload_sample.py \\
        --input-dir benchmarks/3dep_vs_google/output/<slug>/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from common import env_required, load_project_env

log = logging.getLogger("bench.upload")

REQUIRED_FILES = ("dsm.tif", "rgb.tif", "mask.tif", "metadata.json")


def _validate_input_dir(input_dir: Path) -> dict:
    """Fail fast if Phase 1 didn't complete cleanly."""
    if not input_dir.is_dir():
        raise SystemExit(f"ERROR: {input_dir} is not a directory")
    missing = [f for f in REQUIRED_FILES if not (input_dir / f).exists()]
    if missing:
        raise SystemExit(
            f"ERROR: {input_dir} is missing files from Phase 1: {missing}. "
            "Run fetch_3dep.py first."
        )
    meta = json.loads((input_dir / "metadata.json").read_text())
    for k in ("sample_id", "source", "width_px", "height_px", "meters_per_px",
              "lat", "lng", "formatted_address"):
        if k not in meta:
            raise SystemExit(f"ERROR: metadata.json is missing required key '{k}'")
    if meta["source"] != "3dep":
        raise SystemExit(
            f"ERROR: metadata.json source='{meta['source']}' — this script "
            "only uploads 3DEP samples. Google samples go through "
            "fetch_google_twin.py."
        )
    return meta


def _get_supabase_client():
    """Create a service-role Supabase client."""
    from supabase import create_client  # type: ignore

    url = env_required("SUPABASE_URL")
    key = env_required("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _upload_with_upsert(client, bucket: str, storage_path: str,
                       local_path: Path, content_type: str) -> str:
    """Upload a file to Supabase Storage with upsert enabled.

    The Supabase Python SDK uses ``upsert='true'`` as a string in the options
    dict — the underlying REST call treats it as a header. Passing ``True``
    as a Python bool is silently ignored, so we stick with the string.
    """
    data = local_path.read_bytes()
    client.storage.from_(bucket).upload(
        storage_path,
        data,
        {"content-type": content_type, "upsert": "true"},
    )
    log.info("uploaded %s (%.1f MB) → %s/%s",
             local_path.name, len(data) / 1e6, bucket, storage_path)
    return storage_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload a 3DEP sample to Supabase")
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="output directory produced by fetch_3dep.py")
    parser.add_argument("--bucket", default="training-data",
                        help="Supabase Storage bucket name (default: training-data)")
    parser.add_argument("--frontend-base", default="http://localhost:3000",
                        help="Labeling UI base URL for the printed instructions")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_project_env()

    meta = _validate_input_dir(args.input_dir)
    sample_id = meta["sample_id"]
    prefix = f"samples/{sample_id}"

    client = _get_supabase_client()

    # Upload all three files. Upsert means a re-run replaces the old ones.
    dsm_path = _upload_with_upsert(
        client, args.bucket, f"{prefix}/dsm.tif",
        args.input_dir / "dsm.tif", "image/tiff",
    )
    rgb_path = _upload_with_upsert(
        client, args.bucket, f"{prefix}/rgb.tif",
        args.input_dir / "rgb.tif", "image/tiff",
    )
    mask_path = _upload_with_upsert(
        client, args.bucket, f"{prefix}/mask.tif",
        args.input_dir / "mask.tif", "image/tiff",
    )

    # Upsert the training_samples row. We pass ``on_conflict='id'`` so a
    # re-run of this script doesn't violate the primary key.
    # The `source` column requires migration 020 to be applied first; the
    # client surfaces a PostgREST error otherwise.
    row = {
        "id": sample_id,
        "source": "3dep",
        "source_address": meta.get("address", ""),
        "formatted_address": meta["formatted_address"],
        "lat": meta["lat"],
        "lng": meta["lng"],
        "width_px": meta["width_px"],
        "height_px": meta["height_px"],
        "meters_per_px": meta["meters_per_px"],
        "rgb_storage_path": rgb_path,
        "dsm_storage_path": dsm_path,
        "mask_storage_path": mask_path,
        "building_insights": json.dumps({
            "benchmark": "3dep_vs_google",
            "capture_date": meta.get("capture_date"),
            "ql_level": meta.get("ql_level"),
            "point_density_per_m2": meta.get("point_density_per_m2"),
            "utm_epsg": meta.get("utm_epsg"),
            "tnm_work_unit": meta.get("tnm_work_unit"),
        }),
    }

    try:
        client.table("training_samples").upsert(row, on_conflict="id").execute()
    except Exception as e:
        msg = str(e)
        if "source" in msg and "column" in msg.lower():
            raise SystemExit(
                "ERROR: Supabase rejected the upsert — the 'source' column "
                "probably doesn't exist yet. Apply migration 020 "
                "(add_source_to_training_samples) and re-run."
            ) from None
        raise

    url = f"{args.frontend_base}/labeling/{sample_id}"
    print(
        f"\nSample uploaded. Label this roof at:\n  {url}\n\n"
        "Make sure the Next.js dev server is running:\n"
        "  cd /Users/carterbrady/Mymetalrooferbackupmvp-firstcommit/frontend && npm run dev\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
