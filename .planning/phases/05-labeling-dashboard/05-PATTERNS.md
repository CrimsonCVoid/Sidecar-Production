# Phase 5: Labeling Dashboard - Pattern Map

**Mapped:** 2026-04-19
**Files analyzed:** 20 new files
**Analogs found:** 14 / 20 (backend analogs for API/schema files; no frontend analogs -- greenfield Next.js)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `frontend/next.config.ts` | config | -- | none (research pattern) | no-analog |
| `frontend/src/app/layout.tsx` | provider | -- | none (research pattern) | no-analog |
| `frontend/src/app/page.tsx` | route | request-response | none (trivial redirect) | no-analog |
| `frontend/src/app/labeling/[sampleId]/page.tsx` | route | request-response | `roof_pipeline/api/labels.py` | partial |
| `frontend/src/components/canvas/HillshadeCanvas.tsx` | component | event-driven | none (Konva greenfield) | no-analog |
| `frontend/src/components/canvas/PolygonLayer.tsx` | component | event-driven | none (Konva greenfield) | no-analog |
| `frontend/src/components/canvas/DrawingLayer.tsx` | component | event-driven | none (Konva greenfield) | no-analog |
| `frontend/src/components/canvas/SnapPreviewLayer.tsx` | component | request-response | `roof_pipeline/api/snap.py` | partial |
| `frontend/src/components/canvas/MagnetIndicator.tsx` | component | event-driven | none (Konva greenfield) | no-analog |
| `frontend/src/components/canvas/AutoCloseIndicator.tsx` | component | event-driven | none (Konva greenfield) | no-analog |
| `frontend/src/components/labeling/LabelingHeader.tsx` | component | -- | none (UI-SPEC contract) | no-analog |
| `frontend/src/components/labeling/LabelingToolbar.tsx` | component | event-driven | none (UI-SPEC contract) | no-analog |
| `frontend/src/lib/api.ts` | service | request-response | `roof_pipeline/api/snap.py` + `labels.py` | role-match |
| `frontend/src/lib/schemas.ts` | model | transform | `roof_pipeline/panel_snap_v2/schema.py` + `api/schemas.py` | exact |
| `frontend/src/lib/supabase.ts` | config | -- | `roof_pipeline/api/deps.py` | partial |
| `frontend/src/lib/errors.ts` | utility | event-driven | `roof_pipeline/api/middleware.py` | role-match |
| `frontend/src/stores/labeler-store.ts` | store | event-driven | none (research pattern) | no-analog |
| `frontend/src/hooks/use-keyboard-shortcuts.ts` | hook | event-driven | none (research pattern) | no-analog |
| `frontend/src/hooks/use-canvas-size.ts` | hook | event-driven | none (research pattern) | no-analog |
| `frontend/e2e/labeler.spec.ts` | test | request-response | `roof_pipeline/api/tests/test_snap.py` + `test_labels.py` | partial |
| `frontend/playwright.config.ts` | config | -- | none (research pattern) | no-analog |

## Pattern Assignments

### `frontend/src/lib/schemas.ts` (model, transform)

**Analog:** `roof_pipeline/panel_snap_v2/schema.py` (lines 1-64) + `roof_pipeline/api/schemas.py` (lines 1-100)

This is the highest-fidelity mirror in the project. Every Zod schema must match its Pydantic counterpart field-for-field.

**PanelCorners Pydantic source** (`roof_pipeline/panel_snap_v2/schema.py` lines 16-54):
```python
class PanelCorners(BaseModel):
    """One panel's click data: integer ID and list of [col_px, row_px] corners."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: int
    corners_pix: list[list[float]]

    @field_validator("corners_pix")
    @classmethod
    def strip_close_polygon_duplicate(cls, v: list[list[float]]) -> list[list[float]]:
        # ... strips duplicate last corner if it matches first within 0.5px
        # NOTE: This server-side validator does NOT need a Zod mirror.
        # The Zod schema enforces min(3) but dedup is backend-only.

    @field_validator("corners_pix")
    @classmethod
    def at_least_three_corners(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError(f"need >= 3 corners to form a polygon, got {len(v)}")
        return v
```

