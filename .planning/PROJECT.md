# My Metal Roofer — FastAPI Sidecar + Labeling Dashboard (Milestone 2 of 2)

## What This Is

Wire the topology-aware snap engine (built in Milestone 1) into a production FastAPI endpoint and build the Next.js labeling dashboard that replaces the matplotlib CLI labeler. Includes two real-data bug fixes discovered during Milestone 1 validation that block production use on complex roofs.

## Core Value

Hip and ridge apex convergences (3+ panels) must weld to a single geometrically-correct point with zero slivers in the output mesh. Everything else — dashboard, monitor, diff viewer — serves this correctness goal.

## Current Milestone: v2.0 FastAPI Sidecar + Labeling Dashboard

**Goal:** Fix real-data bugs blocking production use, expose snap engine via FastAPI, and build the Next.js labeling dashboard with shared-node magnet, undo/redo, and snap preview.

**Target features:**
- Densify bug fix for complex hip-and-valley roofs (fb7e705c panel 8)
- Labeler duplicate-corner dedup (legacy winding.py + new Konva auto-close)
- FastAPI snap-preview endpoint on existing DigitalOcean droplet
- Next.js labeling dashboard with Konva canvas, shared-node magnet, undo/redo, snap preview
- Dashboard index with sample table, filters, diff viewer, run monitor

## Requirements

### Validated

- V [Plane fitting] SVD per panel, sky-up normal, RMS residual — existing (`planes.py`)
- V [Boundary extraction] Two polygon sources: `polygons_from_clicks` (preferred) and `extract_panel_polygons` (legacy) — existing (`boundaries.py`)
- V [Pairwise edge snap] Current midline replacement — existing (`snapping.py`, superseded by v2)
- V [Mesh build] Earcut triangulation, OBJ + glTF export — existing (`mesh.py`)
- V [Cut sheets] Multi-page dimensioned PDF — existing (`cutsheets.py`)
- V [Shop drawings] 4-page fabrication PDF — existing (`shop_drawings.py`)
- V [TS export/render] JSON export + PDF re-render — existing (`ts_export.py`, `ts_render_pdf.py`)
- V [Interactive labeler] Matplotlib clicker writing mask.json — existing CLI fallback (`label_panels.py`)
- V [Real-data pipeline] GeoTIFF DSM + labeled mask orchestration — existing (`run_real.py`)
- V [Topology engine] `panel_snap_v2` with union-find clustering, feature graph, valence-aware apex solver — Milestone 1 Phase 1+2
- V [Input validation] Pydantic schema at `polygons_from_clicks` boundary — Milestone 1 Phase 2
- V [Snap v2 integration] `--snap-v2` flag, JSON sidecar, 41 tests green — Milestone 1 Phase 2

### Active

- [ ] Densify bug fix for complex hip-and-valley roofs (make_valid MultiPolygon at 65.9%)
- [ ] Labeler duplicate-corner silent dedup in winding.py (legacy mask.json protection)
- [ ] FastAPI snap-preview endpoint wrapping `panel_snap_v2` on existing DigitalOcean droplet
- [ ] Next.js labeling dashboard with Konva canvas, shared-node magnet, undo/redo, snap preview
- [ ] Konva labeler auto-close at 10px (prevents new duplicate-corner bugs)
- [ ] Dashboard index with sample table, filter chips, diff viewer, run monitor

### Out of Scope

- 3D mesh viewer — future milestone
- Vertex drag with live re-snap — future milestone
- Edge semantic classification (ridge/hip/valley/eave/rake tagging) — future milestone
- Penetration labeling (chimneys, skylights, vents) — future milestone
- Face-segmentation NN training target — way later
- Multi-user concurrent editing — complexity not justified
- Removing the matplotlib labeler — kept as CLI fallback
- shop_drawings.py subpackage extraction — flagged by mapper as 2089 lines but deferred

## Context

- **Existing pipeline**: Pure Python CLI prototype with topology-aware snap engine (`panel_snap_v2`). Sequential: DSM raster -> 3D mesh -> PDF documents. 41 tests, 22 requirements delivered in Milestone 1.
- **My Metal Roofer**: Next.js + Supabase + DigitalOcean SaaS. DSMs arrive from Google Solar API `buildingInsights:findClosest` and get written to Supabase Storage. Existing `/labeling` route is the one being replaced.
- **Real-data bugs**: Densify produces make_valid MultiPolygon with largest piece at 65.9% on 12-panel hip-and-valley roof (fb7e705c panel 8) — correctly rejected by D-06 area threshold but blocks production use. Matplotlib labeler double-clicks first corner, producing duplicate last corners in all tested roofs.
- **Coordinate systems**: Internal geometry always in meters. Drawing output in feet-inches. TS export uses x -> -v_in, z -> u_in; render uses pageX = z * scale + 300, pageY = -x * scale + 400. Round-trip tests required per CONCERNS.md.

## Constraints

- **Python**: 3.11, existing requirements.txt. Pydantic already added in Milestone 1.
- **Frontend**: Next.js app router, existing Supabase schema. New tables allowed if justified. TypeScript everywhere, no `any`. Zod at every API boundary.
- **Infra**: FastAPI sidecar reuses existing DigitalOcean droplet. Don't spin a new one.
- **Compatibility**: Any change to `ts_export.py` or `ts_render_pdf.py` requires round-trip coordinate tests.
- **Downstream stability**: `mesh.py`, `shop_drawings.py`, `cutsheets.py`, `ts_export.py`, `ts_render_pdf.py` must keep working on the gable-roof smoke test.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Replace snap, don't delete `snapping.py` | `--snap-v2` flag keeps old path as fallback until validation passes | Validated M1 |
| Union-find with 3-pass expanding tolerance | Transitive hip apex grouping where no single pair is within tol | Validated M1 |
| Least-squares plane intersection for valence-3+ | Closed-form 3x3 for 3 planes, lstsq for 4+. Prior art: Kelly & Wonka 2011, Ren et al. SGA21 | Validated M1 |
| Pydantic schema at `polygons_from_clicks` boundary | New dashboard writes to this contract over HTTP — now a security surface | Validated M1 |
| Keep matplotlib labeler as CLI fallback | Production use moves to dashboard, but CLI fallback useful for dev/debug | Decided |
| Split into 2 milestones | Snap engine first, dashboard second. No descope, just sequencing. | Decided |
| Fix densify before FastAPI | 65.9% area loss on complex roofs blocks production — must fix before exposing via API | Pending |
| Shared-node magnet in UI (12px snap radius) | Eliminates 3-8px ridge pair drift at the source instead of correcting downstream | Milestone 2 |

## Highest-Risk Item

Densify bug on complex hip-and-valley roofs. The make_valid repair produces a MultiPolygon where the largest piece is only 65.9% of the original area — far below the D-06 threshold. This may indicate a fundamental issue with the edge-walking densification on panels that share edges with 3+ neighbors, not just a tolerance tuning problem.

## Definition of Done (Milestone 2)

1. Densify bug fixed — 12-panel hip-and-valley roof (fb7e705c) passes through `--snap-v2` without area-change rejection
2. Duplicate-corner dedup in winding.py handles legacy mask.json files silently
3. FastAPI endpoint accepts mask.json, returns feature graph + snapped polygons
4. Next.js `/labeling/[sampleId]` route with Konva canvas, shared-node magnet, undo/redo, snap preview
5. Dashboard index with sample table, filter chips, diff viewer, Supabase Realtime run monitor
6. All existing 41 tests still green + new tests for bug fixes and API

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
*Last updated: 2026-04-18 — Milestone 2 started*
