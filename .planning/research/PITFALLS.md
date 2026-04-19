# Domain Pitfalls -- Milestone 2: FastAPI Sidecar + Labeling Dashboard

**Domain:** Adding API layer, Konva polygon editor, Supabase Realtime monitoring to existing Python CLI pipeline
**Researched:** 2026-04-19 (Milestone 2 scope)
**Supersedes:** Prior PITFALLS.md (Milestone 1 snap engine pitfalls, now resolved with 41 tests passing)

---

## Critical Pitfalls

Mistakes that cause rewrites, data corruption, user-facing breakage, or architectural dead ends.

---

### Pitfall 1: FastAPI Event Loop Blocking by CPU-Bound Pipeline Code

**What goes wrong:** The snap engine (`snap_polygons`) and full pipeline are CPU-bound synchronous functions (NumPy, SVD, Shapely). If called from an `async def` route handler, they block the asyncio event loop. A 10-panel roof takes ~200ms for snap preview, 5-15s for full pipeline. During that time, NO other requests are served.

**Why it happens:** FastAPI auto-runs `def` (non-async) handlers in a threadpool, but `async def` handlers execute directly on the event loop. Developers write `async def` for routes (to `await` Supabase calls) and call `snap_polygons()` synchronously inside, blocking the loop.

**Consequences:** Concurrent `/snap-preview` requests queue behind each other. `/run-pipeline` blocks for 5-15s, during which Supabase status writes cannot complete.

**Prevention:**
1. Use `def` (not `async def`) for route handlers calling pipeline code. FastAPI runs them in the default threadpool (40 threads via AnyIO).
2. For routes needing both async Supabase calls and sync pipeline calls, use `starlette.concurrency.run_in_threadpool`:
   ```python
   from starlette.concurrency import run_in_threadpool
   result = await run_in_threadpool(snap_polygons, polygons, planes, tol=req.tol)
   ```
3. For `/run-pipeline`, use `BackgroundTasks` with a synchronous (not `async def`) task function.

**Detection:** Load test with 2+ concurrent `/snap-preview` requests. If second request latency is ~2x the first, event loop is blocked.

**Phase:** FastAPI sidecar setup. Must be correct from day one.

**Confidence:** HIGH -- FastAPI docs explicitly describe this. Python asyncio behavior is inherent.

---

### Pitfall 2: Coordinate System Triple-Mismatch (Pipeline Meters vs Canvas Pixels vs DSM Raster)

**What goes wrong:** Three coordinate spaces must convert correctly at every boundary:

1. **Pipeline world:** meters, `x = col * res_m`, `y = row * res_m`, `z = elevation`. Origin at raster top-left.
2. **DSM raster:** pixel `(row, col)`, integer/fractional. Stored in `corners_pix` as `[col_px, row_px]`.
3. **Konva canvas:** screen pixels, affected by Stage scale (zoom), position (pan), device pixel ratio.

Conversion chain: `canvas screen px -> (inverse Stage transform) -> DSM pixel -> (* res_m) -> world meters`. Any step omitted or misordered produces wrong vertex positions.

Specific failures:
- **Zoom-dependent drift:** Click at 3x zoom records (300, 200) instead of (100, 66.7) if Stage transform not inverted.
- **Y-axis flip:** Canvas Y-down vs geographic Y-up.
- **res_m mismatch:** Dashboard reads from Supabase metadata, pipeline from GeoTIFF header -- different values scale everything wrong.

**Prevention:**
1. Single `coords.ts` module: `screenToPixel(point, stage)`, `pixelToScreen(point, stage)`, `pixelToWorld(point, res_m)`, `worldToPixel(point, res_m)`. No inline conversions.
2. Use `getRelativePointerPosition()` on the Layer, not `getPointerPosition()` on the Stage. Handles zoom/pan automatically.
3. Make `res_m` required (not optional) in mask.json. Pipeline verifies it matches GeoTIFF header.
4. Round-trip test: click -> save -> load -> verify corner renders at same position.

**Phase:** Must be resolved before any vertex placement code is written.

**Confidence:** HIGH -- coordinate spaces documented in CONCERNS.md and ts_export.py. Konva API verified in Context7.

---