**PanelsInput Pydantic source** (`roof_pipeline/panel_snap_v2/schema.py` lines 57-64):
```python
class PanelsInput(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    panels: list[PanelCorners]
    res_m: float | None = None
    shape: list[int] | None = None
    panel_count: int | None = None
    panel_pixel_counts: dict[str, int] | None = None
```

**SnapPreviewResponse + FeatureNode Pydantic source** (`roof_pipeline/api/schemas.py` lines 16-37):
```python
class FeatureNode(BaseModel):
    """One feature in the snap feature graph."""
    id: int
    valence: int
    position_xyz: list[float] | None
    panel_ids: list[int]

class FeatureEdge(BaseModel):
    """One edge in the snap feature graph."""
    panel_a: int
    panel_b: int
    feature_ids: list[int]

class SnapPreviewResponse(BaseModel):
    """Response from POST /snap-preview (API-01)."""
    feature_graph: dict  # {features: [...], edges: [...]}
    snapped_polygons: dict[str, list[list[float]]]  # panel_id -> [[x,y,z],...]
```

**LabelData Pydantic source** (`roof_pipeline/api/schemas.py` lines 83-87):
```python
class LabelData(BaseModel):
    """Panel label data for POST/GET /labels/{sampleId} (API-03, D-07 stub)."""
    sample_id: str
    panels: list[dict]  # Schema TBD per D-07, Phase 5 owns
```

**ErrorResponse Pydantic source** (`roof_pipeline/api/schemas.py` lines 94-99):
```python
class ErrorResponse(BaseModel):
    """Standard error response shape."""
    error_type: str
    message: str
    trace_id: str | None = None
```

**Zod mapping rules:**
- `int` -> `z.number().int()`
- `float` -> `z.number()`
- `list[X]` -> `z.array(X)`
- `X | None` -> `z.X().nullable()`
- `X | None = None` -> `z.X().nullable().optional()`
- `list[list[float]]` with min 3 corners -> `z.array(z.array(z.number()).length(2)).min(3)`
- `dict[str, X]` -> `z.record(z.string(), X)`
- `ConfigDict(strict=True, extra="forbid")` -> Zod `.strict()` on the object (strips unknown keys)

---

### `frontend/src/lib/api.ts` (service, request-response)

**Analog:** `roof_pipeline/api/snap.py` (lines 58-95) + `roof_pipeline/api/labels.py` (lines 30-91)

The API client must call the same endpoints with the same request/response shapes.

**Snap preview endpoint contract** (`roof_pipeline/api/snap.py` lines 58-95):
```python
@router.post("/preview", response_model=SnapPreviewResponse)
async def snap_preview(body: PanelsInput, request: Request):
    # Mounted at /api/snap, so full path is: POST /api/snap/preview
    # Request body: PanelsInput (panels array + optional res_m, shape, etc.)
    # Success: 200 with SnapPreviewResponse
    # Empty panels: 422
    # ValueError: 422
    # RuntimeError: 500
```

**Labels endpoint contract** (`roof_pipeline/api/labels.py` lines 30-91):
```python
@router.post("/{sample_id}")
async def save_labels(sample_id: str, body: LabelData, ...):
    # Full path: POST /api/labels/{sampleId}
    # Request body: LabelData { sample_id, panels }
    # Success: 200 with { status: "saved", sample_id, panel_count }
    # Supabase error: 500

@router.get("/{sample_id}")
async def get_labels(sample_id: str, ...):
    # Full path: GET /api/labels/{sampleId}
    # Success: 200 with LabelData { sample_id, panels }
    # Not found: 404 with { detail: "No labels found for sample {sampleId}" }
```

**Error response shape** from global handler (`roof_pipeline/api/main.py` lines 80-122):
```python
# All error responses use ErrorResponse shape:
# { error_type: str, message: str, trace_id: str | None }
# Plus X-Trace-ID header on every response
```

