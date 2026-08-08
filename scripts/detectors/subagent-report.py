#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Subagent report detector — Python port of subagent-report.sh.

Nudges Claude Code to act on recent subagent report files in docs_dev/,
tests/scenarios/reports/, scripts_dev/ that have not yet been referenced
in any commit message. Catches the 'agent wrote a report but the
findings were never acted upon' drift pattern.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

_SCAN_DIRS = ("docs_dev", "tests/scenarios/reports", "scripts_dev")
_MAX_EMIT_PER_FIRE = 5


def _path_or_parent_referenced(rel: str, scan_dir: str, commits: str) -> bool:
    """True if `rel` OR any of its parent directories appears in `commits`.

    Handles the common case where a commit references a parent directory
    (e.g. a timestamped backup snapshot folder) as a single logical
    artifact, rather than listing every file inside it. Without the
    walk-up, every file under such a directory was reported as
    unreferenced even though the parent was explicitly committed.

    We stop before reaching the scan dir itself because bare names like
    'docs_dev' are too generic — any unrelated commit message that
    happens to mention 'docs_dev' would suppress legitimate orphan alerts.
    """
    if not commits:
        return False
    p = rel
    while True:
        if p in commits:
            return True
        parent = p.rsplit("/", 1)[0] if "/" in p else ""
        if parent == p or parent == scan_dir or not parent:
            return False
        p = parent


def _dir_is_gitignored(scan_dir: str, root: Path) -> bool:
    """True iff `scan_dir` is matched by git's ignore rules.

    The `_dev` scratch convention (`docs_dev/`, `scripts_dev/`, `reports*/`)
    gitignores whole directories — so every file under them is INTENTIONALLY
    uncommittable (RULE 0.2). Reporting per-file that such a file is "not
    referenced in any commit" is pure noise: the file can never be committed,
    and a note placed in the same scratch dir is itself gitignored (#32).
    One `git check-ignore -q <dir>` per scan dir (3 calls total) classifies
    the dir; `-q` exits 0 when ignored, 1 when not.
    """
    proc = state.run_subprocess(
        ["git", "check-ignore", "-q", scan_dir],
        cwd=root,
        timeout=10,
        detector_name="subagent-report",
    )
    return proc is not None and proc.returncode == 0


def _recent_unreferenced(f: Path, root: Path, cutoff: int, scan_dir: str, commit_bodies: str):
    """Return (rel, mtime) if `f` is a recent .md not yet referenced in a commit.

    Factored out of main() so the gitignored-scratch path and the tracked
    per-file path apply the SAME recency + not-referenced filter. Returns
    None when the file is too old or already referenced (directly or via a
    committed parent dir).
    """
    if not f.is_file():
        return None
    mtime = state.file_mtime(f)
    if mtime == 0 or mtime < cutoff:
        return None
    try:
        rel = str(f.relative_to(root))
    except ValueError:
        return None
    if _path_or_parent_referenced(rel, scan_dir, commit_bodies):
        return None
    return rel, mtime


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "subagent-report-seen.txt"
    lookback = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_SUBAGENT_REPORT_LOOKBACK"), 86400)

    # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock and
    # collides with a concurrent `publish.py` commit (janitor#245).
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(state.project_root()),
        capture_output=True,
        text=True,
        check=False,
        env=git_env,
    )
    if proc.returncode != 0:
        state.log_line("subagent-report", "not a git repo — skipping")
        return 0

    root = state.project_root()
    now = int(time.time())
    cutoff = now - lookback

    # Collect commit messages within the lookback window once. Use the
    # epoch-syntax `--since=@<ts>` because the locale-dependent
    # `--since="7 days ago"` form fails on non-English LC_TIME and was
    # also hardcoded to 7d regardless of the lookback knob. Bound by a
    # 15s timeout so a corrupted ref doesn't park the heartbeat.
    since_epoch = max(0, now - max(lookback, 7 * 86400))
    log_proc = state.run_subprocess(
        ["git", "log", f"--since=@{since_epoch}", "--pretty=format:%s %b"],
        cwd=root,
        timeout=15,
        detector_name="subagent-report",
    )
    commit_bodies = log_proc.stdout if (log_proc is not None and log_proc.returncode == 0) else ""

    count = 0
    scratch_count = 0
    scratch_example = ""
    for d in _SCAN_DIRS:
        full = root / d
        if not full.is_dir():
            continue
        ignored = _dir_is_gitignored(d, root)
        for f in full.rglob("*.md"):
            hit = _recent_unreferenced(f, root, cutoff, d, commit_bodies)
            if hit is None:
                continue
            rel, mtime = hit

            # Gitignored _dev scratch: the file can NEVER be committed
            # (RULE 0.2), so the per-file "not referenced in any commit" nag
            # is un-actionable noise. Fold every such file into one daily
            # summary instead of N per-file lines (#32).
            if ignored:
                scratch_count += 1
                if not scratch_example:
                    scratch_example = d
                continue

            if count >= _MAX_EMIT_PER_FIRE:
                continue

            age_h = (now - mtime) // 3600
            bucket = (now - mtime) // 86400
            # `rel` comes from the project's filesystem (any user with write
            # access to the scan dir controls it). Defang `[`/`]` for the
            # prose; keep raw `rel` in the dedup key so dedup is unaffected.
            display_rel = state.sanitize_for_drift_line(rel)
            line = dedupe.emit_once(
                seen,
                f"report@{rel}@d{bucket}",
                f"[subagent-report] {display_rel} ({age_h}h old) has not been referenced in any commit — review and act on it, or commit a note explaining why it's deferred.",
            )
            if line is not None:
                print(line)
                count += 1

    # One soft heads-up per day for the whole gitignored-scratch bucket — keyed
    # on the local date so it fires at most once/day no matter how many scratch
    # files accumulate (the reporter saw 212 per-file nags every heartbeat).
    if scratch_count > 0:
        summary = dedupe.emit_once(
            seen,
            f"scratch-summary@d{now // 86400}",
            f"[subagent-report] {scratch_count} recent report file(s) under gitignored scratch "
            f"(e.g. {scratch_example}/) — intentionally uncommitted (RULE 0.2); act on any pending "
            "findings if needed, but no commit is required.",
        )
        if summary is not None:
            print(summary)

    state.rotate_log_if_big("subagent-report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
