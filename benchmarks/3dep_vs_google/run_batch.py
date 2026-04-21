"""Phase 5 — Batch runner across a CSV of test addresses.

Semi-interactive: for each row it runs fetch_3dep → upload → fetch_google_twin,
then pauses for you to label both samples in the UI. Type 'y' to run
compare and move to the next address, 's' to skip, 'q' to stop. A rollup
Markdown at the end tallies verdicts and notes which roof topologies
favour which source.

Don't reach for this until Phases 1-4 are proven on a single house. The
batch wrapper multiplies debugging pain if the core scripts aren't solid.

CSV format:
    address,notes
    "123 Main St, Apex NC",simple hip roof
    "456 Oak Dr, Raleigh NC",complex multi-gable
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import subprocess
import sys
from pathlib import Path

from common import load_project_env

log = logging.getLogger("bench.batch")


def _run(cmd: list[str]) -> tuple[int, str]:
    log.info("$ %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    print(out)
    return proc.returncode, out


def _extract_sample_id(stdout: str) -> str | None:
    # Both fetch_3dep and fetch_google_twin print "Sample ID: <uuid>" and
    # the upload script prints a labeling URL ending in the id. Scan for
    # any UUIDv5-looking token.
    import re
    m = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        stdout,
    )
    return m.group(0) if m else None


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip().lower()
    except EOFError:
        return "q"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch benchmark runner")
    parser.add_argument("--addresses-csv", type=Path, required=True)
    parser.add_argument("--output-report", type=Path,
                        default=Path(__file__).parent / "results"
                        / f"batch_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}.md")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_project_env()

    rows: list[dict] = []
    with open(args.addresses_csv) as f:
        for r in csv.DictReader(f):
            if r.get("address"):
                rows.append(r)

    here = Path(__file__).parent
    python = sys.executable
    results: list[dict] = []

    for idx, row in enumerate(rows, start=1):
        address = row["address"]
        notes = row.get("notes", "")
        print(f"\n=== [{idx}/{len(rows)}] {address} ===")

        # Phase 1: 3DEP fetch
        code, out = _run([python, str(here / "fetch_3dep.py"), "--address", address])
        if code != 0:
            results.append({"address": address, "notes": notes,
                            "verdict": "skipped", "reason": "3dep fetch failed"})
            continue

        # Phase 2: upload (find the newest output subdir)
        out_subdirs = sorted((here / "output").glob("*"), key=lambda p: p.stat().st_mtime)
        out_subdirs = [p for p in out_subdirs if p.is_dir() and not p.name.startswith("_")]
        if not out_subdirs:
            results.append({"address": address, "notes": notes,
                            "verdict": "skipped", "reason": "no output dir"})
            continue
        code, out_up = _run([python, str(here / "upload_sample.py"),
                             "--input-dir", str(out_subdirs[-1])])
        if code != 0:
            results.append({"address": address, "notes": notes,
                            "verdict": "skipped", "reason": "upload failed"})
            continue
        dep_sample_id = _extract_sample_id(out_up)

        # Phase 3: Google twin
        code, out_g = _run([python, str(here / "fetch_google_twin.py"),
                            "--address", address])
        if code != 0:
            results.append({"address": address, "notes": notes,
                            "verdict": "skipped", "reason": "google twin failed"})
            continue
        google_sample_id = _extract_sample_id(out_g)

        if not google_sample_id or not dep_sample_id:
            results.append({"address": address, "notes": notes,
                            "verdict": "skipped", "reason": "couldn't parse sample ids"})
            continue

        # Pause for labeling
        print(f"\nLabel BOTH samples with identical panel topology:")
        print(f"  Google: http://localhost:3000/labeling/{google_sample_id}")
        print(f"  3DEP:   http://localhost:3000/labeling/{dep_sample_id}")
        ans = _prompt("\nLabeling complete? [y/s/q]: ")
        if ans == "q":
            break
        if ans != "y":
            results.append({"address": address, "notes": notes,
                            "verdict": "skipped", "reason": "user skipped"})
            continue

        # Phase 4: compare
        code, out_cmp = _run([python, str(here / "compare.py"),
                              "--google-sample-id", google_sample_id,
                              "--3dep-sample-id", dep_sample_id])
        verdict = "error"
        for ln in out_cmp.splitlines():
            if "Verdict:" in ln:
                verdict = ln.split("Verdict:")[-1].strip().strip("*").strip()
                break
        results.append({"address": address, "notes": notes,
                        "verdict": verdict,
                        "google_sample_id": google_sample_id,
                        "3dep_sample_id": dep_sample_id})

    # Rollup
    tally = {"3DEP wins": 0, "Google wins": 0, "Mixed": 0, "skipped": 0, "error": 0}
    for r in results:
        tally[r.get("verdict", "error")] = tally.get(r.get("verdict", "error"), 0) + 1

    md: list[str] = [
        f"# 3DEP vs Google batch — {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}",
        "",
        f"Total addresses: {len(rows)}",
        "",
        "## Tally",
        "",
    ]
    for k, v in tally.items():
        md.append(f"- **{k}**: {v}")
    md.append("")
    md.append("## Per-address")
    md.append("")
    md.append("| # | Address | Notes | Verdict |")
    md.append("|---|---|---|---|")
    for i, r in enumerate(results, start=1):
        md.append(f"| {i} | {r['address']} | {r.get('notes', '')} | "
                  f"{r.get('verdict', '?')} |")
    md.append("")

    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text("\n".join(md))
    print(f"\nBatch rollup written to {args.output_report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