### Pitfall 3: DSM Memory Retention in Long-Lived FastAPI Process

**What goes wrong:** Each request loads a 5-15MB DSM GeoTIFF. Without caching, 5 concurrent requests on the same sample = 75MB duplicated. Python GC does not immediately free large NumPy arrays. RSS grows monotonically. Background tasks retain references to all arguments for 5-15s pipeline duration.

**Why it happens:** Pipeline was designed for single CLI invocation (load, process, exit). Long-lived FastAPI process changes memory lifecycle fundamentally.

**Prevention:**
1. LRU cache: `@functools.lru_cache(maxsize=10)` on DSM loading (~150MB max cache).
2. `asyncio.Semaphore(2)` for concurrent full pipeline runs.
3. Explicit `del` + `gc.collect()` in try/finally for background tasks.
4. `/health` endpoint reporting `psutil.Process().memory_info().rss`.

**Phase:** FastAPI sidecar setup. DSM caching strategy must be designed before first route.

**Confidence:** HIGH -- well-documented for long-lived Python processes.

---

### Pitfall 4: Densify MultiPolygon Bug at 65.9% -- Root Cause

**What goes wrong:** On fb7e705c 12-panel hip-and-valley roof, `make_valid` after densification produces MultiPolygon where largest piece is 65.9%. D-06 threshold correctly rejects, but this blocks production use.

**Likely root cause:** Panel 8 shares edges with 3+ neighbors. Densification inserts apex point from two neighbors at slightly different positions, creating near-duplicate vertices and a tiny self-intersection. `make_valid` splits into MultiPolygon.

**Prevention:**
1. Post-solver feature graph refresh -- rebuild shared-edge detection after `solve_apices` moves vertices.
2. Deduplicate consecutive vertices within 1e-6m after densification.
3. Validate each panel individually after densification -- flag any >2% area change.
4. Test with fb7e705c specifically.
5. Consider densifying in XY (plan view) rather than 3D for steep pitch variation.

**Detection:** Run snap_v2 on fb7e705c. Panel 8 must produce a single valid Polygon with area within 2% of original.

**Phase:** Bug fix phase (must precede FastAPI wrapping).

**Confidence:** HIGH that the bug exists (PROJECT.md documents specific numbers). MEDIUM on root cause -- requires debugging with sample data.

---

## Moderate Pitfalls

---

### Pitfall 5: Shared-Node Magnet False Positive Snaps

**What goes wrong:** At hip apices, 3-4 panel corners converge within pixels. Magnet finds nearest vertex, which may be wrong panel's corner. User cannot see difference at 1x zoom, but pipeline receives two separate vertices instead of one shared vertex.

**Prevention:**
1. Snap priority: prefer vertices from adjacent panels, then valence-2+ positions, then nearest.
2. Exclude densification-inserted vertices from snap targets.
3. Suppress self-snap except for polygon closing (vertex 0 with >=3 vertices).
4. Visual indicator debounce: show only after 150ms within radius.
5. Shift-click override (already planned).

**Phase:** Konva labeler implementation. Design snap algorithm before visual indicator.

**Confidence:** MEDIUM -- pattern is sound but priority ordering needs empirical tuning.

---

### Pitfall 6: Undo/Redo State Explosion During Drag

**What goes wrong:** `onDragMove` fires ~60/s. Each fires `set()`, creating a zundo history snapshot. 3-second drag = 180 entries. Ctrl+Z undoes one pixel, not the whole drag.

**Prevention:**
1. zundo `handleSet`: skip recording while `_isDragging` flag is set.
2. Record drag-start and drag-end only.
3. `limit: 100` in zundo config.
4. `partialize` to exclude ephemeral state.

**Detection:** Drag vertex 3 seconds, press Ctrl+Z. Should undo entire drag, not one pixel.

**Phase:** Zustand store design. Must decide before any drag handler.

**Confidence:** HIGH -- zundo `handleSet` API verified in Context7.

---

### Pitfall 7: Supabase Realtime Silent Disconnection

