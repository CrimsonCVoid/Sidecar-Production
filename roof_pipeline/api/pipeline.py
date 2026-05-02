"""Pipeline run endpoints: POST /run-pipeline, GET /run/{run_id} (API-02).

Triggers full pipeline execution as a background task. Writes status updates
to Supabase pipeline_runs table at each stage boundary. Uploads output files
to Supabase Storage. Per D-09, D-10, D-11, D-12, D-13.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from supabase import Client

from ..run_real import _load_dsm, run_pipeline
from .deps import (
    Principal,
    get_settings,
    get_supabase,
    require_principal,
    verify_sample_access,
)
from .config import Settings
from .schemas import PipelineRunCreated, PipelineRunRequest, PipelineRunStatus

log = logging.getLogger(__name__)

router = APIRouter()


def _fetch_birdseye(settings: Settings, lat: float | None, lng: float | None) -> dict[str, bytes]:
    """Best-effort Bing Bird's Eye fetch. Empty dict on any failure."""
    if not settings.bing_maps_key:
        return {}
    try:
        from ..bing_birdseye import fetch_birdseye_views
        return fetch_birdseye_views(lat, lng, settings.bing_maps_key)
    except Exception as exc:
        log.warning("birdseye fetch failed: %s", exc)
        return {}


def _fetch_rgb_bytes(supabase: Client, settings: Settings, rgb_storage_path: str | None) -> bytes | None:
    """Best-effort download of the RGB GeoTIFF for a sample.

    Used to color the orthographic / 3D-views pages of the cut-sheet PDF
    with the actual Google Solar imagery instead of falling back to a
    bare mesh wireframe. Failures are non-fatal — the pipeline still
    runs, the PDF just loses the AERIAL cell.
    """
    if not rgb_storage_path:
        return None
    for bucket in [settings.training_bucket, settings.storage_bucket]:
        try:
            data = supabase.storage.from_(bucket).download(rgb_storage_path)
            if data:
                return data
        except Exception:
            continue
    log.warning("rgb GeoTIFF not found in any bucket for path %s", rgb_storage_path)
    return None


# ---- Content type mapping for Supabase Storage uploads (D-13) ----
_CONTENT_TYPES: dict[str, str] = {
    ".obj": "model/obj",
    ".gltf": "model/gltf+json",
    ".pdf": "application/pdf",
    ".json": "application/json",
}


def _upload_output(
    supabase: Client,
    bucket: str,
    run_id: str,
    local_path: Path,
) -> str:
    """Upload a single output file to Supabase Storage (D-13).

    Returns the storage path for referencing in the pipeline_runs row.
    Sets content-type explicitly to avoid Supabase defaulting to text/plain.
    """
    content_type = _CONTENT_TYPES.get(local_path.suffix, "application/octet-stream")
    storage_path = f"runs/{run_id}/{local_path.name}"
    with open(local_path, "rb") as f:
        supabase.storage.from_(bucket).upload(
            storage_path,
            f,
            {"content-type": content_type, "upsert": "true"},
        )
    log.info("uploaded %s -> %s (%s)", local_path.name, storage_path, content_type)
    return storage_path


def _update_status(
    supabase: Client,
    run_id: str,
    *,
    status: str,
    stage_name: str | None = None,
    progress_pct: int = 0,
    error_message: str | None = None,
    completed_at: str | None = None,
) -> None:
    """Write status update to pipeline_runs table (D-10)."""
    update_data: dict = {
        "status": status,
        "progress_pct": progress_pct,
    }
    if stage_name is not None:
        update_data["stage_name"] = stage_name
    if error_message is not None:
        update_data["error_message"] = error_message
    if completed_at is not None:
        update_data["completed_at"] = completed_at
    supabase.table("pipeline_runs").update(update_data).eq("id", run_id).execute()


