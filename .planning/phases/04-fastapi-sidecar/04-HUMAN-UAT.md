---
status: partial
phase: 04-fastapi-sidecar
source: [04-VERIFICATION.md]
started: 2026-04-19T17:27:00Z
updated: 2026-04-19T17:27:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Snap preview performance (<500ms on 12-panel roof)
expected: POST /api/snap/preview with fb7e705c 12-panel roof data returns within 500ms
result: [pending]

### 2. End-to-end pipeline run with live Supabase
expected: POST /api/pipeline/run triggers full pipeline, background task updates pipeline_runs table at each stage boundary, output files uploaded to Supabase Storage
result: [pending]

### 3. Labels round-trip via live Supabase
expected: POST /api/labels/{sampleId} persists label data, GET retrieves it with all vertex coordinates preserved without floating-point loss
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
