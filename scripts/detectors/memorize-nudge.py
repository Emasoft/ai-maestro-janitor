#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""memorize-nudge — nudge the agent to MEMORIZE when code outran the wiki.

Priority #6 of the memory-curation mission (TRDD-87935f21): "Claudes are nudged
to memorize recent changes." A wiki is only useful if it stays populated — but
the harness `# Memory` directive fires only when the agent *chooses* to write,
and in a long coding session that choice is easy to skip. This detector closes
the loop: when SUBSTANTIVE commits have landed since the last memory note, it
reminds the agent (once per interval) to capture what changed and WHY, with a
pointer to /janitor-memory-write and the recall-first rule.

WHY a heartbeat detector and NOT a Stop/PostToolUse hook: commits land via Bash
(`git commit`) whose exact moment a Stop hook can't reliably bracket, and a
substantive change is often several commits — a per-commit hook would either nag
on every commit or miss the batch. The heartbeat sees the accumulated git state
and the memory-dir mtimes together, so it fires at most once per interval and
goes SILENT the moment the agent memorizes (the gap closes itself).

NEVER NAGS, by construction:
- ADOPTION GATE: silent unless the project already has ≥1 memory note in LOCAL or
  PROJECT scope (memory is demonstrably in use here). A vanilla project that does
  not use the wiki is never nudged. Override with
  CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_REQUIRE_ADOPTION=false to also nudge an
  empty wiki (aggressive mode — e.g. the ai-maestro fleet).
- THRESHOLD: needs ≥ MIN_COMMITS substantive commits (default 3) — a single tiny
  commit does not trigger it.
- SUBSTANTIVE-ONLY: bookkeeping commits (memory writes, TRDDs/design, reports,
  CHANGELOG, release commits) are not "changes worth memorizing" and are excluded
  — so a flurry of release/docs commits never triggers the nudge.
- WINDOW: only commits NEWER than the last memory note (capped at 14 days) count,
  so memorizing immediately silences it; a stale clock can't resurrect it.
- DEDUPE: per-session, one nudge per interval (no per-commit spam).

