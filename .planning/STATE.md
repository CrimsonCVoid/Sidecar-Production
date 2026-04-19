---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: FastAPI Sidecar + Labeling Dashboard
status: defining_requirements
stopped_at: Milestone v2.0 started — defining requirements
last_updated: "2026-04-18T00:00:00.000Z"
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State: FastAPI Sidecar + Labeling Dashboard (Milestone 2)

## Project Reference

**Core Value:** Hip and ridge apex convergences (3+ panels) must weld to a single geometrically-correct point with zero slivers in the output mesh.
**Milestone:** 2 of 2 — Fix real-data bugs, expose snap engine via FastAPI, build Next.js labeling dashboard.

---

## Current Position

**Phase:** Not started (defining requirements)
**Plan:** —
**Status:** Defining requirements

```
[                                                                          ]
0%
```

---

## Performance Metrics

- Phases complete: 0/0
- Tests passing: 41/41 (inherited from Milestone 1)
- Requirements delivered: 0/0 (defining)

---

## Accumulated Context

### Key Decisions

- `--snap-v2` flag keeps old path (`snapping.py`) as fallback until all validation passes
- `scipy.cluster.hierarchy.DisjointSet` for union-find (already in scipy >=1.11, no new dep)
- `shapely.make_valid` preferred over `buffer(0)` — buffer(0) discards geometry in bowtie topologies
- Condition-number thresholds: 1e8 WARNING fallback, 1e12 hard-fail
- solve_apices returns tuple (polygons, solved_positions) for downstream graph position update
- snap_polygons returns tuple (polygons, graph) — run_real.py needs graph for JSON sidecar
- ConfigDict(strict=True, extra='forbid') on Pydantic models — prevents silent coercion for HTTP surface
- Pydantic exception to TOPO-11 accepted per D-07 — VALID-01 explicitly offers it and FastAPI needs it
- Fix densify before FastAPI — 65.9% area loss on complex roofs blocks production use

### Active Todos

- Investigate and fix densify bug on fb7e705c panel 8 (12-panel hip-and-valley roof)
- Fix labeler duplicate-corner bug (silent dedup in winding.py + Konva auto-close)

### Known Blockers

- Densify make_valid MultiPolygon at 65.9% blocks production use on complex roofs

### Pitfalls to Watch

1. Non-simple polygon reaching winding check — `shapely.is_valid` guard before normalization
2. Near-parallel planes in apex solver — condition-number guard + centroid fallback (implemented)
3. Earcut failure on post-snap polygons — assert area conservation within 1%; remove zero-length edges
4. Densify on panels sharing edges with 3+ neighbors — may need edge-walk redesign, not just tolerance tuning
5. Duplicate last corners in legacy mask.json — must dedup silently without breaking valid polygons

---

## Session Continuity

**Last session:** 2026-04-18
**Stopped at:** Milestone v2.0 started — defining requirements
**Resume file:** None — defining requirements
**Next action:** Define requirements, create roadmap

---

*State initialized: 2026-04-18*
*Last updated: 2026-04-18 — Milestone 2 started*
