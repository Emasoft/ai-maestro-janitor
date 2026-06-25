#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Memory scope-migration helper (TRDD-47df698b) — re-scope a LOCAL memory corpus
to PROJECT scope, conservatively and privacy-first.

    migrate_memory_scope.py <local-mem-dir> --project-repo <repo> [--dry-run]

PHASE 1 (this build) — the READ-ONLY classifier. `--dry-run` (the DEFAULT) scans
every real note in `<local-mem-dir>`, classifies each PROJECT / LOCAL-stay (a hard
PRIVACY gate forces any note with machine/user-private data to LOCAL), and writes a
reviewable PLAN to `reports/migrate-memory-scope/<ts>-plan.md`. NO mutation.

PHASE 2 — `--apply` (run by the OWNING project's Claude, NOT from here) — is a
SEPARATE deferred build. The cross-project contract (`how-to-fix-issues-of-other-
projects.md`) forbids the janitor session from mutating another project's store;
the owning Claude reviews the plan, then runs `--apply` in its own session. Until
that build lands, `--apply` FAILS FAST with a clear message — it never silently
no-ops.

Fail-fast: a missing dir / a bad invocation exits non-zero with a clear message.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_migrate as mm  # noqa: E402


def _report_path(project_repo: Path) -> Path:
    """Where the plan is written: the MAIN repo's `reports/migrate-memory-scope/`
    (gitignored), timestamped local-time + GMT offset (the agent-reports rule)."""
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S%z")
    out_dir = project_repo / "reports" / "migrate-memory-scope"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{ts}-plan.md"


def main() -> int:
    ap = argparse.ArgumentParser(prog="migrate_memory_scope")
    ap.add_argument("local_mem_dir", help="the LOCAL memory corpus to classify")
    ap.add_argument(
        "--project-repo",
        required=True,
        help="the owning project's repo root (PROJECT-scope target)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="(DEFAULT) read-only: classify + write the plan, mutate nothing",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="PHASE 2 (deferred) — run by the owning Claude; not built yet",
    )
    args = ap.parse_args()

    memdir = Path(args.local_mem_dir).expanduser()
    project_repo = Path(args.project_repo).expanduser()

    if not memdir.is_dir():
        print(f"error: local mem dir not found: {memdir}", file=sys.stderr)
        return 2

    if args.apply:
        # Fail-fast, never silently: the apply path is the owning Claude's job and
        # is a separate deferred build (cross-project contract). Do NOT pretend to
        # do nothing — refuse loudly so the caller knows to run the dry-run first.
        print(
            "error: --apply is not implemented in this build. Phase 1 (the read-only classifier) ships here; the owning project's Claude runs --apply in its own session after reviewing the dry-run plan (cross-project contract).",
            file=sys.stderr,
        )
        return 2

    # Default = dry-run (read-only).
    verdicts = mm.classify_corpus(memdir)
    plan = mm.render_plan(memdir, verdicts, project_repo=str(project_repo))
    out = _report_path(project_repo)
    out.write_text(plan, encoding="utf-8")

    n_project = sum(1 for v in verdicts if v.verdict == mm.PROJECT)
    n_local = sum(1 for v in verdicts if v.verdict == mm.LOCAL)
    n_leak = sum(1 for v in verdicts if v.leak_classes)
    print(f"classified {len(verdicts)} notes ({n_project} → PROJECT, {n_local} → LOCAL-stay, {n_leak} privacy-flagged). Plan: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
