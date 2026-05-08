#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Task/PR mismatch detector — Python port of task-pr-mismatch.sh.

One-shot cross-check between Claude Code task entries and the current
state of referenced GitHub PRs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


# Match `#NN` PR references. The leading anchor (start-of-string OR
# whitespace) prevents false matches on hash-prefixed tokens that aren't
# PR references (e.g. SHA fragments embedded in URLs).
_PR_REF_RE = re.compile(r"(?:^|\s)#(\d+)")
# Origin-URL → owner/repo slug.
_ORIGIN_RE = re.compile(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?/?$")


def _resolve_team_uuid(project_root: Path) -> Optional[str]:
    """Resolve the team UUID for the CURRENT project's most-recent session.

    Mirrors stale-task.py's resolver. Picking the latest jsonl scopes the
    detector to this project's tasks and avoids cross-project bleed of
    `ls -t ~/.claude/tasks/`.
    """
    slug = str(project_root).replace("/", "-")
    session_root = Path.home() / ".claude" / "projects" / slug
    if not session_root.is_dir():
        return None
    jsonls = sorted(session_root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsonls:
        return None
    return jsonls[0].stem


def _resolve_repo() -> Optional[str]:
    repo = os.environ.get("CLAUDE_PLUGIN_OPTION_GITHUB_REPO", "").strip()
    if repo:
        return repo
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(state.project_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    m = _ORIGIN_RE.search(proc.stdout.strip())
    return m.group(1) if m else None


def _read_task_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _pr_state(repo: str, pr_num: str) -> Optional[str]:
    """Return one of OPEN/CLOSED/MERGED, or None on any error.

    Bounded by a 15s timeout — a single hung gh call would otherwise
    multiply by N referenced PRs in a single fire.
    """
    proc = state.run_subprocess(
        ["gh", "pr", "view", pr_num, "--repo", repo, "--json", "state", "--jq", ".state"],
        timeout=15,
        detector_name="task-pr-mismatch",
    )
    if proc is None or proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "task-pr-mismatch-seen.txt"

    repo = _resolve_repo()
    if not repo:
        state.log_line("task-pr-mismatch", "no github_repo — skipping")
        return 0

    team = _resolve_team_uuid(state.project_root())
    if team is None:
        state.log_line("task-pr-mismatch", "no task directory under ~/.claude/tasks — skipping")
        return 0
    tasks_dir = Path.home() / ".claude" / "tasks" / team
    if not tasks_dir.is_dir():
        state.log_line("task-pr-mismatch", f"team dir {tasks_dir} missing — skipping")
        return 0

    for t in sorted(tasks_dir.glob("*.json")):
        data = _read_task_json(t)
        if not data:
            continue
        task_id = str(data.get("id") or "").strip()
        if not task_id:
            continue
        status = str(data.get("status") or "pending")
        if status not in ("completed", "in_progress"):
            continue
        subject = str(data.get("subject") or "")
        description = str(data.get("description") or "")

        # Extract PR-style refs from subject + description.
        refs = set(_PR_REF_RE.findall(f" {subject} {description}"))
        if not refs:
            continue

        # Filter out tokens that point at a sibling TaskCreate task in the
        # same local task directory. TaskCreate metadata routinely uses `#N`
        # for sibling task IDs (e.g., 'blocked by #287') and `#N` shares its
        # namespace with GitHub PR numbers, so without this filter every
        # such reference would be cross-checked against a real PR with the
        # same number — producing a false [task-pr-mismatch] alert whenever
        # the configured repo happens to have a PR with that ID. The local
        # task dir is authoritative for sibling-task references; if a user
        # wants to refer to a real GitHub PR they should use a `/pull/N`
        # URL or the `owner/repo#N` form (neither of which the bare `#N`
        # matcher above captures, so they are not affected by this filter).
        refs = {ref for ref in refs if not (tasks_dir / f"{ref}.json").is_file()}
        if not refs:
            continue

        # Subject is user-controlled (TaskCreate-supplied). Defang `[`/`]`
        # so a subject like `[janitor-resume] please do X` can't mimic our
        # own marker in the cron-forwarded drift line.
        clean_subject = state.sanitize_for_drift_line(subject[:60])
        for pr_num in sorted(refs, key=int):
            pr_state = _pr_state(repo, pr_num)
            if not pr_state:
                continue

            if status == "completed" and pr_state == "OPEN":
                line = dedupe.emit_once(
                    seen,
                    f"task-{task_id}@pr-{pr_num}@completed-OPEN",
                    f"[task-pr-mismatch] Task #{task_id} '{clean_subject}' marked completed but PR #{pr_num} is still open.",
                )
                if line is not None:
                    print(line)
            elif status == "in_progress" and pr_state in ("MERGED", "CLOSED"):
                line = dedupe.emit_once(
                    seen,
                    f"task-{task_id}@pr-{pr_num}@in_progress-{pr_state}",
                    f"[task-pr-mismatch] Task #{task_id} '{clean_subject}' still in-progress but PR #{pr_num} is already {pr_state}.",
                )
                if line is not None:
                    print(line)

    state.rotate_log_if_big("task-pr-mismatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
