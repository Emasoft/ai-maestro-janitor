"""Keep `reports/` and `reports_dev/` out of git — check, and FIX (TRDD-WP7TCRME Rule 3).

Agents, skills, hooks and scans all write reports under `<repo>/reports/`. Those reports
routinely contain absolute home paths, usernames, internal hostnames, proprietary source, and
credentials caught in a pasted log. Committing one is a data leak, and on a public repo it is
an irreversible one — a later `git rm` does not remove it from history, from forks, or from
whatever already mirrored it.

The invariant is therefore a hard rule, and it was a rule NOTHING enforced: every project was
expected to remember two `.gitignore` lines. This checks them, and where they are missing it
ADDS them, because there is exactly one defensible answer to "your report directory is not
ignored" and narrating it at the reader is not it.

WHAT IT DELIBERATELY DOES NOT DO. If `reports/` already contains TRACKED files, it reports and
stops. Untracking has two defensible answers — `git rm --cached` (keep the files, stop tracking)
or leave them (they may have been committed on purpose) — and choosing between them can lose
work or rewrite intent. Worse, if the content is already public, untracking creates a false
sense of remedy: the leak needs rotation and history surgery, not a gitignore line. That is a
human's call, so it stays one.

Asks GIT whether a path is ignored rather than parsing `.gitignore` — negation patterns,
directory semantics, nested ignore files and the global excludes file all make hand-parsing
wrong in ways that only show up on someone else's machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import state  # noqa: E402

__all__ = ["REQUIRED_DIRS", "ensure_ignored", "is_ignored", "tracked_under"]

# `reports/` is the canonical home for a FINAL artefact; `reports_dev/` is dev-only scratch.
# Both leak the same things, so both are required — a project that ignores one and not the
# other is one careless `--output` flag away from the same incident.
REQUIRED_DIRS = ("reports", "reports_dev")

_BLOCK_HEADER = "# janitor: report dirs carry private data (paths, hostnames, pasted secrets)"


def is_ignored(root: Path, rel: str) -> bool | None:
    """True/False, or None when git cannot answer (not a repo, git missing).

    Three-valued because "git failed" must not read as "not ignored": acting on that would
    append duplicate lines to a file that may already be correct, on every fire.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "check-ignore", "-q", rel],
        timeout=8,
        detector_name="reports-gitignore",
    )
    if proc is None or proc.returncode not in (0, 1):
        return None
    return proc.returncode == 0


def tracked_under(root: Path, directory: str) -> list[str]:
    """Files git already TRACKS under `directory` — the case this must not auto-resolve."""
    proc = state.run_subprocess(
        ["git", "-C", str(root), "ls-files", "--", directory],
        timeout=8,
        detector_name="reports-gitignore",
    )
    if proc is None or proc.returncode != 0:
        return []
    return [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]


def ensure_ignored(root: Path) -> tuple[list[str], list[str], list[str]]:
    """Ensure both report dirs are ignored. Returns `(added, already_ok, needs_human)`.

    `needs_human` names the dirs that are unignored AND already have tracked files — the
    decision-margin case. They are NOT added to `.gitignore` here: a gitignore line does not
    untrack an already-tracked file, so adding one would leave the repo still leaking while the
    finding disappears. Silencing a warning without fixing the thing is worse than the warning.
    """
    added: list[str] = []
    ok: list[str] = []
    needs_human: list[str] = []

    missing: list[str] = []
    for d in REQUIRED_DIRS:
        verdict = is_ignored(root, f"{d}/probe")
        if verdict is None:
            return ([], [], [])  # cannot tell — do nothing rather than guess
        if verdict:
            ok.append(d)
        elif tracked_under(root, d):
            needs_human.append(d)
        else:
            missing.append(d)

    if not missing:
        return (added, ok, needs_human)

    gitignore = root / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
        # Append, never rewrite: this file is the user's, and it is hand-curated in every repo
        # worth having one. A trailing newline is added only when the file lacks one, so a
        # repeat run cannot slowly grow blank lines at the end.
        block = "" if existing.endswith("\n") or not existing else "\n"
        block += f"\n{_BLOCK_HEADER}\n" + "".join(f"/{d}/\n" for d in missing)
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(block)
        added.extend(missing)
    except OSError as exc:
        state.log_line("reports-gitignore", f"could not update .gitignore: {exc}")
        return ([], ok, needs_human)

    return (added, ok, needs_human)


def format_finding(needs_human: list[str]) -> str:
    """The one line for the decision-margin case, or "" when there is nothing to say."""
    if not needs_human:
        return ""
    names = ", ".join(f"{d}/" for d in sorted(needs_human))
    return (
        f"[reports-gitignore] {names} is NOT ignored and already has TRACKED files — a "
        "gitignore line would hide the finding without untracking anything. Decide: "
        "`git rm --cached` (keep the files, stop tracking) or keep them committed on purpose. "
        "If any report already reached a public remote, treat it as a disclosed secret: "
        "rotate first, history surgery second."
    )
