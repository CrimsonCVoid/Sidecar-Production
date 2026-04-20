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


@router.post("/generate-pdf/{sample_id}")
async def generate_pdf(
    sample_id: str,
    request: Request,
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    """Generate a PDF from saved labels for a sample.

    Reads panel labels from training_labels, downloads DSM from storage,
    runs the pipeline synchronously, and returns the PDF file.
    """
    from fastapi.responses import Response
    from io import BytesIO

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
        .select("dsm_storage_path, formatted_address, source_address, meters_per_px")
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
):
    """Return the structured data that powers the cutsheet PDF, as JSON.

    The UI uses this to render an interactive cutsheet (clickable panels,
    selectable detail view). Exactly the same pipeline as
    /generate-pdf/{sample_id} but returns panel/plane/mesh stats as JSON
    instead of rendering a PDF.
    """
    from io import BytesIO

    from ..boundaries import extract_panel_polygons
    from ..cutsheets import (
        azimuth_degrees,
        meters_to_ft_in,
        polygon_area_2d,
        rotation_to_horizontal,
        slope_rise_over_12,
    )
    from ..planes import Plane, fit_all_panels

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

    # 4. Open DSM and rasterize labels into a mask
    import cv2
    import rasterio

    with rasterio.open(BytesIO(dsm_bytes)) as ds:
        dsm_arr = ds.read(1).astype(np.float64)
        h, w = ds.height, ds.width
        res_m = abs(ds.res[0]) if ds.res else float(
            sample.get("meters_per_px") or 0.25
        )

    mask_arr = np.zeros((h, w), dtype=np.uint8)
    for i, p in enumerate(panels):
        new_id = i + 1
        corners = np.array(p.get("corners_pix", []), dtype=np.int32)
        if len(corners) < 3:
            continue
        cv2.fillPoly(mask_arr, [corners], new_id)

    # 5. Fit a plane per panel from DSM+mask, then extract 3D polygons
    #    projected onto each fitted plane. Order matters — the signature
    #    is extract_panel_polygons(mask, dsm, res_m, planes) which uses
    #    the planes to lift 2D mask boundaries into proper 3D points.
    planes: dict[int, Plane] = fit_all_panels(dsm_arr, mask_arr)
    polygons_3d = extract_panel_polygons(mask_arr, dsm_arr, res_m, planes)

    # 6. Per-panel stats in plan view (rotated to horizontal for clean 2D)
    M_TO_FT = 3.280839895
    panel_payloads = []
    for pid in sorted(polygons_3d.keys()):
        poly = polygons_3d[pid]
        plane = planes.get(pid)
        if plane is None:
            continue

        # Rotate the 3D polygon to horizontal so plan-view math works
        R = rotation_to_horizontal(plane.normal)
        rotated = (R @ poly.T).T
        xy = rotated[:, :2]

        # Center at origin for the UI — keeps coords compact
        center = xy.mean(axis=0)
        xy_centered = xy - center

        # Edges + dimensions
        edges = []
        for i in range(len(xy_centered)):
            p1 = xy_centered[i]
            p2 = xy_centered[(i + 1) % len(xy_centered)]
            length_m = float(np.linalg.norm(p2 - p1))
            edges.append(
                {
                    "length_m": length_m,
                    "length_ft_in": meters_to_ft_in(length_m),
                    "start_ft": [float(p1[0] * M_TO_FT), float(p1[1] * M_TO_FT)],
                    "end_ft": [float(p2[0] * M_TO_FT), float(p2[1] * M_TO_FT)],
                }
            )

        area_m2 = float(polygon_area_2d(xy_centered))
        panel_payloads.append(
            {
                "id": int(pid),
                "area_sqft": round(area_m2 * 10.7639104, 1),
                "slope_rise": int(slope_rise_over_12(plane.normal)),
                "azimuth_deg": round(float(azimuth_degrees(plane.normal)), 1),
                "azimuth_label": _azimuth_label(
                    float(azimuth_degrees(plane.normal))
                ),
                "perimeter_ft": round(
                    sum(e["length_m"] for e in edges) * M_TO_FT, 2
                ),
                "vertex_count": int(len(xy_centered)),
                "vertices_ft": [
                    [float(p[0] * M_TO_FT), float(p[1] * M_TO_FT)]
                    for p in xy_centered
                ],
                "edges": [
                    {
                        "length_ft_in": e["length_ft_in"],
                        "length_ft": round(e["length_m"] * M_TO_FT, 2),
                    }
                    for e in edges
                ],
            }
        )

    # 7. Plan view for the aggregate diagram — all panels in world coords
    plan_panels = []
    for pid in sorted(polygons_3d.keys()):
        poly = polygons_3d[pid]
        # Just use raw xy from 3D polygon (top-down projection)
        plan_panels.append(
            {
                "id": int(pid),
                "vertices_ft": [
                    [float(v[0] * M_TO_FT), float(v[1] * M_TO_FT)]
                    for v in poly
                ],
            }
        )

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
