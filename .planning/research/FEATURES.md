# Feature Landscape -- Milestone 2

**Domain:** FastAPI sidecar + interactive canvas-based polygon labeling dashboard with real-time pipeline monitoring
**Researched:** 2026-04-19
**Overall confidence:** HIGH (patterns grounded in QGIS/ArcGIS prior art, Context7-verified Konva/Zustand/Supabase docs, existing codebase fully examined)

---

## Table Stakes

Features users expect. Missing = product feels incomplete or the iteration loop is broken.

### Bug Fixes (Blocking Production)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Densify bug fix (fb7e705c panel 8)** | make_valid produces MultiPolygon at 65.9% area on 12-panel hip-and-valley roof. Correctly rejected by D-06 threshold, but blocks production use on complex roofs. Cannot expose snap engine via API until fixed. | High | Root cause may be edge-walking on panels sharing edges with 3+ neighbors, not tolerance tuning. Highest-risk item per PROJECT.md. |
| **Labeler duplicate-corner dedup** | Matplotlib labeler double-clicks first corner on every tested roof, producing duplicate last corners in mask.json. Legacy files exist. `winding.py` must silently dedup. Konva labeler must auto-close at 10px to prevent new duplicates. | Med | Two-pronged: backend tolerance for legacy data + frontend prevention for new data. |

### FastAPI Sidecar

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **`POST /snap-preview`** | Dashboard value proposition is "label, preview snap, iterate" without full CLI pipeline. Wraps `panel_snap_v2.snap_polygons()`, returns feature graph JSON. Without it, dashboard is a dumb polygon editor. | Med | Input: existing `PanelsInput` schema. Output: `snap_v2_features.json` schema. Must respond <500ms for 12-panel roof. Sync endpoint. |
| **`POST /run-pipeline`** | Users need to trigger full pipeline from dashboard. Without this, they SSH into server. | Med | Background task (FastAPI `BackgroundTasks`). Progress writes to `pipeline_runs` table. Returns run ID immediately (HTTP 202). |
| **CORS configuration** | Dashboard on localhost:3000/Vercel calls sidecar on DigitalOcean:8000. Without CORS, all requests fail. | Low | `CORSMiddleware` with explicit origin list. |
| **Pydantic request/response schemas** | Contract boundary. Validates mask.json shape, snap-preview response, run-pipeline request. | Med | `MaskContractV2` (extends M1 `MaskContract` with `shared_nodes` and `dsm_key`), `SnapPreviewResponse`, `RunPipelineRequest`. |

### Konva Labeling Canvas (`/labeling/[sampleId]`)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Click-to-add polygon vertices on DSM overlay** | Core interaction replacing matplotlib labeler. Every annotation tool (CVAT, LabelMe) uses vertex-click. | Med | Konva `Stage` + `Layer` + `Image` (hillshade) + `Line` (polygon, `closed: true`) + `Circle` (vertex handles). |
| **Auto-close at first vertex (10px)** | Standard polygon annotation UX. CVAT closes on click near first vertex. Prevents duplicate-corner bug. | Low | Distance check from click to first vertex. If <10px and >=3 vertices, finalize panel. Visual indicator: first vertex pulses when cursor within range. |
| **Shared-node magnet snap (12px radius)** | The single most important UX feature. Eliminates 3-8px ridge pair drift at the source. QGIS uses 10-12px default. Without this, dashboard is no better than matplotlib. | High | On mousemove: find nearest vertex from other panels within 12px. Snap cursor. Visual indicator ("-> P3.C1"). Records shared_nodes in mask.json. Snap radius in screen pixels, constant across zoom. |
| **Shift-click override for magnet** | Standard in geometry editors (ArcGIS: Spacebar, AutoCAD: Shift). Users need to place vertices near but not at existing vertices. | Low | Check `event.shiftKey` before snap logic. Bypass magnet, use raw click position. |
| **Panel list sidebar** | Users need to see which panels exist, select them, know color mapping. CVAT/LabelMe/matplotlib labeler all show panel IDs. | Low | Sidebar with colored chips, click-to-select, vertex count. |
| **Undo/redo (Cmd+Z / Cmd+Shift+Z)** | Expected in any editor. Every annotation tool has this. | Med | Zustand + zundo `temporal()`. `partialize` excludes UI state. `limit: 100`. Keyboard binding via `useEffect`. |
| **Keyboard shortcuts** | Existing matplotlib labeler has Enter, Backspace, F, S, Q. Web editors universally support shortcuts. | Low | Enter=finalize, Backspace=undo last vertex, Delete=delete panel, Cmd+Z=undo, Cmd+Shift+Z=redo, Escape=cancel. |
| **Zoom and pan** | DSM tiles are large. Without zoom, pixel-precise corner placement is impossible. | Low | Konva `Stage` `draggable: true` for pan, `onWheel` for zoom with scale clamping [0.1x, 10x]. |
| **Save to mask.json** | Dashboard must write the same JSON schema `polygons_from_clicks()` reads. API boundary. | Med | Zod-validated on client, Pydantic-validated on server. POST to FastAPI. |
| **Load existing labels** | Users iterate: label -> run -> see errors -> re-label. Without load, start from scratch. | Med | GET endpoint returns existing mask.json. Hydrate Zustand store. Handle fresh sample (no existing labels). |