**CORS configuration** (`roof_pipeline/api/main.py` lines 36-57):
```python
_cors_origins: list[str] = ["http://localhost:3000"]
# Frontend MUST run on localhost:3000 to match CORS allowlist
```

**API base URL:** `http://localhost:8000` (FastAPI default, configurable via `NEXT_PUBLIC_API_URL` env var).

**Endpoint summary for fetch wrapper:**

| Method | Path | Request Body | Success Response | Error Codes |
|--------|------|-------------|------------------|-------------|
| POST | `/api/snap/preview` | `PanelsInput` | `SnapPreviewResponse` (200) | 422, 500 |
| POST | `/api/labels/{sampleId}` | `LabelData` | `{ status, sample_id, panel_count }` (200) | 500 |
| GET | `/api/labels/{sampleId}` | -- | `LabelData` (200) | 404 |
| POST | `/api/errors` | `BrowserError` | 200 (fire-and-forget) | -- |

---

### `frontend/src/lib/errors.ts` (utility, event-driven)

**Analog:** `roof_pipeline/api/middleware.py` (lines 41-69) -- the structured logging middleware shows how the backend logs errors, and the error payload shape the frontend should send.

**Backend trace ID and error logging pattern** (`roof_pipeline/api/middleware.py` lines 41-69):
```python
async def structured_logging_middleware(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    # ... logs JSON with trace_id, sample_id, endpoint, method, status_code, latency_ms
    response.headers["X-Trace-ID"] = trace_id
    return response
```

**Frontend errors endpoint:** Does not yet exist in the FastAPI sidecar. Phase 5 must add `POST /api/errors` that accepts a `BrowserError` payload and logs it as a structured JSON line. The endpoint follows the same pattern as the structured logging middleware -- it logs the incoming JSON payload using the existing `JSONFormatter`.

**Error payload shape to send** (from UI-SPEC Error Capture Contract):
```typescript
interface BrowserError {
  timestamp: string;       // ISO 8601
  page: string;            // window.location.pathname
  error_type: string;      // "unhandled_exception" | "unhandled_rejection" | "api_error" | "render_error"
  message: string;
  stack: string | null;
  user_agent: string;
  sample_id: string | null;
}
```

---

### `frontend/src/lib/supabase.ts` (config)

**Analog:** `roof_pipeline/api/deps.py` (lines 1-33) + `roof_pipeline/api/config.py` (lines 1-31)

**Backend Supabase client pattern** (`roof_pipeline/api/deps.py` lines 26-33):
```python
def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
```

**Backend config pattern** (`roof_pipeline/api/config.py` lines 12-31):
```python
class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    cors_origins: list[str] = ["http://localhost:3000"]
    storage_bucket: str = "pipeline-outputs"
```

**Frontend Supabase client:** Uses `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` env vars (anon key, NOT service role key -- frontend is a public client). For Phase 5 MVP, Supabase client may only be needed for Storage URL generation (hillshade image), or may not be needed if the API proxies everything.

---

### `frontend/src/stores/labeler-store.ts` (store, event-driven)

**Analog:** No existing codebase analog. Pattern comes from RESEARCH.md.

**Data shape mirrors Python PanelCorners** (`roof_pipeline/panel_snap_v2/schema.py` lines 16-22):
```python
class PanelCorners(BaseModel):
    id: int
    corners_pix: list[list[float]]
```

The Zustand store's `PanelData` interface must match this shape exactly so serialization to `PanelsInput` for API calls is a direct mapping with no transformation needed.

**Key constraint from backend:** The `strip_close_polygon_duplicate` validator (schema.py lines 24-45) runs server-side. The frontend store MUST NOT include duplicate-close corners in `corners_pix`. The `closePolygon()` action should NOT append the first vertex as the last vertex.

---

### `frontend/src/app/labeling/[sampleId]/page.tsx` (route, request-response)

**Analog:** `roof_pipeline/api/labels.py` (lines 67-91) -- the GET endpoint that this page calls on mount.

