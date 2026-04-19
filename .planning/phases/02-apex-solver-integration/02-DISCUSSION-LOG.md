# Phase 2: Apex Solver + Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 02-apex-solver-integration
**Areas discussed:** Solver fallback behavior, Validation + repair strictness, Input schema design, Byte-identity test strategy

---

## Solver fallback behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Centroid + warning | XY centroid + per-plane Z reconstruction. Log warning with panel IDs and condition number. Pipeline continues. | ✓ |
| Hard fail with panel IDs | Raise RuntimeError with offending panel IDs. User must fix input. | |
| Skip cluster + warning | Leave vertices unmodified. May produce small gaps but no incorrect geometry. | |

**User's choice:** Centroid + warning (Recommended)
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| XY centroid + Z from each plane | Each panel gets its own Z at shared XY centroid, reconstructed from that panel's plane. Matches v1 pairwise snap. | ✓ |
| Single solved Z from lower-residual plane | Pick plane with lower RMS residual, use its Z for both panels. | |
| You decide | Claude picks for backward compatibility. | |

**User's choice:** XY centroid + Z from each plane (Recommended)
**Notes:** Preserves backward compatibility with v1 snap behavior.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Summary at INFO level | One-line summary with apex counts and fallback count. Consistent with pipeline logging. | ✓ |
| Silent unless warning | Only log on fallback or validation failure. | |
| You decide | Claude picks based on existing patterns. | |

**User's choice:** Summary at INFO level (Recommended)
**Notes:** None

---

## Validation + repair strictness

| Option | Description | Selected |
|--------|-------------|----------|
| After densify only | Single pass at the end. Avoids double-checking. | |
| After solver AND after densify | Two validation passes. Catches problems early before densify potentially masks them. | ✓ |
| You decide | Claude picks based on where invalid geometry most likely appears. | |

**User's choice:** After solver AND after densify
**Notes:** User chose the more defensive option over the recommended single-pass.

---

| Option | Description | Selected |
|--------|-------------|----------|
| 1% area change | Raise if repaired area differs by >1%. Aligns with STATE.md pitfall #4. | ✓ |
| 5% area change | More lenient. Allows larger sliver removal. | |
| Zero tolerance | Any change fails. Most strict. | |

**User's choice:** 1% area change (Recommended)
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Keep largest piece + warning | Take largest polygon from MultiPolygon, discard rest. Log warning. | ✓ |
| Hard fail with panel ID | Raise RuntimeError. Input was seriously malformed. | |
| You decide | Claude picks based on likelihood. | |

**User's choice:** Keep largest piece + warning (Recommended)
**Notes:** None

---

## Input schema design

| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic | Rich validation, clear error messages. FastAPI in Milestone 2 needs it. New dependency. | ✓ |
| Dataclass + manual checks | No new dependency. More code. | |
| You decide | Claude picks based on TOPO-11 and Milestone 2 alignment. | |

**User's choice:** Pydantic (Recommended)
**Notes:** User explicitly accepted TOPO-11 exception for input validation. Pydantic added to requirements.txt.

---

| Option | Description | Selected |
|--------|-------------|----------|
| panel_snap_v2/schema.py | Inside snap engine subpackage. boundaries.py imports from it. Single source of truth. | ✓ |
| boundaries.py (inline) | Next to polygons_from_clicks. Simpler but couples to legacy module. | |
| roof_pipeline/schema.py (top-level) | Shared module at package root. Most neutral. | |

**User's choice:** panel_snap_v2/schema.py (Recommended)
**Notes:** None

---

## Byte-identity test strategy

| Option | Description | Selected |
|--------|-------------|----------|
| OBJ vertex comparison | Compare OBJ vertices/faces as parsed arrays. Deterministic, no timestamps. | |
| All output files byte-identical | Literally diff everything. Strip PDF timestamps. Most strict but brittle. | |
| Polygon array comparison only | Compare snapped polygon arrays before mesh/PDF. Fastest, most focused. | |

**User's choice:** Other — Four-tier comparison strategy
**Notes:** User provided a detailed tiered approach:
- Tier 0 (pre-flight): polygon dict at atol=1e-12
- Tier 1 (strict byte): snap_v2_features.json, sorted keys
- Tier 2 (structural): OBJ/glTF via trimesh, atol=1e-9, exact faces
- Tier 3 (semantic PDF): DEFERRED to Milestone 2
- Goldens in `roof_pipeline/panel_snap_v2/tests/golden/gable/`, committed to git
- `--regenerate-golden` pytest flag with manual git diff review

---

| Option | Description | Selected |
|--------|-------------|----------|
| Add pdfplumber as test dep | Test-only dependency for Tier 3 PDF comparison. | |
| Skip Tier 3 for now | Defer PDF comparison to Milestone 2. Tiers 0-2 cover geometry. | ✓ |
| You decide | Claude picks based on value vs cost. | |

**User's choice:** Skip Tier 3 for now
**Notes:** Tiers 0-2 provide sufficient geometry coverage.

---

## Claude's Discretion

- Internal solver decomposition within solver.py
- Edge-walking densify algorithm details in densify.py
- Pydantic model field naming and nesting in schema.py
- Exact --regenerate-golden pytest fixture implementation
- How --snap-v2 flag interacts with existing --snap-tol argument

## Deferred Ideas

None
