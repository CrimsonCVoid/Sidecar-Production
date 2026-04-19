---
phase: 05-labeling-dashboard
plan: 01
subsystem: ui, api
tags: [next.js, react-konva, zustand, zundo, zod, shadcn, fastapi, browser-errors]

# Dependency graph
requires:
  - phase: 04-fastapi-sidecar
    provides: FastAPI app with CORS, middleware, snap/labels/pipeline routers
provides:
  - Next.js 15 project scaffold in frontend/ with dark theme and shadcn
  - Zod schemas mirroring all Pydantic models (PanelCorners, PanelsInput, FeatureNode, SnapPreviewResponse, LabelData, BrowserError)
  - Typed fetch wrapper with Zod validation at every API boundary
  - Zustand + zundo labeler store with temporal middleware and correct partialize
  - Supabase client singleton for Storage URL generation
  - POST /api/errors endpoint for browser error capture (OBSERVABILITY-01b)
affects: [05-02, 05-03, 05-04, 05-05]

# Tech tracking
tech-stack:
  added: [next@15.5.15, react@19.1.0, react-konva@19.2.3, konva@10.2.5, zustand@5.0.12, zundo@2.3.0, zod@4.3.6, @supabase/supabase-js, sonner, lucide-react, shadcn, tailwindcss@4]
  patterns: [zustand-temporal-partialize, zod-pydantic-mirror, typed-api-fetch-wrapper, fire-and-forget-error-reporting]

key-files:
  created:
    - frontend/src/lib/schemas.ts
    - frontend/src/lib/api.ts
    - frontend/src/lib/supabase.ts
    - frontend/src/stores/labeler-store.ts
    - frontend/src/app/labeling/[sampleId]/page.tsx
    - frontend/src/app/layout.tsx
    - frontend/next.config.ts
    - roof_pipeline/api/errors.py
  modified:
    - roof_pipeline/api/main.py

key-decisions:
  - "Used --legacy-peer-deps for react-konva peer dep resolution (react 19.1.0 vs ^19.2.0 requirement)"
  - "Added .npmrc to frontend/ with legacy-peer-deps=true for consistent installs"
  - "Panel palette placeholder text intentional -- Plan 02 replaces with HillshadeCanvas dynamic import"

patterns-established:
  - "Zod schema files include source comment: // Mirrors: roof_pipeline/path::ClassName"
  - "API fetch wrapper validates every response through Zod schema before use"
  - "Zustand temporal partialize excludes UI state (mode, selectedPanelIndex, snapPreview, isSaving, isLoadingPreview)"
  - "nextPanelId monotonic counter avoids ID reuse after deletion (Pitfall 7)"
  - "webpack canvas external in next.config.ts for Konva SSR compatibility"

requirements-completed: [DASH-01, OBSERVABILITY-01b, DASH-05]

# Metrics
duration: 6min
completed: 2026-04-19
---

# Phase 5 Plan 01: Frontend Scaffold + API Foundation Summary

**Next.js 15 app with Zustand+zundo store, Zod-validated API client mirroring Pydantic models, and POST /api/errors endpoint for browser error capture**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-19T18:19:53Z
- **Completed:** 2026-04-19T18:26:27Z
- **Tasks:** 2
- **Files modified:** 33

## Accomplishments
- Next.js 15 project scaffolded with shadcn (button, tooltip, badge, separator, sonner, alert-dialog), Tailwind 4, dark theme
- Zod schemas mirror all 6 Pydantic models field-for-field with source comments
- Typed API client with Zod validation at every boundary (getLabels, saveLabels, snapPreview, reportError)
- Zustand store with zundo temporal middleware, correct partialize, and nextPanelId monotonic counter
- POST /api/errors endpoint mounted on FastAPI sidecar for OBSERVABILITY-01b browser error capture

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold Next.js project, install deps, configure for Konva** - `b64ba48` (feat)
2. **Task 2: Create Zod schemas, API client, Zustand store, and backend errors endpoint** - `1288ed7` (feat)

