---
phase: 05-labeling-dashboard
plan: 02
subsystem: ui
tags: [react-konva, canvas, polygon-drawing, magnet-snap, auto-close, dynamic-import]

# Dependency graph
requires:
  - phase: 05-labeling-dashboard
    plan: 01
    provides: Zustand store, API client, schemas, Next.js scaffold
provides:
  - Konva canvas with hillshade image loading, pan/zoom, polygon drawing
  - Shared-node magnet snap at 12px radius with shift override
  - Auto-close indicator at 10px radius from first vertex
  - Completed polygon rendering with 16-color panel palette
  - Dynamic import of canvas (SSR-safe)
  - Label loading on page mount via getLabels API
affects: [05-03, 05-04, 05-05]

# Tech tracking
tech-stack:
  added: []
  patterns: [konva-dynamic-import, magnet-snap-euclidean, image-space-coordinates, resize-observer-canvas]

key-files:
  created:
    - frontend/src/components/canvas/HillshadeCanvas.tsx
    - frontend/src/components/canvas/PolygonLayer.tsx
    - frontend/src/components/canvas/DrawingLayer.tsx
    - frontend/src/components/canvas/MagnetIndicator.tsx
    - frontend/src/components/canvas/AutoCloseIndicator.tsx
    - frontend/src/lib/errors.ts
  modified:
    - frontend/src/app/labeling/[sampleId]/page.tsx

key-decisions:
  - "Cursor position stored in React local state (not Zustand) to avoid undo explosion per Pitfall 3"
  - "Stage always renders even without hillshade image (gray placeholder text shown until loaded)"
  - "Coordinate transforms use image space: (pos.x - stage.x()) / stage.scaleX()"

requirements-completed: [DASH-01, DASH-02, DASH-06]

# Metrics
duration: 5min
completed: 2026-04-19
---

# Phase 5 Plan 02: Konva Canvas + Polygon Drawing Summary

**Konva canvas with magnet snap (12px, shift override), auto-close (10px), 16-color palette polygons, and dynamic import for SSR safety**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-19T18:31:04Z
- **Completed:** 2026-04-19T18:36:06Z
- **Tasks:** 2/2
- **Files created:** 6
- **Files modified:** 1

## Accomplishments

- HillshadeCanvas renders in the browser via dynamic import (no SSR crash)
- Clicking canvas in draw mode places vertices (white circles appear via DrawingLayer)
- Magnet snap indicator (yellow ring) appears within 12px of existing vertex from another panel
- Shift+click bypasses magnet snap (e.evt.shiftKey check)
- Auto-close indicator (green ring) appears within 10px of first vertex when >= 3 vertices drawn
- Completed polygons render with palette colors (16 colors, cycling) and panel ID label at centroid
- Pan/zoom works via mouse wheel with focal-point zoom
- Labels load from API on mount (404 = empty state, error = toast)
- ResizeObserver keeps canvas dimensions responsive to container

## Task Commits

Each task was committed atomically:

1. **Task 1: Create canvas component hierarchy** - `e1725c5` (feat)
2. **Task 2: Wire dynamic import in labeling page** - `9423490` (feat)

## Files Created/Modified

- `frontend/src/components/canvas/HillshadeCanvas.tsx` - Main Konva Stage wrapper with pan/zoom, magnet snap, auto-close, click handlers (195 lines)
- `frontend/src/components/canvas/PolygonLayer.tsx` - Completed polygon rendering with palette colors, centroid labels, vertex circles (78 lines)
- `frontend/src/components/canvas/DrawingLayer.tsx` - In-progress polyline with ghost line to cursor (53 lines)
- `frontend/src/components/canvas/MagnetIndicator.tsx` - Yellow ring at 12px radius snap target (24 lines)
- `frontend/src/components/canvas/AutoCloseIndicator.tsx` - Green ring at 10px radius close target (24 lines)
- `frontend/src/lib/errors.ts` - Stub initErrorCapture for Plan 04 (3 lines)
- `frontend/src/app/labeling/[sampleId]/page.tsx` - Rewritten with dynamic import, label loading, header, toolbar placeholder

## Decisions Made

- Cursor position stored in React local state to avoid zundo undo explosion (Pitfall 3 mitigation)
- Stage renders unconditionally even without hillshade image (shows "Loading hillshade..." text)
- All coordinates stored in image space (transformed from stage coords via scale/position)
- PolygonLayer uses hex color + alpha suffix (`#06b6d440` for fill, `#06b6d4cc` for stroke) for performance

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

| File | Line | Content | Reason |
|------|------|---------|--------|
| frontend/src/lib/errors.ts | 2 | `initErrorCapture` returns no-op | Intentional: Plan 04 provides full implementation |
| frontend/src/app/labeling/[sampleId]/page.tsx | 75 | Save button placeholder comment | Intentional: Plan 04 wires save functionality |
| frontend/src/app/labeling/[sampleId]/page.tsx | 81 | Toolbar text placeholder | Intentional: Plan 03 adds keyboard shortcuts and toolbar buttons |

All stubs are intentional scaffolding per plan scope. Plans 03 and 04 replace them.

## Self-Check: PASSED

All 7 files verified present. Both commit hashes (e1725c5, 9423490) verified in git log. `tsc --noEmit` passes. `next build` exits 0.

---
*Phase: 05-labeling-dashboard*
*Completed: 2026-04-19*
