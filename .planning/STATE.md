# Project State: Topology-Aware Snap Engine (Milestone 1)

## Project Reference

**Core Value:** Hip and ridge apex convergences (3+ panels) must weld to a single geometrically-correct point with zero slivers in the output mesh.
**Milestone:** 1 of 2 — Snap engine only. Dashboard/FastAPI is Milestone 2.

---

## Current Position

**Phase:** 1 — Feature Graph + Clustering
**Plan:** None started
**Status:** Not started

```
[Phase 1: Feature Graph + Clustering ] [ Phase 2: Apex Solver + Integration ]
[░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]
0%
```

---

## Performance Metrics

- Phases complete: 0/2
- Tests passing: 0/7
- Requirements delivered: 0/22

---

## Accumulated Context

### Key Decisions
- `--snap-v2` flag keeps old path (`snapping.py`) as fallback until all validation passes
- Phase 1 implements `--snap-v2-dryrun` (print graph, exit 0) — solver is Phase 2
- `scipy.cluster.hierarchy.DisjointSet` for union-find (already in scipy >=1.11, no new dep)
- `shapely.make_valid` preferred over `buffer(0)` — buffer(0) discards geometry in bowtie topologies
- Winding normalization must run before union-find (assumes consistent vertex sequences)
- Feature graph built exactly once, after all 3 tolerance passes complete (prevents valence drift)
- Condition-number guard (`np.linalg.cond(N) > 100`) before lstsq; fallback to centroid with warning

### Active Todos
- None yet — waiting for Phase 1 plan

### Known Blockers
- None

### Pitfalls to Watch
1. Non-simple polygon reaching winding check — `shapely.is_valid` guard before normalization
2. Feature graph built mid union-find pass — build after all 3 passes complete
3. Near-parallel planes in apex solver — condition-number guard + centroid fallback
4. Earcut failure on post-snap polygons — assert area conservation within 1%; remove zero-length edges
5. Union-find transitivity chain drift — check max intra-cluster diameter after clustering

---

## Session Continuity

**Last session:** 2026-04-18 — Phase 1 context gathered
**Stopped at:** Phase 1 context gathered
**Resume file:** `.planning/phases/01-feature-graph-clustering/01-CONTEXT.md`
**Next action:** `/gsd-plan-phase 1`

---

*State initialized: 2026-04-18*
*Last updated: 2026-04-18 after Phase 1 context session*