async def _run_pipeline_bg(
    run_id: str,
    sample_id: str,
    request_body: PipelineRunRequest,
    supabase: Client,
    settings: Settings,
) -> None:
    """Background task: run full pipeline, update status at stage boundaries (D-10, D-11, D-12).

    Pipeline stages and progress percentages per D-10:
      plane_fits(15%) -> boundaries(30%) -> snap(50%) -> mesh(65%) ->
      cutsheets(80%) -> shop_drawings(90%) -> upload(95%) -> done(100%)

    The entire body is wrapped in try/except per D-11. On ANY exception,
    status='error' + error_message is written to pipeline_runs. The background
    task never dies silently.
    """
    try:
        _update_status(supabase, run_id, status="running", stage_name="loading", progress_pct=5)

        # Load DSM and mask from Supabase Storage
        # Real table is training_samples (not "samples")
        sample_result = supabase.table("training_samples").select("*").eq("id", sample_id).execute()
        if not sample_result.data:
            raise ValueError(f"Sample {sample_id} not found in training_samples table")

        sample = sample_result.data[0]

        # Download DSM and mask files from Supabase Storage to a temp directory
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Download DSM .tif
            dsm_storage_path = sample.get("dsm_storage_path")
            if not dsm_storage_path:
                raise ValueError(f"Sample {sample_id} has no dsm_storage_path")
            dsm_bytes = supabase.storage.from_(settings.storage_bucket).download(dsm_storage_path)
            dsm_local = tmp_path / "dsm.tif"
            dsm_local.write_bytes(dsm_bytes)

            # Download mask .npy
            mask_storage_path = sample.get("mask_storage_path")
            if not mask_storage_path:
                raise ValueError(f"Sample {sample_id} has no mask_storage_path")
            mask_bytes = supabase.storage.from_(settings.storage_bucket).download(mask_storage_path)
            mask_local = tmp_path / "mask.npy"
            mask_local.write_bytes(mask_bytes)

            # Download panels.json if it exists
            panels_json_path: Path | None = None
            panels_json_storage = sample.get("panels_json_path")
            if panels_json_storage:
                try:
                    pj_bytes = supabase.storage.from_(settings.storage_bucket).download(panels_json_storage)
                    panels_json_local = tmp_path / "panels.json"
                    panels_json_local.write_bytes(pj_bytes)
                    panels_json_path = panels_json_local
                except Exception:
                    log.warning("Could not download panels.json for sample %s, using contour fallback", sample_id)

            _update_status(supabase, run_id, status="running", stage_name="loading", progress_pct=10)

            # Load data
            dsm, res_m = _load_dsm(dsm_local)
            mask_arr = np.load(mask_local).astype(np.uint8)

            # Pull the RGB GeoTIFF too so the orthographic / 3D-views
            # pages of the shop-drawings PDF render with Google Solar
            # imagery. None on failure → mesh fallback (still works).
            rgb_bytes = _fetch_rgb_bytes(
                supabase, settings, sample.get("rgb_storage_path"),
            )
            # Optional Bing Bird's Eye oblique photos for the four
            # angled cells on the orthographic-views page. Empty dict
            # → mesh fallback per direction.
            birdseye_views = _fetch_birdseye(
                settings, sample.get("lat"), sample.get("lng"),
            )

            # Run pipeline in thread to avoid blocking event loop (D-12)
            out_dir = tmp_path / "output"
            output_paths = await asyncio.to_thread(
                run_pipeline,
                dsm,
                mask_arr,
                res_m,
                out_dir,
                snap_tol=request_body.snap_tol,
                use_snap_v2=request_body.use_snap_v2,
                panels_json_path=panels_json_path,
                project_name=request_body.project_name,
                project_address=request_body.project_address,
                estimate_number=sample_id,
                coverage_in=request_body.coverage_in,
                profile=request_body.profile,
                waste_pct=request_body.waste_pct,
                rgb_bytes=rgb_bytes,
                birdseye_views=birdseye_views,
            )

            _update_status(supabase, run_id, status="running", stage_name="uploading", progress_pct=90)

            # Upload all output files to Supabase Storage (D-13)
            storage_paths: dict[str, str] = {}
            for key, local_path in output_paths.items():
                if local_path is not None and local_path.exists():
                    storage_paths[key] = _upload_output(
                        supabase, settings.storage_bucket, run_id, local_path,
                    )

            # Also store feature graph in snap_features table if v2 was used
            features_path = output_paths.get("features_json")
            if features_path and features_path.exists():
                with open(features_path) as f:
                    feature_graph = json.load(f)
                supabase.table("snap_features").insert({
                    "id": str(uuid.uuid4()),
                    "sample_id": sample_id,
                    "run_id": run_id,
                    "feature_graph": feature_graph,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }).execute()

            # Mark complete
            now = datetime.now(timezone.utc).isoformat()
            supabase.table("pipeline_runs").update({
                "status": "done",
                "stage_name": "done",
                "progress_pct": 100,
                "completed_at": now,
                "output_paths": storage_paths,
            }).eq("id", run_id).execute()

            log.info("pipeline run %s completed: %d files uploaded", run_id, len(storage_paths))

    except Exception as exc:
        # D-11: NEVER let a background task die silently
        now = datetime.now(timezone.utc).isoformat()
        try:
            _update_status(
                supabase, run_id,
                status="error",
                error_message=str(exc),
                completed_at=now,
            )
        except Exception as db_exc:
            log.error("Failed to write error status for run %s: %s", run_id, db_exc)
        log.exception("pipeline run %s failed", run_id)