### Dashboard Index (`/labeling`)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Sample table with status badges** | Users manage multiple roofs. Need to see labeled/running/done/error status. | Low | Supabase query on samples. Columns: ID, address, status badge, last modified. |
| **Filter chips by status** | With 10+ samples, filtering is needed. | Low | Chips: needs-labeling, labeled, running, v2-verified, failed. Toggle, OR logic. |

---

## Differentiators

Features that set the product apart from generic polygon editors. High value for roof topology editing specifically.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Snap preview with valence-colored dots** | After labeling, user clicks "Preview Snap" and sees feature graph overlaid. Immediate visual verification of topology before full pipeline. Cuts iteration from minutes to seconds. | High | POST to `/snap-preview`, render as Konva overlay. Color map: `{2: "#3b82f6", 3: "#f59e0b", 4: "#ef4444"}`. Dashed lines for shared edges. Edit locked during preview. |
| **Run monitor via Supabase Realtime** | Watch pipeline execution in real-time: stage progress, timing, errors. Push-based via Postgres Changes. | Med | Pipeline writes to `pipeline_runs` table. Dashboard subscribes via `postgres_changes`. Progress bar with stage names and elapsed time. |
| **Snap residual feedback** | Show snap delta (mm), plane RMS (mm), valence per vertex. Identifies suspicious corners. | Med | Data from snap_v2_features.json. Tooltip on hover over snap preview dots. |
| **Diff viewer** | Side-by-side comparison of two pipeline runs on same sample. Shows which vertices moved, edges changed. | High | Compare two feature graph JSONs. Overlay: green=added, red=removed, yellow=moved. Needs >=2 completed runs. |

---

## Anti-Features

Features to explicitly NOT build in Milestone 2.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Multi-user concurrent editing** | PROJECT.md excludes. CRDT for geometric data is enormous complexity. | Single-user locking via `locked_by` column. |
| **AI/SAM auto-labeling** | Input is DSM (elevation), not RGB. SAM does not work on elevation data. | Manual labeling with magnet snap addresses the accuracy pain point. |
| **3D mesh viewer** | Three.js adds ~200KB bundle. 2D feature graph overlay is more actionable. | Download links for OBJ/glTF. Feature graph overlay on 2D DSM. |
| **Vertex drag with live re-snap** | Requires client-side KD-tree. High complexity, only valuable after core loop works. | Delete-and-re-add is sufficient for v1. Defer. |
| **Edge semantic classification** | PROJECT.md defers to next milestone. Requires validated feature graph first. | Feature graph valence implies edge type. Explicit tagging later. |
| **Removing matplotlib labeler** | PROJECT.md keeps as CLI fallback. Works offline. | Keep `label_panels.py` untouched. |
| **shop_drawings.py refactoring** | 2089 lines but works. No bugs related to M2. | Do not refactor. Minimal surgical edits only if forced. |
| **Custom snap tolerance UI** | Confuses end users. Default t=1.0m handles 95% of residential roofs. | Hardcode default. `--snap-tol` CLI only. |
| **Freehand/bezier tools** | Roof panels have straight edges. Curves add complexity without value. | Click-to-add-vertex with straight edges. |