**Data loading contract** (`roof_pipeline/api/labels.py` lines 67-91):
```python
@router.get("/{sample_id}")
async def get_labels(sample_id: str, ...):
    result = supabase.table("labels").select("*").eq("sample_id", sample_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"No labels found for sample {sample_id}")
    row = result.data[0]
    return LabelData(sample_id=row["sample_id"], panels=row["panels"])
```

**Page must handle:**
- 200: Load panels into store via `loadPanels()`
- 404: Empty state (no panels labeled yet) -- not an error, just start fresh
- 500/network error: Error toast per UI-SPEC copywriting contract

---

### `frontend/src/components/canvas/SnapPreviewLayer.tsx` (component, request-response)

**Analog:** `roof_pipeline/api/snap.py` (lines 58-95) -- the snap preview endpoint whose response this component renders.

**Feature graph structure from backend** (`roof_pipeline/api/schemas.py` lines 16-37):
```python
class FeatureNode(BaseModel):
    id: int
    valence: int
    position_xyz: list[float] | None  # [x, y, z] in meters or null
    panel_ids: list[int]
```

**Rendering rules from UI-SPEC (valence dot colors):**

| Valence | Color | Hex | Radius |
|---------|-------|-----|--------|
| 2 | Green | `#22c55e` | 5px |
| 3 | Yellow | `#eab308` | 7px |
| 4+ | Red | `#ef4444` | 9px |

**Coordinate mapping:** The `position_xyz` field from the backend is in meters (or pixel * res_m). The canvas displays pixel coordinates. If `res_m` was provided in the request, divide position by `res_m` to get pixel coords. If `res_m` was null/1.0, the position IS the pixel coord.

---

### `frontend/e2e/labeler.spec.ts` (test, request-response)

**Analog:** `roof_pipeline/api/tests/test_snap.py` (lines 1-99) + `roof_pipeline/api/tests/test_labels.py` (lines 1-137)

**Backend test fixture pattern** (`roof_pipeline/api/tests/conftest.py` lines 42-60):
```python
@pytest.fixture
def two_panel_input():
    """Two adjacent rectangular panels sharing an edge at x=100."""
    return {
        "panels": [
            {"id": 1, "corners_pix": [[0, 0], [100, 0], [100, 100], [0, 100]]},
            {"id": 2, "corners_pix": [[100, 0], [200, 0], [200, 100], [100, 100]]},
        ],
    }

@pytest.fixture
def single_panel_input():
    """Single triangular panel."""
    return {
        "panels": [
            {"id": 1, "corners_pix": [[0, 0], [100, 0], [50, 80]]},
        ],
    }
```

**Backend test naming pattern** (`test_snap.py`):
```python
class TestSnapPreview:
    def test_two_panels_returns_200(self, client, two_panel_input):
    def test_response_has_features_and_edges(self, client, two_panel_input):
    def test_empty_panels_returns_422(self, client):
    def test_malformed_input_returns_422(self, client):
```

**Playwright test structure mirrors the test class approach:**
- Group tests in `test.describe()` blocks (equivalent to Python test classes)
- Use API mocking via `page.route()` (equivalent to Python dependency overrides)
- Use fixture data matching the `two_panel_input` / `single_panel_input` patterns from conftest
- Canvas interaction via `page.locator('[data-testid="labeler-canvas"] canvas').click({ position: { x, y } })`

---

### `frontend/next.config.ts` (config)

**Analog:** None in codebase. Pattern from RESEARCH.md (Pattern 5).

**Required webpack external for Konva:**
```typescript
// Prevents "Can't resolve 'canvas'" error in server-side builds
webpack: (config) => {
    config.externals = [...(config.externals || []), { canvas: "canvas" }];
    return config;
},
```

---

### `frontend/src/app/layout.tsx` (provider)

**Analog:** None in codebase. Standard Next.js App Router pattern.