@router.get("/samples")
async def list_samples(
    request: Request,
    principal: Principal = Depends(require_principal),
):
    """List all samples with their latest pipeline run status (DIDX-01).

    Returns each sample joined with the most recent pipeline_runs row
    so the dashboard can show address, panel count, and run status.
    Gracefully returns an empty list when Supabase credentials are missing.

    Auth: this is an admin-shaped endpoint (returns every sample). Only
    the internal proxy principal may call it — user-JWT callers get 403.
    Per-user sample listing should go through the Next.js /api/projects
    route, which is scoped by org membership.
    """
    if principal.kind != "internal":
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        settings = Settings()
    except Exception:
        log.warning("Supabase credentials not configured -- returning empty samples list")
        return []

    from supabase import create_client

    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)

    # Real table is training_samples, not "samples"
    samples_result = (
        supabase.table("training_samples")
        .select("id, formatted_address, source_address, width_px, height_px, dsm_storage_path, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    samples = samples_result.data or []

    # auto_built_roofs has region_count and label_status per sample
    roofs_result = (
        supabase.table("auto_built_roofs")
        .select("sample_id, status, region_count, label_status")
        .execute()
    )
    roofs_by_sample: dict[str, dict] = {}
    for r in roofs_result.data or []:
        roofs_by_sample[r["sample_id"]] = r

    # training_labels for label count
    labels_result = (
        supabase.table("training_labels")
        .select("sample_id, status")
        .execute()
    )
    labels_by_sample: dict[str, dict] = {}
    for lb in labels_result.data or []:
        labels_by_sample[lb["sample_id"]] = lb

    result = []
    for s in samples:
        sid = s["id"]
        roof = roofs_by_sample.get(sid)
        label = labels_by_sample.get(sid)
        result.append({
            "id": sid,
            "address": s.get("formatted_address") or s.get("source_address") or sid,
            "panel_count": roof.get("region_count", 0) if roof else 0,
            "latest_run_status": roof["status"] if roof else None,
            "label_status": roof.get("label_status", "unlabeled") if roof else "unlabeled",
            "has_labels": label is not None,
            "dsm_storage_path": s.get("dsm_storage_path"),
        })

    return result


@router.post("/run", status_code=202, response_model=PipelineRunCreated)
async def trigger_pipeline_run(
    body: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
):
    """Trigger a full pipeline run as a background task (API-02, D-09).

    Returns 202 Accepted immediately with run_id and status_url.
    The pipeline runs asynchronously and writes status updates to the
    pipeline_runs Supabase table at each stage boundary.
    """
    verify_sample_access(principal, body.sample_id, supabase)
    request.state.sample_id = body.sample_id

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Insert initial pipeline_runs row (D-10)
    supabase.table("pipeline_runs").insert({
        "id": run_id,
        "sample_id": body.sample_id,
        "status": "queued",
        "stage_name": None,
        "progress_pct": 0,
        "error_message": None,
        "started_at": now,
        "completed_at": None,
    }).execute()

    # Schedule background task (D-10)
    background_tasks.add_task(
        _run_pipeline_bg, run_id, body.sample_id, body, supabase, settings,
    )

    log.info("pipeline run %s queued for sample %s", run_id, body.sample_id)

    return PipelineRunCreated(
        run_id=run_id,
        status_url=f"/api/pipeline/run/{run_id}",
    )


@router.get("/run/{run_id}", response_model=PipelineRunStatus)
async def get_run_status(
    run_id: str,
    request: Request,
    supabase: Client = Depends(get_supabase),
    principal: Principal = Depends(require_principal),
):
    """Get current status of a pipeline run (API-02).

    Returns the pipeline_runs row for the given run_id.
    Frontend polls this endpoint or subscribes via Supabase Realtime.
    """
    result = supabase.table("pipeline_runs").select("*").eq("id", run_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    row = result.data[0]
    # Ownership chain: run_id → sample_id → projects ownership.
    verify_sample_access(principal, row["sample_id"], supabase)
    return PipelineRunStatus(
        id=row["id"],
        sample_id=row["sample_id"],
        status=row["status"],
        stage_name=row.get("stage_name"),
        progress_pct=row.get("progress_pct", 0),
        error_message=row.get("error_message"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )


@router.post("/generate-pdf/{sample_id}")
async def generate_pdf(
    sample_id: str,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
):
    """Generate a PDF from saved labels for a sample.

    Reads panel labels from training_labels, downloads DSM from storage,
    runs the pipeline synchronously, and returns the PDF file.
    """
    from fastapi.responses import Response
    from io import BytesIO

    verify_sample_access(principal, sample_id, supabase)
    request.state.sample_id = sample_id

    # 1. Get labels from DB
    labels_result = (
        supabase.table("training_labels")
        .select("annotations")
        .eq("sample_id", sample_id)
        .execute()
    )
    if not labels_result.data:
        raise HTTPException(status_code=404, detail="No labels found -- save labels first")

    annotations = labels_result.data[0].get("annotations") or {}
    panels = annotations.get("panels", [])
    if not panels:
        raise HTTPException(status_code=400, detail="Labels have no panels")

    # 2. Get sample info
    sample_result = (
        supabase.table("training_samples")
        .select(
            "dsm_storage_path, rgb_storage_path, formatted_address, "
            "source_address, meters_per_px, lat, lng"
        )
        .eq("id", sample_id)
        .execute()
    )
    if not sample_result.data:
        raise HTTPException(status_code=404, detail="Sample not found")

    sample = sample_result.data[0]
    dsm_path = sample.get("dsm_storage_path")
    if not dsm_path:
        raise HTTPException(status_code=400, detail="Sample has no DSM")

    address = sample.get("formatted_address") or sample.get("source_address") or sample_id

    # 3. Download DSM
    dsm_bytes = None
    for bucket in [settings.training_bucket, settings.storage_bucket]:
        try:
            dsm_bytes = supabase.storage.from_(bucket).download(dsm_path)
            break
        except Exception:
            continue
    if dsm_bytes is None:
        raise HTTPException(status_code=404, detail="Could not download DSM from storage")

    # 4. Write panels.json and DSM to temp dir, run pipeline
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Write DSM
        dsm_local = tmp_path / "dsm.tif"
        dsm_local.write_bytes(dsm_bytes)

        # Rasterize panel polygons into mask and remap IDs to 1-indexed
        import rasterio
        import cv2

        with rasterio.open(BytesIO(dsm_bytes)) as ds:
            h, w = ds.height, ds.width
            res_m = abs(ds.res[0]) if ds.res else sample.get("meters_per_px", 0.1)

        remapped_panels = []
        mask_arr = np.zeros((h, w), dtype=np.uint8)
        for i, p in enumerate(panels):
            new_id = i + 1
            corners = np.array(p["corners_pix"], dtype=np.int32)
            cv2.fillPoly(mask_arr, [corners], new_id)
            remapped_panels.append({**p, "id": new_id})

        # Write panels.json with remapped 1-indexed IDs
        panels_json = tmp_path / "panels.json"
        panels_json.write_text(json.dumps({"panels": remapped_panels}))

        mask_local = tmp_path / "mask.npy"
        np.save(mask_local, mask_arr)

        # Load DSM array
        dsm_arr, actual_res = _load_dsm(dsm_local)

        # Best-effort RGB ortho download for the cut-sheet PDF's
        # orthographic / 3D-views aerial cell.
        rgb_bytes = _fetch_rgb_bytes(
            supabase, settings, sample.get("rgb_storage_path"),
        )
        # Best-effort Bing Bird's Eye oblique photos.
        birdseye_views = _fetch_birdseye(
            settings, sample.get("lat"), sample.get("lng"),
        )

        out_dir = tmp_path / "output"

        log.info("generating PDF for sample %s (%d panels)", sample_id, len(panels))

        output_paths = await asyncio.to_thread(
            run_pipeline,
            dsm_arr,
            mask_arr,
            actual_res,
            out_dir,
            use_snap_v2=True,
            panels_json_path=panels_json,
            project_name=address,
            project_address=address,
            estimate_number=sample_id[:8],
            rgb_bytes=rgb_bytes,
            birdseye_views=birdseye_views,
        )

        # Find the cutsheets PDF
        pdf_path = output_paths.get("cutsheets_pdf")
        if pdf_path is None or not pdf_path.exists():
            # Try any PDF in output
            pdfs = list(out_dir.glob("*.pdf"))
            pdf_path = pdfs[0] if pdfs else None

        if pdf_path is None or not pdf_path.exists():
            raise HTTPException(status_code=500, detail="Pipeline ran but no PDF was generated")

        # Read PDF bytes before temp dir is cleaned up (FileResponse is lazy)
        pdf_bytes = pdf_path.read_bytes()

    # Return outside the tempdir context so cleanup has already happened
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{sample_id[:8]}_cutsheets.pdf"',
        },
    )


# ---------------------------------------------------------------------------
# Finalized PDF — same as generate-pdf, but scales every dimension by a
# field-verified scale factor so on-roof tape measurements override the
# Solar/DSM-derived geometry. Mirrors generate-pdf almost exactly; the
# only difference is that res_m is multiplied by the scale before the
# pipeline runs, which propagates through every plane fit, cutsheet
# dimension, and shop-drawing measurement automatically.
# ---------------------------------------------------------------------------


@router.post("/generate-finalized-pdf/{sample_id}")
async def generate_finalized_pdf(
    sample_id: str,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
):
    """Generate a finalized PDF with field-verified scale applied.

    Scale factor sources, in priority order:
      1. ``?scale=`` query param (Next.js can pre-compute and pass it).
      2. Median of (field-measured length / pipeline-computed length)
         derived from ``projects.field_measurements`` JSONB combined
         with the legacy ``field_baseline_length_ft`` column.
      3. ``1.0`` (no rescale — fall back to the same output as
         ``/generate-pdf``).

    Always re-runs the pipeline; we do not cache against a previous
    cutsheet because the geometry the user verified against may have
    drifted between requests.
    """
    from fastapi.responses import Response
    from io import BytesIO

    verify_sample_access(principal, sample_id, supabase)
    request.state.sample_id = sample_id

    # Optional override from the Next.js side. If passed, takes priority
    # over computing scale from project columns; lets us tune behaviour
    # without redeploying the sidecar.
    scale_qs = request.query_params.get("scale")
    panel_type_qs = request.query_params.get("panel_type")

    # 1. Labels
    labels_result = (
        supabase.table("training_labels")
        .select("annotations")
        .eq("sample_id", sample_id)
        .execute()
    )
    if not labels_result.data:
        raise HTTPException(status_code=404, detail="No labels found -- save labels first")
    annotations = labels_result.data[0].get("annotations") or {}
    panels = annotations.get("panels", [])
    if not panels:
        raise HTTPException(status_code=400, detail="Labels have no panels")

    # 2. Sample
    sample_result = (
        supabase.table("training_samples")
        .select(
            "dsm_storage_path, rgb_storage_path, formatted_address, "
            "source_address, meters_per_px, lat, lng"
        )
        .eq("id", sample_id)
        .execute()
    )
    if not sample_result.data:
        raise HTTPException(status_code=404, detail="Sample not found")
    sample = sample_result.data[0]
    dsm_path = sample.get("dsm_storage_path")
    if not dsm_path:
        raise HTTPException(status_code=400, detail="Sample has no DSM")
    address = sample.get("formatted_address") or sample.get("source_address") or sample_id

    # 3. Field-verified scale. We try the query string first because the
    # Next.js side already computes the median when measurements are
    # saved; that path lets us avoid a duplicate "fetch baseline +
    # measurements + compute median" round trip server-side.
    scale = 1.0
    if scale_qs:
        try:
            parsed = float(scale_qs)
            if 0.5 <= parsed <= 2.0:  # sanity-clamp; tape vs DSM rarely > 2x
                scale = parsed
            else:
                log.warning("ignoring out-of-range field scale %.4f from qs", parsed)
        except ValueError:
            log.warning("ignoring non-numeric scale qs %r", scale_qs)

    if scale == 1.0:
        # Fall back to project columns. projects.id == sample_id in this
        # codebase (the labeler uses the project UUID as its sample_id).
        try:
            proj = (
                supabase.table("projects")
                .select("field_measurements, field_baseline_length_ft")
                .eq("id", sample_id)
                .single()
                .execute()
            )
            row = proj.data or {}
            measurements = row.get("field_measurements") or {}
            # Same-edge check: if there's a single legacy baseline, prefer
            # it; the median path needs more than one entry.
            if isinstance(measurements, dict) and len(measurements) >= 1:
                # Need expected lengths to compute scale ratios. Pull them
                # from the ts_export JSON of a fresh pipeline pass below
                # is overkill; instead we use the labeler edge-pixel
                # lengths and convert with res_m. Done after loading DSM.
                pass
        except Exception as exc:
            log.warning("could not load project field_* columns: %s", exc)

    # 4. Download DSM
    dsm_bytes = None
    for bucket in [settings.training_bucket, settings.storage_bucket]:
        try:
            dsm_bytes = supabase.storage.from_(bucket).download(dsm_path)
            break
        except Exception:
            continue
    if dsm_bytes is None:
        raise HTTPException(status_code=404, detail="Could not download DSM from storage")

    # 5. Run pipeline. The corrected scale is applied by multiplying
    #    res_m at the input — every meter-derived dimension downstream
    #    (mesh vertices, cutsheet edge lengths, shop-drawing trim
    #    quantities) scales linearly with res_m, so a single multiply
    #    here propagates correctly through plane fits, polygon vertex
    #    coords, and PDF output.
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        dsm_local = tmp_path / "dsm.tif"
        dsm_local.write_bytes(dsm_bytes)

        import rasterio
        import cv2

        with rasterio.open(BytesIO(dsm_bytes)) as ds:
            h, w = ds.height, ds.width
            base_res_m = abs(ds.res[0]) if ds.res else sample.get("meters_per_px", 0.1)

        remapped_panels = []
        mask_arr = np.zeros((h, w), dtype=np.uint8)
        for i, p in enumerate(panels):
            new_id = i + 1
            corners = np.array(p["corners_pix"], dtype=np.int32)
            cv2.fillPoly(mask_arr, [corners], new_id)
            remapped_panels.append({**p, "id": new_id})

        panels_json = tmp_path / "panels.json"
        panels_json.write_text(json.dumps({"panels": remapped_panels}))

        mask_local = tmp_path / "mask.npy"
        np.save(mask_local, mask_arr)

        dsm_arr, actual_res = _load_dsm(dsm_local)

        # If the QS scale wasn't supplied, derive scale here from
        # field_measurements. We need pixel-edge lengths to convert into
        # the "expected" baseline. Doing it post-DSM-load means we have
        # actual_res handy.
        if scale == 1.0:
            try:
                proj = (
                    supabase.table("projects")
                    .select("field_measurements, field_baseline_length_ft")
                    .eq("id", sample_id)
                    .single()
                    .execute()
                )
                row = proj.data or {}
                measurements = row.get("field_measurements") or {}
                if isinstance(measurements, dict) and measurements:
                    M_TO_FT = 3.280839895
                    ratios: list[float] = []
                    for key, measured_ft in measurements.items():
                        try:
                            # Keys come in as "p<panel_idx>_e<edge_idx>";
                            # the panel_idx here matches the LABEL panel
                            # array order (0-based) from training_labels.
                            if not isinstance(measured_ft, (int, float)):
                                continue
                            parts = str(key).split("_")
                            p_idx = int(parts[0].lstrip("p"))
                            e_idx = int(parts[1].lstrip("e"))
                            corners = panels[p_idx].get("corners_pix") or []
                            if e_idx < 0 or e_idx >= len(corners):
                                continue
                            a = corners[e_idx]
                            b = corners[(e_idx + 1) % len(corners)]
                            dx = (b[0] - a[0]) * actual_res
                            dy = (b[1] - a[1]) * actual_res
                            expected_m = (dx * dx + dy * dy) ** 0.5
                            expected_ft = expected_m * M_TO_FT
                            if expected_ft <= 0.5:
                                continue
                            ratio = float(measured_ft) / expected_ft
                            if 0.5 <= ratio <= 2.0:
                                ratios.append(ratio)
                        except Exception:
                            continue
                    if ratios:
                        ratios.sort()
                        mid = len(ratios) // 2
                        median = (
                            ratios[mid]
                            if len(ratios) % 2 == 1
                            else 0.5 * (ratios[mid - 1] + ratios[mid])
                        )
                        scale = median
                        log.info(
                            "field-verified median scale %.4f from %d edges",
                            scale,
                            len(ratios),
                        )
            except Exception as exc:
                log.warning("could not compute scale from field measurements: %s", exc)

        out_dir = tmp_path / "output"

        log.info(
            "generating FINALIZED PDF for sample %s (%d panels, scale=%.4f)",
            sample_id,
            len(panels),
            scale,
        )

        # Map UI panel-type slug -> shop-drawings profile + coverage.
        coverage_in = 16.0
        profile = "SS"
        if panel_type_qs == "pbr":
            coverage_in, profile = 36.0, "PBR"
        elif panel_type_qs == "5v":
            coverage_in, profile = 24.0, "5V"
        elif panel_type_qs == "ag":
            coverage_in, profile = 36.0, "AG"
        elif panel_type_qs == "corrugated":
            coverage_in, profile = 26.0, "CORR"

        # Best-effort RGB ortho download for the cut-sheet PDF's
        # orthographic / 3D-views aerial cell. Field-scale doesn't change
        # which RGB we use — same Google Solar imagery as the unscaled run.
        rgb_bytes = _fetch_rgb_bytes(
            supabase, settings, sample.get("rgb_storage_path"),
        )
        # Best-effort Bing Bird's Eye photos.
        birdseye_views = _fetch_birdseye(
            settings, sample.get("lat"), sample.get("lng"),
        )

        output_paths = await asyncio.to_thread(
            run_pipeline,
            dsm_arr,
            mask_arr,
            actual_res * scale,  # <-- the whole point of this endpoint
            out_dir,
            use_snap_v2=True,
            panels_json_path=panels_json,
            project_name=address,
            project_address=address,
            estimate_number=sample_id[:8],
            coverage_in=coverage_in,
            profile=profile,
            rgb_bytes=rgb_bytes,
            birdseye_views=birdseye_views,
        )

        pdf_path = output_paths.get("shop_pdf") or output_paths.get("pdf")
        if pdf_path is None or not pdf_path.exists():
            pdfs = list(out_dir.glob("*.pdf"))
            pdf_path = pdfs[0] if pdfs else None
        if pdf_path is None or not pdf_path.exists():
            raise HTTPException(
                status_code=500, detail="Pipeline ran but no PDF was generated"
            )
        pdf_bytes = pdf_path.read_bytes()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{sample_id[:8]}_finalized_cutsheet.pdf"'
            ),
            "X-Field-Scale": f"{scale:.6f}",
        },
    )