Project-scoped; reads git + LOCAL/PROJECT memory mtimes only. Never mutates
anything, never touches USER/global scope (a cross-project USER write must not
suppress THIS project's nudge).
"""

from __future__ import annotations

import hashlib
import os
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import memory_scopes  # noqa: E402
import state  # noqa: E402

# Paths whose changes are NOT "code/knowledge worth memorizing": the memory store
# itself, design/TRDD bookkeeping, gitignored dev dirs, generated changelog.
_BOOKKEEPING_PREFIXES = (
    ".claude/project/memory/",
    "design/",
    "docs_dev/",
    "reports/",
    "reports_dev/",
    "scripts_dev/",
    "samples_dev/",
    "examples_dev/",
    "tests_dev/",
    "downloads_dev/",
    "libs_dev/",
    "builds_dev/",
)
_BOOKKEEPING_BASENAMES = frozenset(
    {"CHANGELOG.md", "MEMORY.md", "memory-index.md", "memory-reorg-proposed.md"}
)
# Files in a memory dir that are NOT notes (indexes / the librarian's proposal).
_NON_NOTE_BASENAMES = _BOOKKEEPING_BASENAMES
# A commit whose subject matches this is bookkeeping regardless of its files.
_RELEASE_SUBJECT = ("chore(release)", "chore: release", "bump version")

_MAX_WINDOW_S = 14 * 86400  # never look back further than 14 days for "recent"
_MAX_COMMITS = 50           # bound the git scan
_SUBJ_TRUNC = 64            # truncate the latest subject in the nudge line


def _session_key() -> str:
    """Session-scoped dedupe key (mirrors report-to-trdd: a fresh session reminds
    independently; no PPID — it rotates)."""
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    host = socket.gethostname().split(".")[0]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return hashlib.sha1(f"{host}@{today}".encode("utf-8")).hexdigest()[:12]


def _note_files(scope_dir: Path) -> list[Path]:
    """Real memory NOTES under `scope_dir` (excludes indexes, the reorg proposal,
    and the private user-mem/ subtree)."""
    out: list[Path] = []
    try:
        for p in scope_dir.rglob("*.md"):
            if p.name in _NON_NOTE_BASENAMES:
                continue
            if "user-mem" in p.parts:
                continue
            out.append(p)
    except OSError:
        return []
    return out


def _last_memory_mtime(scope_dirs: list[tuple[str, Path]]) -> tuple[int, int]:
    """(newest note mtime, note count) across LOCAL+PROJECT scopes. USER is
    excluded: it is cross-project, so a global write while working elsewhere must
    not look like 'this project was memorized'."""
    newest = 0
    count = 0
    for label, d in scope_dirs:
        if label == "USER":
            continue
        for note in _note_files(d):
            count += 1
            mt = state.file_mtime(note)
            if mt > newest:
                newest = mt
    return newest, count


def _is_substantive(subject: str, files: list[str]) -> bool:
    """A commit is substantive iff it is not a release commit AND it changed at
    least one file outside the bookkeeping set."""
    subj = subject.strip().lower()
    if any(subj.startswith(p) for p in _RELEASE_SUBJECT):
        return False
    for f in files:
        f = f.strip()
        if not f:
            continue
        base = f.rsplit("/", 1)[-1]
        if base in _BOOKKEEPING_BASENAMES:
            continue
        if any(f.startswith(pre) for pre in _BOOKKEEPING_PREFIXES):
            continue
        return True  # a real, non-bookkeeping file changed
    return False


def _substantive_commits_since(root: Path, secs: int) -> list[str]:
    """Subjects of substantive commits in the last `secs` seconds, newest first.

    Uses \\x01 as the commit-record separator and \\x1f between sha and subject so
    parsing never collides with anything in a real subject line.
    """
    if secs <= 0:
        return []
    proc = state.run_subprocess(
        [
            "git", "log",
            f"--since={secs} seconds ago",
            f"--max-count={_MAX_COMMITS}",
            "--no-merges",
            "--name-only",
            "--pretty=format:%x01%H%x1f%s",
        ],
        timeout=15,
        cwd=str(root),
        capture=True,
        detector_name="memorize-nudge",
    )
    if proc is None or proc.returncode != 0 or not proc.stdout:
        return []
    subjects: list[str] = []
    for chunk in proc.stdout.split("\x01"):
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        header = lines[0]
        if "\x1f" not in header:
            continue
        _sha, subject = header.split("\x1f", 1)
        files = [ln for ln in lines[1:] if ln.strip()]
        if _is_substantive(subject, files):
            subjects.append(subject)
    return subjects


def main() -> int:
    state.init_state()
    interval = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_INTERVAL"),
        14400,
        detector_name="memorize-nudge",
        var_name="CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_INTERVAL",
    )
    min_commits = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_MIN_COMMITS"),
        3,
        detector_name="memorize-nudge",
        var_name="CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_MIN_COMMITS",
    )
    require_adoption = state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_REQUIRE_ADOPTION", default=True
    )

    root = state.project_root()
    # Only nudge inside a git work tree (no commits → nothing to nudge about).
    inside = state.run_subprocess(
        ["git", "rev-parse", "--is-inside-work-tree"],
        timeout=10, cwd=str(root), capture=True, detector_name="memorize-nudge",
    )
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return 0

    scope_dirs = memory_scopes.resolve_scope_dirs()
    last_mem, note_count = _last_memory_mtime(scope_dirs)

    # ADOPTION GATE: by default stay silent unless the wiki is in use here.
    if require_adoption and note_count == 0:
        return 0

    now = int(time.time())
    # Window: commits newer than the last memory note, capped at 14 days. An empty
    # wiki (last_mem == 0, adoption gate off) looks back the full window.
    cutoff = max(last_mem, now - _MAX_WINDOW_S)
    secs = max(0, now - cutoff)
    subjects = _substantive_commits_since(root, secs)

    if len(subjects) < max(1, min_commits):
        return 0

    raw_latest = subjects[0]
    clipped = raw_latest[:_SUBJ_TRUNC] + ("…" if len(raw_latest) > _SUBJ_TRUNC else "")
    latest = state.sanitize_for_drift_line(clipped)
    n = len(subjects)
    more = "" if n < _MAX_COMMITS else "+"  # we capped the scan; show it's a floor
    msg = (
        f"[memorize-nudge] {n}{more} substantive commit(s) since the last memory "
        f'note (latest: "{latest}"). Capture what changed + WHY in the wiki — '
        f"/janitor-memory-write (PROJECT scope for architecture/code knowledge, "
        f"LOCAL for machine-specific). Recall first (/janitor-memory-recall) so you "
        f"update an existing page, not duplicate it."
    )

    # Tick-bucket dedupe keyed by interval ONLY (NOT HEAD) so rapid commits never
    # produce a per-commit nag: at most one nudge per interval, and it auto-silences
    # the moment a memory note is written (the gap closes → count drops below
    # threshold). Per-session so a fresh session is reminded independently.
    seen = state.state_dir() / f"memorize-nudge-session-{_session_key()}.txt"
    tick_key = f"tick-{now // max(1, interval)}"
    line = dedupe.emit_once(seen, tick_key, msg)
    if line is not None:
        print(line)

    state.rotate_log_if_big("memorize-nudge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