**Must include:**
- `next/font/google` Inter font at weights 400, 600
- Tailwind CSS globals import
- `<Toaster />` from sonner for toast notifications
- Error capture initialization via `initErrorCapture()` from `lib/errors.ts`

---

### `frontend/src/hooks/use-keyboard-shortcuts.ts` (hook, event-driven)

**Analog:** None in codebase. Pattern from RESEARCH.md.

**Shortcut table from UI-SPEC:**

| Shortcut | Action | Store Method |
|----------|--------|-------------|
| Cmd+Z | Undo | `useLabelerStore.temporal.getState().undo()` |
| Cmd+Shift+Z | Redo | `useLabelerStore.temporal.getState().redo()` |
| Escape | Cancel drawing / deselect | `cancelDrawing()` or `selectPanel(null)` |
| Delete/Backspace | Delete selected panel | `deletePanel(selectedPanelIndex)` |
| D | Draw mode | `setMode("draw")` |
| S | Select mode | `setMode("select")` |

---

## Shared Patterns

### API Error Response Shape
**Source:** `roof_pipeline/api/schemas.py` lines 94-99 + `roof_pipeline/api/main.py` lines 80-122
**Apply to:** `frontend/src/lib/api.ts` (fetch wrapper error handling)

```python
# Backend error response shape (all endpoints):
class ErrorResponse(BaseModel):
    error_type: str
    message: str
    trace_id: str | None = None

# Errors always include X-Trace-ID header:
response.headers["X-Trace-ID"] = trace_id
```

The `apiFetch()` wrapper must:
1. Extract `X-Trace-ID` from response headers
2. Parse error body for `message` or `detail` field (FastAPI uses `detail` for HTTPException, `message` for ErrorResponse)
3. Throw `ApiError` with status, message, and traceId

### Pydantic-to-Zod Schema Mirroring
**Source:** `roof_pipeline/panel_snap_v2/schema.py` lines 1-64 + `roof_pipeline/api/schemas.py` lines 1-100
**Apply to:** `frontend/src/lib/schemas.ts`

Every Zod schema file must include a comment referencing the source Pydantic model:
```typescript
// Mirrors: roof_pipeline/panel_snap_v2/schema.py::PanelCorners
// Mirrors: roof_pipeline/api/schemas.py::SnapPreviewResponse
```

Field validators with side effects (`strip_close_polygon_duplicate`) are backend-only. The Zod schema does NOT replicate them. Only structural constraints (`.min(3)`, `.length(2)`, `.int()`) are mirrored.

### Request Body Conventions
**Source:** `roof_pipeline/api/snap.py` line 59, `roof_pipeline/api/labels.py` line 33
**Apply to:** All API calls in `frontend/src/lib/api.ts`

```python
# Backend accepts JSON body with Content-Type: application/json
# PanelsInput body (snap preview):
async def snap_preview(body: PanelsInput, request: Request):

# LabelData body (save labels):
async def save_labels(sample_id: str, body: LabelData, ...):
```

All POST requests must set `Content-Type: application/json` and `JSON.stringify()` the body.

### Router Prefix Mapping
**Source:** `roof_pipeline/api/main.py` lines 72-74
**Apply to:** `frontend/src/lib/api.ts` endpoint paths

```python
app.include_router(snap_router, prefix="/api/snap", tags=["snap"])
app.include_router(pipeline_router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(labels_router, prefix="/api/labels", tags=["labels"])
```

Frontend endpoint paths:
- Snap preview: `POST ${API_BASE}/api/snap/preview`
- Save labels: `POST ${API_BASE}/api/labels/${sampleId}`
- Get labels: `GET ${API_BASE}/api/labels/${sampleId}`
- Errors: `POST ${API_BASE}/api/errors` (new, to be added to sidecar)

### Test Data Fixtures
**Source:** `roof_pipeline/api/tests/conftest.py` lines 42-60
**Apply to:** `frontend/e2e/labeler.spec.ts` mock data

