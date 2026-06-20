# PROJECT-memory gitignore-exception enforcer (TRDD-3f7b6807, Phase 2).
#
# GOAL: guarantee a repo's `.claude/project/memory/` is git-TRACKED — the
# PROJECT memory scope is shared with every contributor, so it must live in
# the repo. The ONLY sanctioned mechanism is a `.gitignore` NEGATION
# (exception) line: `!.claude/project/memory/**`. We NEVER `git add`, NEVER
# `git add -f`, NEVER force-stage — those bypass the user's ignore intent and
# can drag in sibling files the user deliberately excluded. We only ever
# APPEND exception lines (atomically), and we NEVER rewrite an existing ignore
# line (a directory-pruning `.claude/` is the user's call to fix).
#
# Imported (not run as a script) so no PEP 723 metadata block. Stdlib-only.

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The canonical exception triplet, in dependency order. git evaluates
# .gitignore patterns top-to-bottom and — critically — will NOT re-include a
# file inside a directory that itself stays excluded. So the parent dirs must
# be un-ignored FIRST, narrowest pattern LAST. We probe MEMORY.md (the index
# file the memory system always creates) as the canary for "is the scope
# reachable by git".
_PROBE_REL = ".claude/project/memory/MEMORY.md"
_EXCEPTIONS = (
    "!.claude/project/",
    "!.claude/project/memory/",
    "!.claude/project/memory/**",
)


def _check_ignored(repo_root: Path) -> bool | None:
    """Is `_PROBE_REL` currently ignored by git? True/False, or None on error.

    Uses `git check-ignore -q <path>`: exit 0 = the path IS ignored, exit 1 =
    NOT ignored. `-q` suppresses output (we only read the exit code). Any other
    outcome (git missing, not a repo, timeout, exit ≥ 2) is reported as None so
    the caller fails safe (no spurious gitignore edits when we can't tell).

    Note: check-ignore answers from the .gitignore RULES, not from whether the
    file exists on disk — exactly what we need to verify the exception works.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", _PROBE_REL],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    # check-ignore returns ≥2 on a fatal error (e.g. not a git repo). Treat as
    # indeterminate so we never edit .gitignore on a bad probe.
    return None


def _append_missing_exceptions(gitignore: Path) -> list[str]:
    """Append any of `_EXCEPTIONS` not already present as an exact line.

    Atomic (tmp + os.replace, the file analogue of the daemon's single-writer
    lock). Preserves all existing content verbatim and the canonical exception
    ORDER for the lines we add. Returns the list of lines actually added (empty
    if all three were already present). NEVER rewrites or removes an existing
    line.
    """
    existing_text = ""
    if gitignore.exists():
        # errors='replace' so a stray non-UTF-8 byte can't crash the enforcer;
        # we only ever read it to test for our exact ASCII exception lines.
        existing_text = gitignore.read_text(encoding="utf-8", errors="replace")
    existing_lines = set(existing_text.splitlines())

    to_add = [exc for exc in _EXCEPTIONS if exc not in existing_lines]
    if not to_add:
        return []

    # Preserve the file's trailing-newline state: if the current content does
    # not end in a newline, add one before our block so we never glue our first
    # exception onto the user's last line.
    parts: list[str] = []
    if existing_text:
        parts.append(existing_text)
        if not existing_text.endswith("\n"):
            parts.append("\n")
    parts.append("\n".join(to_add))
    parts.append("\n")
    new_text = "".join(parts)

    tmp = gitignore.with_suffix(gitignore.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, gitignore)
    return to_add


def ensure_tracked(repo_root: Path | str) -> tuple[str, str]:
    """Guarantee `<repo>/.claude/project/memory/` is git-trackable via a
    .gitignore EXCEPTION, NEVER by force-staging.

    Returns (action, detail) where action is one of:
      * "absent"          — the memory dir doesn't exist; nothing to do.
      * "already-tracked" — the scope is NOT ignored (no exception needed).
      * "exception-added" — we appended the missing exception line(s); the
                            scope is now reachable by git. `detail` lists them.
      * "needs-manual"    — a directory-pruning ignore (e.g. bare `.claude/`)
                            stops git descending, so an exception can't apply;
                            a human must change it. We do NOT auto-rewrite it.
      * "error"           — could not determine ignore status (git missing /
                            not a repo / probe failed); `detail` carries why.

    NEVER calls `git add`. NEVER raises — every failure path returns
    ("error", msg) so a heartbeat detector calling this can't crash a fire.
    """
    try:
        root = Path(repo_root)
        mem_dir = root / ".claude" / "project" / "memory"

        # 1) No memory dir → nothing to enforce.
        if not mem_dir.is_dir():
            return ("absent", f"{mem_dir} does not exist")

        # 2) Probe whether the scope is currently ignored.
        ignored = _check_ignored(root)
        if ignored is None:
            return ("error", "git check-ignore unavailable (not a git repo / git missing)")
        if not ignored:
            # Exit 1 — NOT ignored → already tracked (or trackable).
            return ("already-tracked", f"{_PROBE_REL} is not ignored")

        # 3) Ignored → append the missing exception line(s) to .gitignore.
        gitignore = root / ".gitignore"
        added = _append_missing_exceptions(gitignore)

        # Re-probe: did the exception take effect?
        ignored_after = _check_ignored(root)
        if ignored_after is None:
            return ("error", "re-probe of git check-ignore failed after editing .gitignore")
        if not ignored_after:
            detail = ", ".join(added) if added else "exception lines already present"
            return ("exception-added", detail)

        # 4) STILL ignored → a directory-pruning ignore line prevents git from
        #    descending into .claude/, so a `!`-exception can never re-include
        #    a child path. The enforcer must NOT rewrite the existing ignore
        #    line (that's the user's deliberate config); surface it for a human.
        return (
            "needs-manual",
            "a directory-pruning ignore like bare `.claude/` prevents git "
            "descending; change it to `.claude/**` so exceptions apply — "
            "enforcer never rewrites an existing ignore line",
        )
    except Exception as exc:  # noqa: BLE001 - never crash a caller (heartbeat)
        return ("error", f"unexpected failure: {exc}")