**What goes wrong:** WebSocket disconnects when tab backgrounded (timer throttling prevents heartbeats). Also: iOS/Safari PWA suspension corrupts Supabase client state (GitHub #36046). Run monitor shows "running" forever.

**Prevention:**
1. `worker: true` in Supabase Realtime config (heartbeat in Web Worker, not throttled).
2. `heartbeatCallback` for active monitoring.
3. Poll `pipeline_runs` every 30s as fallback (Realtime = optimization, poll = correctness).
4. Single channel per dashboard, filtered by `sample_id`.

**Phase:** Run monitor implementation.

**Confidence:** HIGH -- Supabase troubleshooting docs recommend these exact mitigations.

---

### Pitfall 8: CORS Misconfiguration

**What goes wrong:** Dashboard on Vercel calls sidecar on DigitalOcean. Without CORS headers, all requests fail. Common errors: wildcard `*` with credentials, NGINX stripping headers, missing OPTIONS handling.

**Prevention:**
1. `CORSMiddleware` with explicit `FRONTEND_URL` env var.
2. Add CORS middleware last in code (runs first in execution).
3. Handle CORS in FastAPI OR NGINX, not both.
4. Test with `curl -v -X OPTIONS` during deployment.

**Phase:** FastAPI sidecar setup.

**Confidence:** HIGH -- W3C CORS spec is deterministic. FastAPI docs cover this.

---

### Pitfall 9: Konva Performance Collapse on Snap Preview

**What goes wrong:** 100-190 shapes all re-rendered on every state change. React reconciliation + Konva hit detection on every mousemove.

**Prevention:**
1. Three-layer architecture: background (cached, `listening={false}`), panels (vertex Circles interactive), overlay (`listening={false}`).
2. `perfectDrawEnabled={false}` during drag.
3. Move dragged shape to dedicated drag layer.
4. `React.memo` / Zustand selectors to prevent unrelated re-renders.

**Phase:** Konva canvas implementation. Layer architecture must be decided upfront.

**Confidence:** HIGH -- Konva performance docs (Context7 verified) recommend these exact patterns.

---

### Pitfall 10: Duplicate-Corner Bug Recurring in Konva

**What goes wrong:** Same bug as matplotlib labeler, via: touch double-tap, React event propagation, auto-close proximity edge case, snap-to-self during close.

**Prevention:**
1. Placement state machine: `IDLE -> DRAWING -> CLOSING -> IDLE`. One vertex per transition.
2. Debounce clicks (200ms).
3. Auto-close does NOT add vertex -- connects last to V0.
4. Legacy dedup in `winding.py` for backward compatibility.

**Phase:** Konva labeler implementation (polygon close logic). Legacy dedup is separate bug fix phase.

**Confidence:** HIGH -- matplotlib bug documented in PROJECT.md. Konva recurrence vectors are standard web edge cases.

---

### Pitfall 11: Pydantic/Zod Schema Drift

**What goes wrong:** mask.json validated by Pydantic (server) and Zod (client). Schemas diverge: field renamed on one side, type widening (strict mode rejects int for float), optional field disagreement.

**Prevention:**
1. Export JSON Schema from Pydantic (`PanelsInput.model_json_schema()`). Generate Zod from it.
2. CI test comparing both schemas against shared fixtures.
3. Consider relaxing `strict=True` for numeric fields.

**Phase:** API boundary definition.

**Confidence:** HIGH -- Pydantic schema exists with `strict=True, extra='forbid'`. These maximize drift detection but also false rejections.

---

## Minor Pitfalls

---

### Pitfall 12: Konva `dragBoundFunc` vs `onDragMove` for Snap

Use `dragBoundFunc` for snap constraints, not `onDragMove`. The latter causes visual jitter because Konva applies its own drag delta after the handler. `dragBoundFunc` returns the allowed position within Konva's drag loop.

**Phase:** Konva labeler. **Confidence:** HIGH (Context7 verified).

---

### Pitfall 13: Zustand Selector Granularity

Using `useStore()` without selector subscribes to ALL changes. Every zoom/hover triggers full canvas re-render. Always use: `useStore(s => s.panels)`. Use `useShallow` for object selectors.

**Phase:** Zustand store design. **Confidence:** HIGH (Zustand docs).

---

### Pitfall 14: next/image vs Konva Image

Next.js `<Image>` produces a DOM `<img>` with lazy loading. Konva needs `HTMLImageElement` reference. Load DSM hillshade with `new window.Image()`, not next/image.

**Phase:** Konva canvas. **Confidence:** HIGH (react-konva docs).

---

### Pitfall 15: Supabase RLS Blocking Pipeline Writes

Sidecar uses service role key for `pipeline_runs` writes. If RLS policies added later without service role exemption, writes fail silently. Add explicit policy and test full chain: write -> Realtime -> dashboard.

**Phase:** Supabase setup. **Confidence:** HIGH.

---

### Pitfall 16: FastAPI Route Registration Leak

If `include_router()` called inside lifespan or middleware, routes re-register on each call, leaking memory. Register all routers once at module level.

**Phase:** FastAPI setup. **Confidence:** HIGH (FastAPI #11079).

---

## Phase-Specific Warnings

| Phase | Pitfall | Severity | Key Mitigation |
|-------|---------|----------|----------------|
| Bug fixes | P4 (densify 65.9%) | Critical | Post-solver graph refresh; vertex dedup |
| Bug fixes | P10 (duplicate corners) | Moderate | Legacy dedup in winding.py |
| FastAPI sidecar | P1 (event loop blocking) | Critical | `def` routes or `run_in_threadpool` |
| FastAPI sidecar | P3 (DSM memory) | Critical | LRU cache; semaphore |
| FastAPI sidecar | P8 (CORS) | Moderate | Explicit origins; test OPTIONS |
| Konva canvas | P2 (coordinate mismatch) | Critical | Single coords.ts; getRelativePointerPosition |
| Konva canvas | P5 (false magnet snaps) | Moderate | Priority ordering; exclude densify vertices |
| Konva canvas | P9 (performance) | Moderate | 3-layer arch; listening={false} |
| Konva canvas | P10 (duplicate corners) | Moderate | State machine; click debounce |
| Konva canvas | P12 (dragBoundFunc) | Minor | Use dragBoundFunc, not onDragMove |
| Zustand store | P6 (undo explosion) | Moderate | handleSet; partialize; limit |
| Zustand store | P13 (selectors) | Minor | Always use selectors |
| Schema boundary | P11 (Pydantic/Zod drift) | Moderate | JSON Schema source; CI test |
| Supabase/Realtime | P7 (silent disconnect) | Moderate | worker:true; poll fallback |
| Supabase/Realtime | P15 (RLS blocking writes) | Minor | Service role key; test chain |

---

## Sources

### FastAPI
- [FastAPI async/await](https://fastapi.tiangolo.com/async/) -- sync vs async handlers
- [FastAPI BackgroundTasks blocking (Discussion #11210)](https://github.com/fastapi/fastapi/discussions/11210)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)
- [BetterUp: Chasing Memory Leak in Async FastAPI](https://build.betterup.com/chasing-a-memory-leak-in-our-async-fastapi-service-how-jemalloc-fixed-our-rss-creep/)

### Konva
- [Konva Performance Tips](https://konvajs.org/docs/performance/All_Performance_Tips.html) -- Context7 verified
- [Konva Layer Management](https://konvajs.org/docs/performance/Layer_Management.html) -- Context7 verified
- [Konva Objects Snapping](https://konvajs.org/docs/sandbox/Objects_Snapping.html) -- Context7 verified
- [Konva Relative Pointer Position](https://konvajs.org/docs/sandbox/Relative_Pointer_Position.html) -- Context7 verified

### Zustand / zundo
- [zundo GitHub](https://github.com/charkour/zundo) -- handleSet, partialize, limit
- [Zustand Discussion #1611](https://github.com/pmndrs/zustand/discussions/1611) -- undo/redo during drag

### Supabase Realtime
- [Supabase: Silent Disconnections](https://supabase.com/docs/guides/troubleshooting/realtime-handling-silent-disconnections-in-backgrounded-applications-592794) -- worker:true, heartbeatCallback
- [Supabase Issue #36046](https://github.com/supabase/supabase/issues/36046) -- PWA/Safari client corruption

### Shapely
- [Shapely make_valid](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html) -- MultiPolygon return behavior

---

*Pitfalls audit: 2026-04-19 (Milestone 2 scope)*