## Files Created/Modified
- `frontend/package.json` - Next.js 15 project with all deps
- `frontend/next.config.ts` - Webpack canvas external for Konva compatibility
- `frontend/src/app/layout.tsx` - Root layout with Inter font, dark theme, Toaster, TooltipProvider
- `frontend/src/app/page.tsx` - Redirect to /labeling/demo
- `frontend/src/app/labeling/[sampleId]/page.tsx` - Stub labeling page with header, toolbar, canvas placeholders
- `frontend/src/lib/schemas.ts` - Zod schemas mirroring PanelCorners, PanelsInput, FeatureNode, SnapPreviewResponse, LabelData, BrowserError
- `frontend/src/lib/api.ts` - Typed fetch wrapper with Zod validation and error handling
- `frontend/src/lib/supabase.ts` - Supabase client singleton
- `frontend/src/stores/labeler-store.ts` - Zustand + zundo store with panels, activeDrawing, mode, actions
- `frontend/src/components/ui/` - shadcn components (button, tooltip, badge, separator, sonner, alert-dialog)
- `frontend/.npmrc` - legacy-peer-deps=true for react-konva compatibility
- `roof_pipeline/api/errors.py` - POST /api/errors endpoint with BrowserError Pydantic model
- `roof_pipeline/api/main.py` - Added errors_router mount

## Decisions Made
- Used --legacy-peer-deps: react-konva 19.2.3 requires react ^19.2.0 but create-next-app@15 installed react 19.1.0. The core functionality is compatible; peer dep resolution is the only friction.
- Added .npmrc with legacy-peer-deps=true so future npm installs in the frontend/ directory resolve cleanly without manual flags.
- Canvas/toolbar placeholder text is intentional per plan scope -- Plan 02 replaces with dynamic Konva import.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Resolved react-konva peer dependency conflict**
- **Found during:** Task 1 (npm install)
- **Issue:** react-konva@19.2.3 requires react ^19.2.0 but create-next-app@15 installed react 19.1.0
- **Fix:** Added .npmrc with legacy-peer-deps=true; used --legacy-peer-deps flag
- **Files modified:** frontend/.npmrc
- **Verification:** npm install succeeds, build passes, tsc --noEmit clean
- **Committed in:** b64ba48 (Task 1 commit)

**2. [Rule 3 - Blocking] Removed nested .git directory from frontend/**
- **Found during:** Task 1 (git add)
- **Issue:** create-next-app created a nested .git repository inside frontend/, causing git to treat it as a submodule
- **Fix:** Removed frontend/.git directory so files are tracked in the main repo
- **Files modified:** (no file changes, just git index cleanup)
- **Verification:** git add frontend/ works without embedded repository warning
- **Committed in:** b64ba48 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes were necessary to unblock installation and committing. No scope creep.

## Known Stubs

| File | Line | Content | Reason |
|------|------|---------|--------|
| frontend/src/app/labeling/[sampleId]/page.tsx | 18 | "Toolbar placeholder" | Intentional: Plan 02 adds LabelingToolbar component |
| frontend/src/app/labeling/[sampleId]/page.tsx | 22 | "Canvas placeholder" | Intentional: Plan 02 adds HillshadeCanvas via dynamic import |

Both stubs are intentional scaffolding per plan scope. Plan 02 replaces them with functional components.

## Issues Encountered
- shadcn init required removing pre-existing components.json (created by initial failed attempt) -- resolved by deleting and re-running.
- shadcn `toast` component is deprecated in favor of `sonner` -- used `sonner` instead as recommended.

## User Setup Required
None - no external service configuration required. The .env.local has empty Supabase credentials which are only needed when connecting to a real Supabase instance.

## Next Phase Readiness
- Frontend scaffold complete, ready for Plan 02 (HillshadeCanvas component, PolygonLayer, DrawingLayer)
- Zustand store API is stable for all subsequent plans to consume
- Zod schemas provide compile-time safety for all API interactions
- POST /api/errors endpoint ready to receive browser errors once error capture hook is wired in Plan 02+

## Self-Check: PASSED

All 8 key files exist. Both commit hashes (b64ba48, 1288ed7) verified in git log.

---
*Phase: 05-labeling-dashboard*
*Completed: 2026-04-19*
