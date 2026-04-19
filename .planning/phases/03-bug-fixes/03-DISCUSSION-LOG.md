# Phase 3: Bug Fixes - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 03-bug-fixes
**Areas discussed:** Dedup placement, Densify fix strategy, Test data sourcing

---

## Dedup Placement

| Option | Description | Selected |
|--------|-------------|----------|
| schema.py validator | Add Pydantic field_validator on PanelCorners.corners_pix. Catches at input boundary — protects CLI and HTTP API. Single source of truth per D-08. | ✓ |
| boundaries.py ingestion | Dedup in polygons_from_clicks() after validation. Keeps schema strict. Only protects CLI path. | |
| winding.py normalization | Dedup at start of normalize_winding(). Deepest in pipeline — only protects v2 snap path. | |

**User's choice:** schema.py validator (Recommended)
**Notes:** None

### Follow-up: Dedup Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Close-polygon only | Strip last corner if matches first within tolerance. Specific to matplotlib double-click bug. Minimal change. | ✓ |
| All consecutive duplicates | Strip any consecutive duplicate vertices anywhere. More defensive but wider blast radius. | |

**User's choice:** Close-polygon only (Recommended)
**Notes:** None

---

## Densify Fix Strategy

### Investigation Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Investigate first | Add diagnostic logging, run on fb7e705c, understand root cause before coding fix. | ✓ |
| Hypothesis: multi-neighbor edge walk | Edge walk breaks with 3+ neighbors — fix algorithm directly. | |
| Hypothesis: tolerance tuning | t-parameter and tol thresholds too aggressive — fix values. | |

**User's choice:** Investigate first (Recommended)
**Notes:** None

### Fix Scope If Redesign Needed

| Option | Description | Selected |
|--------|-------------|----------|
| Fix the algorithm | Redesign edge walk for multi-neighbor panels. Same API, same tests, better internals. No threshold changes. | ✓ |
| Fix + relax thresholds | Fix algorithm AND adjust D-06/D-05 thresholds. | |
| Minimal patch | Minimum to get fb7e705c passing — special-case if needed. Quick but fragile. | |

**User's choice:** Fix the algorithm (Recommended)
**Notes:** User provided four additional densify decisions via freeform text:
1. Narrow fix only — fix panel 8 failure mode, no broader refactoring (scope creep)
2. Keep D-06 strict — no fallback, hard-fail, user re-labels mask.json
3. No CLI flag for densify tolerance — validate-layer only
4. Diagnostic DEBUG logging: per-shared-edge (panel_a, panel_b, candidate_vertices_considered, vertices_inserted, insertion_positions_xy)

---

## Test Data Sourcing

### Data Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Real data available | Commit DSM .tif and mask to test golden directory. | |
| Build synthetic multi-hip | Programmatic geometry via make_synthetic_multi_hip(). No real data. | |
| Both — real + synthetic | Real data for primary regression, synthetic for broader coverage. | ✓ |

**User's choice:** Both — real + synthetic
**Notes:** User corrected the framing: densify operates downstream of DSM/mask — no DSM or mask needed in tests.

### Data Format (user-corrected)

User rejected all three presented options. Actual decision:
- Real data test: Inline Python constants (12 panels' clicked corners + 12 plane normals). Extracted one-time from ~/Downloads/fb7e705c.mask.json. No binary blobs, no external paths.
- Synthetic test: make_synthetic_multi_hip() in synthetic.py. Programmatic geometry.
- Source DSM/mask stays at ~/Downloads/ — only for regenerating plane fits.

---

## Claude's Discretion

- Exact tolerance value for close-polygon dedup matching in schema.py
- Diagnostic log line format details beyond required fields
- Internal decomposition of densify fix
- make_synthetic_multi_hip() exact geometry

## Deferred Ideas

None — discussion stayed within phase scope
