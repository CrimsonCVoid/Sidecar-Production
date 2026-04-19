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
from .deps import get_settings, get_supabase
from .config import Settings
from .schemas import PipelineRunCreated, PipelineRunRequest, PipelineRunStatus

log = logging.getLogger(__name__)

router = APIRouter()


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
        # For MVP: load sample metadata from Supabase to get file paths
        sample_result = supabase.table("samples").select("*").eq("id", sample_id).execute()
        if not sample_result.data:
            raise ValueError(f"Sample {sample_id} not found in samples table")

        sample = sample_result.data[0]

        # Download DSM and mask files from Supabase Storage to a temp directory
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Download DSM .tif
            dsm_storage_path = sample.get("dsm_path")
            if not dsm_storage_path:
                raise ValueError(f"Sample {sample_id} has no dsm_path")
            dsm_bytes = supabase.storage.from_(settings.storage_bucket).download(dsm_storage_path)
            dsm_local = tmp_path / "dsm.tif"
            dsm_local.write_bytes(dsm_bytes)

            # Download mask .npy
            mask_storage_path = sample.get("mask_path")
            if not mask_storage_path:
                raise ValueError(f"Sample {sample_id} has no mask_path")
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
async def list_samples(request: Request):
    """List all samples with their latest pipeline run status (DIDX-01).

    Returns each sample joined with the most recent pipeline_runs row
    so the dashboard can show address, panel count, and run status.
    Gracefully returns an empty list when Supabase credentials are missing.
    """
    try:
        settings = Settings()
    except Exception:
        log.warning("Supabase credentials not configured -- returning empty samples list")
        return []

    from supabase import create_client

    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)

    samples_result = supabase.table("samples").select("*").execute()
    samples = samples_result.data or []

    # Fetch latest run per sample in one query, ordered by started_at desc
    runs_result = (
        supabase.table("pipeline_runs")
        .select("sample_id, status, progress_pct, started_at, completed_at, output_paths")
        .order("started_at", desc=True)
        .execute()
    )
    # Build map of sample_id -> latest run (first occurrence wins due to desc order)
    latest_runs: dict[str, dict] = {}
    for run in runs_result.data or []:
        sid = run["sample_id"]
        if sid not in latest_runs:
            latest_runs[sid] = run

    result = []
    for s in samples:
        sid = s["id"]
        run = latest_runs.get(sid)
        result.append({
            "id": sid,
            "address": s.get("address", sid),
            "panel_count": s.get("panel_count", 0),
            "latest_run_status": run["status"] if run else None,
            "latest_run_progress": run.get("progress_pct", 0) if run else None,
            "latest_run_started": run.get("started_at") if run else None,
            "latest_run_completed": run.get("completed_at") if run else None,
            "pdf_path": (run.get("output_paths") or {}).get("cutsheets_pdf") if run else None,
        })

    return result


@router.post("/run", status_code=202, response_model=PipelineRunCreated)
async def trigger_pipeline_run(
    body: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    """Trigger a full pipeline run as a background task (API-02, D-09).

    Returns 202 Accepted immediately with run_id and status_url.
    The pipeline runs asynchronously and writes status updates to the
    pipeline_runs Supabase table at each stage boundary.
    """
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
):
    """Get current status of a pipeline run (API-02).

    Returns the pipeline_runs row for the given run_id.
    Frontend polls this endpoint or subscribes via Supabase Realtime.
    """
    result = supabase.table("pipeline_runs").select("*").eq("id", run_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    row = result.data[0]
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