The same panel coordinate fixtures used in backend tests should be reused in E2E test mocks for consistency:
```python
# Two adjacent panels sharing edge at x=100:
{"id": 1, "corners_pix": [[0, 0], [100, 0], [100, 100], [0, 100]]}
{"id": 2, "corners_pix": [[100, 0], [200, 0], [200, 100], [100, 100]]}

# Single triangle:
{"id": 1, "corners_pix": [[0, 0], [100, 0], [50, 80]]}
```

---

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/src/components/canvas/HillshadeCanvas.tsx` | component | event-driven | No frontend exists; Konva Stage wrapper pattern from RESEARCH.md Pattern 1 |
| `frontend/src/components/canvas/PolygonLayer.tsx` | component | event-driven | Konva `<Line closed>` rendering; no backend equivalent |
| `frontend/src/components/canvas/DrawingLayer.tsx` | component | event-driven | In-progress polyline; pure canvas interaction |
| `frontend/src/components/canvas/MagnetIndicator.tsx` | component | event-driven | Konva Circle indicator; pure canvas interaction |
| `frontend/src/components/canvas/AutoCloseIndicator.tsx` | component | event-driven | Konva Circle indicator; pure canvas interaction |
| `frontend/src/components/labeling/LabelingHeader.tsx` | component | -- | UI chrome from UI-SPEC layout contract |
| `frontend/src/components/labeling/LabelingToolbar.tsx` | component | event-driven | UI chrome from UI-SPEC layout contract |
| `frontend/src/stores/labeler-store.ts` | store | event-driven | Zustand + zundo pattern from RESEARCH.md Pattern 2 |
| `frontend/src/hooks/use-keyboard-shortcuts.ts` | hook | event-driven | useEffect keydown listener; no backend equivalent |
| `frontend/src/hooks/use-canvas-size.ts` | hook | event-driven | ResizeObserver or window resize; no backend equivalent |
| `frontend/src/app/layout.tsx` | provider | -- | Standard Next.js root layout |
| `frontend/src/app/page.tsx` | route | -- | Minimal redirect; trivial |
| `frontend/next.config.ts` | config | -- | Webpack canvas external from RESEARCH.md Pattern 5 |
| `frontend/playwright.config.ts` | config | -- | Standard Playwright config |

**Note:** The majority of Phase 5 files have no codebase analog because this is an entirely new Next.js frontend. The patterns for these files come from:
1. **RESEARCH.md** -- Patterns 1-5 (dynamic import, zustand+zundo, magnet snap, Zod schemas, next.config)
2. **UI-SPEC.md** -- Layout contract, color tokens, spacing, interaction contract, state contract
3. **Backend schema files** -- PanelCorners/PanelsInput/SnapPreviewResponse define the data contract

---

## Backend File to Add

Phase 5 requires adding one new endpoint to the existing FastAPI sidecar:

| File | Change Type | Purpose |
|------|-------------|---------|
| `roof_pipeline/api/errors.py` | NEW | `POST /api/errors` endpoint for browser error capture (OBSERVABILITY-01b) |
| `roof_pipeline/api/main.py` | MODIFY (line 74) | Add `app.include_router(errors_router, prefix="/api/errors", tags=["errors"])` |

**Pattern for errors.py:** Follow the same structure as `roof_pipeline/api/labels.py` (lines 1-91):
```python
# Same imports pattern:
from fastapi import APIRouter, Request
# Same router creation:
router = APIRouter()
# Same logging setup:
log = logging.getLogger(__name__)
# Endpoint: fire-and-forget log, return 200
```

---

## Metadata

**Analog search scope:** `roof_pipeline/api/`, `roof_pipeline/panel_snap_v2/`
**Files scanned:** 15 Python backend files
**Pattern extraction date:** 2026-04-19
**Key finding:** Since the entire frontend is greenfield (no `frontend/` directory exists), 14 of 20 files have no codebase analog. The 6 files with analogs are all API-boundary files where Pydantic schemas map to Zod schemas and endpoint contracts map to fetch calls. RESEARCH.md and UI-SPEC.md are the primary pattern sources for all canvas, state, and UI component files.