# ---------------------------------------------------------------------------
# Cutsheet data as JSON (for interactive UI — same source data as the PDF)
# ---------------------------------------------------------------------------


_COMPASS_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _azimuth_label(deg: float) -> str:
    """Bucket 0-360° azimuth into 8 compass sectors."""
    idx = int(round((deg % 360) / 45)) % 8
    return _COMPASS_LABELS[idx]


@router.get("/cutsheet-data/{sample_id}")
async def get_cutsheet_data(
    sample_id: str,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_principal),
):
    """Return the structured data that powers the cutsheet PDF, as JSON.

    The UI uses this to render an interactive cutsheet (clickable panels,
    selectable detail view). Exactly the same pipeline as
    /generate-pdf/{sample_id} but returns panel/plane/mesh stats as JSON
    instead of rendering a PDF.
    """
    from io import BytesIO

    from ..cutsheets import (
        azimuth_degrees,
        meters_to_ft_in,
        polygon_area_2d,
        rotation_to_horizontal,
        slope_rise_over_12,
    )
    from ..planes import Plane, fit_plane

    verify_sample_access(principal, sample_id, supabase)
    request.state.sample_id = sample_id

    # 1. Labels
    labels_result = (
        supabase.table("training_labels")
        .select("annotations")
        .eq("sample_id", sample_id)
        .execute()
    )
    if not labels_result.data:
        raise HTTPException(
            status_code=404, detail="No labels saved for this project"
        )
    annotations = labels_result.data[0].get("annotations") or {}
    panels = annotations.get("panels", [])
    if not panels:
        raise HTTPException(status_code=400, detail="Labels have no panels")

    # 2. Sample metadata
    sample_result = (
        supabase.table("training_samples")
        .select(
            "dsm_storage_path, formatted_address, source_address, "
            "meters_per_px, width_px, height_px"
        )
        .eq("id", sample_id)
        .execute()
    )
    if not sample_result.data:
        raise HTTPException(status_code=404, detail="Sample not found")
    sample = sample_result.data[0]
    dsm_path = sample.get("dsm_storage_path")
    if not dsm_path:
        raise HTTPException(status_code=400, detail="Sample has no DSM")

    # 3. Download DSM
    dsm_bytes = None
    for bucket in [settings.training_bucket, settings.storage_bucket]:
        try:
            dsm_bytes = supabase.storage.from_(bucket).download(dsm_path)
            break
        except Exception:
            continue
    if dsm_bytes is None:
        raise HTTPException(
            status_code=404, detail="Could not download DSM from storage"
        )

    # 4. Open DSM
    import rasterio

    with rasterio.open(BytesIO(dsm_bytes)) as ds:
        dsm_arr = ds.read(1).astype(np.float64)
        h, w = ds.height, ds.width
        res_m = abs(ds.res[0]) if ds.res else float(
            sample.get("meters_per_px") or 0.25
        )

    # 5. For each user-clicked panel polygon:
    #    (a) rasterize the polygon to a mask of *interior* pixels,
    #    (b) erode the mask inward ~2 pixels to dodge DSM edge-bleed --
    #        Google Solar's 0.1-0.5m DSMs are Gaussian-smoothed, so the
    #        2-3 pixel ring just inside the user polygon is contaminated
    #        with values that bleed from the wall / gutter / ground
    #        outside. Sampling those values produces a fit that tilts
    #        unrealistically steep (we've seen 24/12 for a true 4/12
    #        panel when the polygon was drawn right at the eave),
    #    (c) fit the plane to a dense sample of the eroded interior,
    #    (d) project each user corner onto the fitted plane so the
    #        returned 3D polygon is guaranteed planar.
    #    Falls back to un-eroded sample when erosion leaves too few
    #    pixels (small panels); falls back to corner-only when even the
    #    un-eroded mask is empty.
    from scipy.ndimage import binary_erosion
    from skimage.draw import polygon as draw_polygon

    M_TO_FT = 3.280839895
    MIN_INTERIOR_PIXELS = 8
    # Erosion depth in pixels. 2px ≈ 0.5 m at Google Solar HIGH quality
    # (0.1 m res) or ~1 m at LOW quality (0.5 m res) — enough to skip
    # the smoothed boundary ring regardless of imagery quality.
    EDGE_BLEED_ERODE_PX = 2
    # If fitted slope exceeds this, log a warning with the most likely
    # cause so the user can see it and re-label. 18/12 (56° pitch) is
    # the top end of real metal-roofing practice; anything steeper is
    # almost always DSM noise rather than real geometry.
    MAX_SANE_RISE_OVER_12 = 18

    def sample_dsm(cx: float, cy: float) -> float:
        ix = max(0, min(w - 1, int(round(cx))))
        iy = max(0, min(h - 1, int(round(cy))))
        return float(dsm_arr[iy, ix])

    def z_on_plane(x_m: float, y_m: float, plane: Plane) -> float:
        """z such that normal . (x,y,z) = plane.d."""
        nx, ny, nz = plane.normal
        if abs(nz) < 1e-9:
            return float(plane.centroid[2])
        return float((plane.d - nx * x_m - ny * y_m) / nz)

    panel_payloads = []
    plan_panels = []

    valid_dsm = ~np.isnan(dsm_arr)

    for i, user_panel in enumerate(panels):
        pid = i + 1
        corners_pix = user_panel.get("corners_pix", [])
        if len(corners_pix) < 3:
            continue

        # --- Interior pixel rasterization for the plane fit ---
        cols_px = np.array([float(c[0]) for c in corners_pix])
        rows_px = np.array([float(c[1]) for c in corners_pix])
        rr, cc = draw_polygon(rows_px, cols_px, shape=(h, w))
        if rr.size == 0:
            log.warning("panel %d: empty rasterization, skipping", pid)
            continue

        # Build a 2D boolean mask for erosion.
        full_mask = np.zeros((h, w), dtype=bool)
        full_mask[rr, cc] = True
        full_mask &= valid_dsm  # drop NaN cells

        # Erode to avoid DSM edge-bleed. If erosion wipes out too many
        # pixels (thin panels where the entire strip is within the
        # bleed zone), fall back to the un-eroded mask.
        eroded_mask = binary_erosion(full_mask, iterations=EDGE_BLEED_ERODE_PX)
        sample_mask = eroded_mask
        used_erosion = True
        if eroded_mask.sum() < MIN_INTERIOR_PIXELS:
            if full_mask.sum() >= MIN_INTERIOR_PIXELS:
                log.warning(
                    "panel %d: erosion left only %d px (too thin); using "
                    "un-eroded interior — expect slope noise near edges",
                    pid, int(eroded_mask.sum()),
                )
                sample_mask = full_mask
                used_erosion = False
            else:
                # Panel is tiny or mostly off-DSM; fall back to corners.
                log.warning(
                    "panel %d: %d interior DSM pixels (<%d); falling back "
                    "to corner-only plane fit",
                    pid, int(full_mask.sum()), MIN_INTERIOR_PIXELS,
                )
                fit_source = np.array([
                    [float(cx) * res_m, float(cy) * res_m,
                     sample_dsm(float(cx), float(cy))]
                    for cx, cy in corners_pix
                ], dtype=np.float64)
                sample_mask = None

        if sample_mask is not None:
            rr_s, cc_s = np.nonzero(sample_mask)
            fit_source = np.column_stack([
                cc_s.astype(np.float64) * res_m,
                rr_s.astype(np.float64) * res_m,
                dsm_arr[rr_s, cc_s],
            ])
            log.info(
                "panel %d: plane fit on %d %s interior pixels",
                pid, int(sample_mask.sum()),
                "eroded" if used_erosion else "full",
            )

        try:
            plane = fit_plane(fit_source)
        except Exception as exc:
            log.warning("fit_plane failed for panel %d: %s", pid, exc)
            continue

        # Slope sanity check. If the fit still comes back absurdly steep
        # after erosion, it's almost always DSM noise near an edge the
        # user couldn't see — not real geometry. Log loudly so it shows
        # up in server logs and the user can re-label tighter.
        fitted_rise = int(slope_rise_over_12(plane.normal))
        if fitted_rise >= MAX_SANE_RISE_OVER_12:
            log.warning(
                "panel %d: fitted slope %d/12 exceeds sane max (%d/12). "
                "Likely cause: polygon drawn too close to the roof edge "
                "and DSM smoothing is bleeding wall/ground elevations "
                "into the sample. Suggest re-labeling with corners pulled "
                "~1 ft inboard from gutter/rake.",
                pid, fitted_rise, MAX_SANE_RISE_OVER_12,
            )

        # --- Build corner 3D polygon from user clicks, projected onto the
        # fitted plane so all vertices are exactly coplanar. ---
        # y = -row*res_m to match planes.py (+y = north for north-up DSMs)
        poly_3d = np.array([
            [float(cx) * res_m, -float(cy) * res_m,
             z_on_plane(float(cx) * res_m, -float(cy) * res_m, plane)]
            for cx, cy in corners_pix
        ], dtype=np.float64)

        # Rotate to horizontal for plan-view math
        R = rotation_to_horizontal(plane.normal)
        rotated = (R @ poly_3d.T).T
        xy = rotated[:, :2]
        center = xy.mean(axis=0)
        xy_centered = xy - center

        edges = []
        for j in range(len(xy_centered)):
            p1 = xy_centered[j]
            p2 = xy_centered[(j + 1) % len(xy_centered)]
            length_m = float(np.linalg.norm(p2 - p1))
            edges.append({
                "length_ft_in": meters_to_ft_in(length_m),
                "length_ft": round(length_m * M_TO_FT, 2),
            })

        area_m2 = float(polygon_area_2d(xy_centered))

        # Plan-view coords (world xy of 3D polygon, centered to roof)
        plan_xy = poly_3d[:, :2]
        plan_panels.append({
            "id": pid,
            "vertices_ft": [
                [float(v[0] * M_TO_FT), float(v[1] * M_TO_FT)]
                for v in plan_xy
            ],
        })

        panel_payloads.append({
            "id": pid,
            "area_sqft": round(area_m2 * 10.7639104, 1),
            "slope_rise": int(slope_rise_over_12(plane.normal)),
            "azimuth_deg": round(float(azimuth_degrees(plane.normal)), 1),
            "azimuth_label": _azimuth_label(
                float(azimuth_degrees(plane.normal))
            ),
            "perimeter_ft": round(sum(e["length_ft"] for e in edges), 2),
            "vertex_count": len(xy_centered),
            "vertices_ft": [
                [float(p[0] * M_TO_FT), float(p[1] * M_TO_FT)]
                for p in xy_centered
            ],
            # World-space 3D vertices in feet — for the 3D isometric view
            "vertices_3d_ft": [
                [
                    float(v[0] * M_TO_FT),
                    float(v[1] * M_TO_FT),
                    float(v[2] * M_TO_FT),
                ]
                for v in poly_3d
            ],
            "edges": edges,
        })

    total_area_sqft = sum(p["area_sqft"] for p in panel_payloads)

    return {
        "sample_id": sample_id,
        "project": {
            "address": sample.get("formatted_address")
            or sample.get("source_address")
            or None,
        },
        "totals": {
            "panel_count": len(panel_payloads),
            "total_area_sqft": round(total_area_sqft, 1),
            "average_slope_rise": (
                round(
                    sum(p["slope_rise"] for p in panel_payloads)
                    / max(len(panel_payloads), 1),
                    1,
                )
                if panel_payloads
                else 0
            ),
        },
        "plan_view": {"panels": plan_panels},
        "panels": panel_payloads,
    }
