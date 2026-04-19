# Topology-Aware Snap + Web Labeling Dashboard

## What This Is

A correctness-focused upgrade to the roof_pipeline snapping engine and a production labeling dashboard for My Metal Roofer. The current pairwise edge snap in `snapping.py` cannot handle 3+ panels meeting at hip/ridge apices, producing slivers and gaps in the mesh. This milestone replaces it with a topology-aware snap engine (`panel_snap_v2`) that mesh-weld-snaps ridges and hip apices geometrically, and wires it into a Next.js labeling dashboard with shared-node magnets, undo, snap preview, run monitoring, and diff viewing.

## Core Value

Hip and ridge apex convergences (3+ panels) must weld to a single geometrically-correct point with zero slivers in the output mesh. Everything else — dashboard, monitor, diff viewer — serves this correctness goal.

## Requirements

### Validated

- V [Plane fitting] SVD per panel, sky-up normal, RMS residual — existing (`planes.py`)
- V [Boundary extraction] Two polygon sources: `polygons_from_clicks` (preferred) and `extract_panel_polygons` (legacy) — existing (`boundaries.py`)
- V [Pairwise edge snap] Current midline replacement — existing (`snapping.py`, being superseded not deleted)
- V [Mesh build] Earcut triangulation, OBJ + glTF export — existing (`mesh.py`)
- V [Cut sheets] Multi-page dimensioned PDF — existing (`cutsheets.py`)
- V [Shop drawings] 4-page fabrication PDF — existing (`shop_drawings.py`)
- V [TS export/render] JSON export + PDF re-render — existing (`ts_export.py`, `ts_render_pdf.py`)
- V [Interactive labeler] Matplotlib clicker writing mask.json — existing CLI fallback (`label_panels.py`)
- V [Real-data pipeline] GeoTIFF DSM + labeled mask orchestration — existing (`run_real.py`)

### Active

- [ ] Topology-aware snap engine (`panel_snap_v2`) with union-find clustering, feature graph, and valence-aware apex solver
- [ ] Multi-pass expanding tolerance (0.3t -> 0.6t -> t) for transitive hip apex grouping
- [ ] Non-convex (L-shaped) panel winding normalization
- [ ] Valence-3+ apex solving via least-squares plane intersection
- [ ] Edge-walking densify for shared edges
- [ ] Shapely polygon validation pass with buffer(0) repair
- [ ] JSON schema validation at `polygons_from_clicks` boundary (Pydantic or dataclass)
- [ ] `--snap-v2` flag in `run_real.py` routing to new engine
- [ ] `snap_v2_features.json` sidecar output (feature graph + edges)
- [ ] 7 specific tests proving correctness (gable unchanged, hip apex weld, ridge weld, transitive cluster, mixed winding, self-intersecting repair, L-shaped winding)
- [ ] FastAPI snap-preview endpoint on existing DigitalOcean droplet
- [ ] Next.js labeling dashboard (`/labeling/[sampleId]`) with Konva canvas, Zustand state, shared-node magnet, undo/redo
- [ ] Shared-node magnet UX: 12px snap radius, shift-click override, visual label ("-> P3.C1")
- [ ] Snap preview mode rendering feature graph with valence-colored dots
- [ ] Comprehensive dashboard (`/labeling` index): sample table, filter chips, feature graph expand, PDF preview, diff viewer, run monitor via Supabase Realtime

### Out of Scope

- Edge semantic classification (ridge/hip/valley/eave/rake tagging) — next milestone
- Penetration labeling (chimneys, skylights, vents) — next milestone
- Face-segmentation NN training target — way later
- Multi-user concurrent editing — complexity not justified for v1
- Removing the matplotlib labeler — kept as CLI fallback
- shop_drawings.py subpackage extraction — flagged by mapper as 2089 lines but deferred; do not plan refactor work this milestone

## Context

- **Existing pipeline**: Pure Python CLI prototype. Sequential: DSM raster -> 3D mesh -> PDF documents. No web framework, no database, no API server.
- **My Metal Roofer**: Next.js + Supabase + DigitalOcean SaaS. DSMs arrive from Google Solar API `buildingInsights:findClosest` and get written to Supabase Storage. Existing `/labeling` route is the one being replaced.
- **The core problem**: Pairwise edge snap cannot handle 3+ panels meeting at a point. Polygons converge to centroids that don't lie on every panel's plane, creating triangular white gaps. This is a correctness issue, not primarily a performance issue (though O(N^2) scaling improves as a side effect).
- **Secondary UX problems**: No snap-to-existing-corner affordance in labeler (3-8px ridge pair drift), no undo, no panel list, no plane-residual feedback, no edge semantics.
- **Coordinate systems**: Internal geometry always in meters. Drawing output in feet-inches. TS export uses x -> -v_in, z -> u_in; render uses pageX = z * scale + 300, pageY = -x * scale + 400. Round-trip tests required per CONCERNS.md.

## Constraints

- **Python**: 3.11, existing requirements.txt. No new deps in the pipeline module (shapely and scipy already present).
- **Frontend**: Next.js app router, existing Supabase schema. New tables allowed if justified. TypeScript everywhere, no `any`. Zod at every API boundary.
- **Infra**: FastAPI sidecar reuses existing DigitalOcean droplet. Don't spin a new one.
- **Compatibility**: Any change to `ts_export.py` or `ts_render_pdf.py` requires round-trip coordinate tests.
- **Downstream stability**: `mesh.py`, `shop_drawings.py`, `cutsheets.py`, `ts_export.py`, `ts_render_pdf.py` must keep working bit-for-bit on the gable-roof smoke test.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Replace snap, don't delete `snapping.py` | `--snap-v2` flag keeps old path as fallback until validation passes | -- Pending |
| Union-find with 3-pass expanding tolerance | Transitive hip apex grouping where no single pair is within tol | -- Pending |
| Least-squares plane intersection for valence-3+ | Closed-form 3x3 for 3 planes, lstsq for 4+. Prior art: Kelly & Wonka 2011, Ren et al. SGA21 | -- Pending |
| Shared-node magnet in UI (12px snap radius) | Eliminates 3-8px ridge pair drift at the source instead of correcting downstream | -- Pending |
| Keep matplotlib labeler as CLI fallback | Production use moves to dashboard, but CLI fallback useful for dev/debug | -- Pending |
| Pydantic/dataclass schema at `polygons_from_clicks` boundary | New dashboard writes to this contract over HTTP — now a security surface | -- Pending |

## Highest-Risk Item

Winding normalization on non-convex (L-shaped) panels. Shoelace-signed-area says "flip" on an L-shape when vertex order relative to an interior notch is wrong. Feature graph corrupts invisibly, mesh export fails three phases later. Phase 1 must address non-convex winding explicitly with dedicated test.

## Researcher Focus

Prior art on multi-plane apex solving: Kelly & Wonka 2011, Ren et al. SGA21 (`llorz/SGA21_roofOptimization`), PolyFit / CGAL roof pipelines. Not for reimplementation — steal residual weighting choices in their LS solvers.

## Definition of Done

1. `pytest roof_pipeline/panel_snap_v2_test.py` green
2. `run_real.py --snap-v2 <hip_roof_sample>` produces a PDF with zero visible slivers at the hip apex
3. Next.js labeler loads a DSM, labels a 4-panel hip roof end-to-end with shared-node magnets working, writes mask.json that `run_real.py --snap-v2` consumes without error
4. Dashboard shows the sample with "v2-verified / clean" badge
5. Second run with one corner moved renders a diff showing exactly which edge changed

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-18 after initialization*
