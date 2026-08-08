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

PHASE 2 — `--apply --plan <plan.md>` — publishes the plan's PROJECT-bound notes into
`<repo>/.claude/project/memory/`. It is run by the OWNING project's Claude, in its own
session: the cross-project contract (`how-to-fix-issues-of-other-projects.md`) forbids
the janitor session from mutating another project's store, and the tool ENFORCES that
(it refuses unless the cwd's git repo IS `--project-repo`; there is no bypass flag).

Apply is guarded like any publish-and-destroy operation, because that is what it is —
PROJECT scope is git-tracked and PUSHED, so a mistake cannot be un-published:
  * it consumes the REVIEWED plan, and aborts if the corpus drifted since (what was
    reviewed must be what is applied);
  * it re-runs the privacy gate at apply time — one leak aborts the whole run;
  * it copies + byte-verifies every note BEFORE retiring any source, and retires a
    source by MOVING it to the repo's gitignored `.trashcan/` (recoverable by one `mv`),
    never by deleting it.

Fail-fast: a missing dir / a bad invocation / a refused guard exits non-zero with a
clear message. Nothing is ever half-applied.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_migrate as mm  # noqa: E402
import project_memory_tracked  # noqa: E402


def _stamp() -> str:
    """Local time + GMT offset (the agent-reports filename convention)."""
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S%z")


def _report_path(project_repo: Path, kind: str = "plan") -> Path:
    """Where a report is written: the MAIN repo's `reports/migrate-memory-scope/`
    (gitignored), timestamped local-time + GMT offset (the agent-reports rule)."""
    out_dir = project_repo / "reports" / "migrate-memory-scope"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{_stamp()}-{kind}.md"


def _cwd_repo_root() -> Path | None:
    """The git root of the CURRENT working directory, or None when cwd is not in a repo.
    This is what the ownership guard compares against `--project-repo`."""
    try:
        # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock
        # and collides with a concurrent `publish.py` commit (janitor#245).
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10, check=False,
            env=git_env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip())


def _do_apply(args: argparse.Namespace, memdir: Path, project_repo: Path) -> int:
    """The Phase-2 apply. Every guard refuses by RAISING, before anything is mutated;
    a refusal is reported verbatim and exits non-zero, so a half-applied corpus is not
    a state this can reach."""
    if not args.plan:
        print(
            "error: --apply requires --plan <plan.md> — the reviewed dry-run plan. "
            "Apply is driven by what a human reviewed, not by a fresh classification.",
            file=sys.stderr,
        )
        return 2
    plan_file = Path(args.plan).expanduser()
    if not plan_file.is_file():
        print(f"error: plan not found: {plan_file}", file=sys.stderr)
        return 2

    try:
        # Guard 1 — the cross-project contract, enforced in code.
        mm.check_ownership(project_repo, _cwd_repo_root())
        # Guards 2 + 3 — the reviewed plan still describes reality, and every note
        # about to be PUBLISHED is privacy-clean RIGHT NOW (not "was, at plan time").
        planned = mm.parse_plan_project_set(plan_file.read_text(encoding="utf-8"))
        verdicts = mm.check_plan_matches_corpus(memdir, planned)
        # PROJECT scope is only real if git actually tracks it — a corpus published
        # into a gitignored dir would be shared with nobody.
        status, detail = project_memory_tracked.ensure_tracked(project_repo)
        # Guard 4 — copy + byte-verify everything before any source is retired.
        results = mm.apply_plan(
            memdir, project_repo, [v.rel_path for v in verdicts],
            stamp=_stamp(), keep_source=args.keep_source,
        )
    except mm.MigrationRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: apply failed ({exc})", file=sys.stderr)
        return 2

    report = _report_path(project_repo, "applied")
    lines = [
        "# Memory scope-migration — APPLIED",
        "",
        f"- Source LOCAL corpus: `{memdir}`",
        f"- Target PROJECT scope: `{mm.project_memory_root(project_repo)}`",
        f"- Plan applied: `{plan_file}`",
        f"- Notes published: {len(results)}",
        f"- Sources: {'KEPT (copy only)' if args.keep_source else 'retired to .trashcan/ (recoverable)'}",
        f"- git-tracking of PROJECT scope: {status} — {detail}",
        "",
        "## Published",
        "",
        *(f"- `{rel}` — {outcome}" for rel, outcome in results),
        "",
        "> Commit the new notes so the PROJECT scope is actually shared:",
        "> `git add .claude/project/memory && git commit`",
        "",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"applied {len(results)} note(s) → {mm.project_memory_root(project_repo)}. Report: {report}")
    print("next: review `git status`, then commit .claude/project/memory/ to share them.")
    return 0


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
        help="PHASE 2 — publish the plan's PROJECT notes (owning repo only; needs --plan)",
    )
    ap.add_argument(
        "--plan",
        help="the reviewed dry-run plan to apply (REQUIRED with --apply)",
    )
    ap.add_argument(
        "--keep-source",
        action="store_true",
        help="with --apply: copy only, do not retire the LOCAL originals",
    )
    args = ap.parse_args()

    memdir = Path(args.local_mem_dir).expanduser()
    project_repo = Path(args.project_repo).expanduser()

    if not memdir.is_dir():
        print(f"error: local mem dir not found: {memdir}", file=sys.stderr)
        return 2

    if args.apply:
        return _do_apply(args, memdir, project_repo)

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
