---
phase: 4
slug: fastapi-sidecar
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-19
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | none -- no pytest.ini/pyproject.toml (tests discovered by convention) |
| **Quick run command** | `python3 -m pytest roof_pipeline/api/tests/ -x -q` |
| **Full suite command** | `python3 -m pytest roof_pipeline/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m pytest roof_pipeline/api/tests/ -x -q`
- **After every plan wave:** Run `python3 -m pytest roof_pipeline/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | API-01 | — | N/A | integration | `python3 -m pytest roof_pipeline/api/tests/test_snap.py -x` | No -- W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | API-01 | — | N/A | performance | Manual benchmark or pytest --timeout | No -- W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | API-02 | — | N/A | integration | `python3 -m pytest roof_pipeline/api/tests/test_pipeline.py -x` | No -- W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | API-02 | — | N/A | integration | `python3 -m pytest roof_pipeline/api/tests/test_pipeline.py::test_status_updates -x` | No -- W0 | ⬜ pending |
| 04-03-01 | 03 | 1 | API-03 | — | N/A | integration | `python3 -m pytest roof_pipeline/api/tests/test_labels.py -x` | No -- W0 | ⬜ pending |
| 04-04-01 | 04 | 1 | OBSERVABILITY-01a | — | N/A | unit | `python3 -m pytest roof_pipeline/api/tests/test_middleware.py -x` | No -- W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `roof_pipeline/api/tests/__init__.py` — package marker
- [ ] `roof_pipeline/api/tests/conftest.py` — FastAPI TestClient fixture, mock Supabase client
- [ ] `roof_pipeline/api/tests/test_snap.py` — covers API-01
- [ ] `roof_pipeline/api/tests/test_pipeline.py` — covers API-02
- [ ] `roof_pipeline/api/tests/test_labels.py` — covers API-03
- [ ] `roof_pipeline/api/tests/test_middleware.py` — covers OBSERVABILITY-01a
- [ ] Framework install: `pip install httpx` (for FastAPI TestClient)

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Response time <500ms for 12-panel roof | API-01 | Requires real pipeline execution with representative data | Run POST /snap-preview with fb7e705c sample, measure wall-clock time |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