---

## Feature Dependencies

```
Densify bug fix ---------> FastAPI /snap-preview (engine must be correct)
                               |
Duplicate-corner dedup --> FastAPI /run-pipeline (handles legacy mask.json)
                               |
                               v
                    Pydantic schemas (MaskContractV2, SnapPreviewResponse)
                               |
                    +---------+---------+
                    |                   |
                    v                   v
           Konva canvas          Dashboard index
           (click, magnet,       (sample table,
            undo, save/load)      filter chips)
                    |                   |
                    v                   v
           Snap preview overlay   Run monitor
           (calls /snap-preview)  (Supabase Realtime)
                    |                   |
                    v                   v
             Diff viewer (needs >= 2 completed runs)
```

## MVP Recommendation

### Phase 1: Bug Fixes (Python)
1. Densify bug on complex hip-and-valley roofs
2. Duplicate-corner dedup in winding.py

### Phase 2: FastAPI Sidecar + Schemas (Python)
1. Pydantic schemas (MaskContractV2, SnapPreviewResponse, RunPipelineRequest)
2. `/snap-preview` endpoint (sync, <500ms)
3. `/run-pipeline` endpoint (background task + Supabase status writes)
4. CORS middleware
5. Supabase `pipeline_runs` table + Realtime publication

### Phase 3: Labeling Canvas Core (Next.js)
1. Konva Stage + Layers + DSM image
2. Click-to-add vertices with polygon rendering
3. Auto-close at 10px
4. Shared-node magnet snap (12px, shift override)
5. Panel sidebar with color-coded IDs
6. Undo/redo (Zustand + zundo)
7. Keyboard shortcuts
8. Zoom/pan
9. Save/load mask.json

### Phase 4: Dashboard Index + Monitoring (Next.js)
1. Sample table with status badges
2. Filter chips
3. Snap preview toggle (calls FastAPI, renders overlay)
4. Run monitor (Supabase Realtime subscription)

### Defer:
- **Diff viewer:** Needs >=2 completed runs per sample. Build after real data flows.
- **Snap residual feedback:** Valuable but not blocking. Add after core loop validates.
- **PDF preview embed:** Low priority. Users download for now.

---

## Sources

### HIGH Confidence (Context7 or official docs)
- [Konva -- Objects Snapping](https://konvajs.org/docs/sandbox/Objects_Snapping.html) -- proximity threshold, snap logic
- [Konva -- Undo/Redo](https://konvajs.org/docs/react/Undo-Redo.html) -- history array pattern
- [zundo v2](https://github.com/charkour/zundo) -- temporal, partialize, limit, handleSet
- [Supabase -- Realtime postgres_changes](https://supabase.com/docs/guides/realtime/subscribing-to-database-changes)
- [QGIS 3.44 -- Editing/Snapping](https://docs.qgis.org/3.44/en/docs/user_manual/working_with_vector/editing_geometry_attributes.html) -- 10-12px snap radius
- [ArcGIS Pro -- About Snapping](https://pro.arcgis.com/en/pro-app/latest/help/editing/enable-snapping.htm)

### MEDIUM Confidence (multiple sources agree)
- [DevMuscle -- React Konva Polygon Annotation](https://devmuscle.com/blog/react-konva-image-annotation) -- PROXIMITY_THRESHOLD=10
- [CVAT](https://www.cvat.ai/) -- auto-close, keyboard shortcuts, polygon UX

---
*Features landscape for Milestone 2: 2026-04-19*
