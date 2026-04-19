---
phase: 5
slug: labeling-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-19
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | @playwright/test 1.59.1 |
| **Config file** | `frontend/playwright.config.ts` (Wave 0 creation) |
| **Quick run command** | `npx playwright test --project=chromium e2e/labeler.spec.ts` |
| **Full suite command** | `npx playwright test` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `npx playwright test --project=chromium e2e/labeler.spec.ts`
- **After every plan wave:** Run `npx playwright test`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | DASH-01 | — | N/A | E2E | `npx playwright test e2e/labeler.spec.ts -g "load"` | No -- W0 | ⬜ pending |
| 05-02-01 | 02 | 2 | DASH-02 | — | N/A | E2E | `npx playwright test e2e/labeler.spec.ts -g "magnet"` | No -- W0 | ⬜ pending |
| 05-02-02 | 02 | 2 | DASH-06 | — | N/A | E2E | `npx playwright test e2e/labeler.spec.ts -g "auto-close"` | No -- W0 | ⬜ pending |
| 05-03-01 | 03 | 2 | DASH-03 | — | N/A | E2E | `npx playwright test e2e/labeler.spec.ts -g "undo"` | No -- W0 | ⬜ pending |
| 05-04-01 | 04 | 3 | DASH-04 | — | N/A | E2E | `npx playwright test e2e/labeler.spec.ts -g "snap preview"` | No -- W0 | ⬜ pending |
| 05-04-02 | 04 | 3 | DASH-05 | — | N/A | E2E | `npx playwright test e2e/labeler.spec.ts -g "save"` | No -- W0 | ⬜ pending |
| 05-05-01 | 05 | 3 | OBSERVABILITY-01b | — | N/A | E2E | `npx playwright test e2e/labeler.spec.ts -g "error"` | No -- W0 | ⬜ pending |
| 05-06-01 | 06 | 3 | TESTING-01a | — | N/A | E2E | `npx playwright test` | No -- W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `frontend/` — entire Next.js project scaffold
- [ ] `frontend/playwright.config.ts` — Playwright configuration
- [ ] `frontend/e2e/labeler.spec.ts` — E2E test stubs for labeler flows
- [ ] `npx playwright install chromium` — browser binary
- [ ] `frontend/src/lib/schemas.ts` — Zod schemas shared between app and tests

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Hillshade renders at correct contrast | DASH-01 | Visual quality assessment | Load sample, verify hillshade is visible against dark chrome |
| Magnet visual indicator is noticeable | DASH-02 | Visual UX assessment | Draw vertex near existing vertex, verify blue ring appears |
| Valence dot colors distinguishable | DASH-04 | Color accessibility check | Run snap preview, verify green/yellow/red + size differences |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
