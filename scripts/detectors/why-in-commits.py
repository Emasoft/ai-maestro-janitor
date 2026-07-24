#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""why-in-commits — nudge when recent substantive commits carry no WHY.

Priority #6 of the memory-curation mission (TRDD-87935f21): "the WHY-in-commit
-messages rule is honored." The commit-discipline rule (rules/commit-discipline.md)
already ships — it asks every commit to record WHY the change is the way it is, in
the message body, because that knowledge can only be written by the author at the
moment of the change and is lost forever once committed without it. This detector
is the ENFORCEMENT half: it surfaces recent feat/fix/refactor/perf commits that are
subject-only (no body → no WHY) and reminds the agent to write the WHY.

WHY a heartbeat detector and not a commit-msg git hook: the janitor must not install
git hooks into arbitrary repos, and a git hook can't nudge the *agent* (it blocks the
*human*). The heartbeat sees the recent git history and reminds the Claude that made
the commits.

NEVER NAGS, by construction:
- ai-maestro GATE: silent outside an ai-maestro project (the fleet that mandates the
  discipline + uses conventional-commit prefixes). Override with JANITOR_FORCE_AI_MAESTRO.
- CONVENTIONAL-TYPE TARGETING: only feat/fix/refactor/perf commits are candidates —
  the substantive types. docs/test/chore/style/ci/build are legitimately terse and
  are never flagged. A non-conventional history yields zero candidates → silent.
- BODY = WHY proxy: a commit WITH a body is trusted (we can't judge whether prose is
  a genuine WHY, so we never second-guess it); only the unambiguous subject-only case
  is deficient.
- THRESHOLD: needs ≥ MIN deficient commits (default 3) — a single terse commit is
  forgiven.
- WINDOW: only the last 3 days (recent habits, not immutable ancient history).
- DEDUPE: keyed on the SET of deficient shas, so the agent is reminded ONCE per
  distinct set (a new deficient commit re-nudges; the same old un-amendable commits
  are not nagged every interval).

Project-scoped, read-only (git log only); never mutates anything.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

# Conventional-commit types that denote substantive code work (an explanation of
# WHY is expected). docs/test/chore/style/ci/build are intentionally excluded.
_SUBSTANTIVE_TYPE = re.compile(r"^(feat|fix|refactor|perf)(\(|:|!)", re.IGNORECASE)

_WINDOW_S = 3 * 86400  # recent habits only — don't nag about ancient history
_MAX_COMMITS = 30      # bound the git scan
_MAX_LISTED = 4        # cap how many short shas we name in one line


def _session_key() -> str:
    """Session-scoped dedupe key (mirrors report-to-trdd: a fresh session reminds
    independently; no PPID — it rotates)."""
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    host = socket.gethostname().split(".")[0]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return hashlib.sha1(f"{host}@{today}".encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _deficient_commits(root: Path, secs: int) -> list[str]:
    """Short shas of substantive commits with NO body, newest first.

    \\x01 separates commit records; \\x1f separates sha / subject / body. The body
    is the LAST field so a multi-line body never collides with the separators.
    """
    if secs <= 0:
        return []
    proc = state.run_subprocess(
        [
            "git", "log",
            f"--since={secs} seconds ago",
            f"--max-count={_MAX_COMMITS}",
            "--no-merges",
            "--pretty=format:%x01%h%x1f%s%x1f%b",
        ],
        timeout=15,
        cwd=str(root),
        capture=True,
        detector_name="why-in-commits",
    )
    if proc is None or proc.returncode != 0 or not proc.stdout:
        return []
    out: list[str] = []
    for chunk in proc.stdout.split("\x01"):
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f", 2)
        if len(parts) < 3:
            continue
        sha, subject, body = parts[0].strip(), parts[1], parts[2]
        if not _SUBSTANTIVE_TYPE.match(subject.strip()):
            continue
        if body.strip() == "":  # subject-only → no WHY recorded
            out.append(sha)
    return out


def main() -> int:
    state.init_state()
    # Context gate: the commit-discipline enforcement nudge is an ai-maestro fleet
    # convention (+ assumes conventional-commit prefixes). Stay silent elsewhere.
    if not state.project_is_ai_maestro():
        return 0
    min_deficient = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_WHY_IN_COMMITS_MIN"),
        3,
        detector_name="why-in-commits",
        var_name="CLAUDE_PLUGIN_OPTION_WHY_IN_COMMITS_MIN",
    )

    root = state.project_root()
    inside = state.run_subprocess(
        ["git", "rev-parse", "--is-inside-work-tree"],
        timeout=10, cwd=str(root), capture=True, detector_name="why-in-commits",
    )
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return 0

    deficient = _deficient_commits(root, _WINDOW_S)
    if len(deficient) < max(1, min_deficient):
        return 0

    listed = deficient[:_MAX_LISTED]
    more = "" if len(deficient) <= _MAX_LISTED else f" (+{len(deficient) - _MAX_LISTED} more)"
    msg = (
        f"[why-in-commits] {len(deficient)} recent feat/fix/refactor commit(s) have "
        f"no body explaining WHY (subject-only): {', '.join(listed)}{more}. The WHY can "
        f"only be written by the author and is lost once committed — record it in the "
        f"message body (and a TRDD-<8hex> when implementing a TRDD). See "
        f"rules/commit-discipline.md."
    )

    # Dedupe on the SET of deficient shas: a new deficient commit yields a fresh key
    # (fresh nudge), but the same un-amendable old commits are not re-nagged every
    # interval. Per-session so a fresh session is reminded once.
    sig = hashlib.sha1(",".join(sorted(deficient)).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    seen = state.state_dir() / f"why-in-commits-session-{_session_key()}.txt"
    line = dedupe.emit_once(seen, f"set-{sig}", msg)
    if line is not None:
        print(line)

    state.rotate_log_if_big("why-in-commits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
