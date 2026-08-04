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
# A commit whose subject matches this is bookkeeping regardless of its files.
_RELEASE_SUBJECT = ("chore(release)", "chore: release", "bump version")

_MAX_WINDOW_S = 14 * 86400  # never look back further than 14 days for "recent"
_MAX_COMMITS = 50           # bound the git scan (subject list only — see _MAX_COVERAGE_COMMITS)
_MAX_COVERAGE_COMMITS = 600  # the coverage scan must span the WHOLE window, not 50 commits
_SUBJ_TRUNC = 64            # truncate the latest subject in the nudge line
_MAX_NAMED_MODULES = 6      # name the worst offenders; a wall of stems is not actionable


def _session_key() -> str:
    """Session-scoped dedupe key (mirrors report-to-trdd: a fresh session reminds
    independently; no PPID — it rotates)."""
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    host = socket.gethostname().split(".")[0]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return hashlib.sha1(f"{host}@{today}".encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _note_files(scope_dir: Path) -> list[Path]:
    """Real memory NOTES under `scope_dir`, via the shared SSOT.

    `memory_scopes.iter_note_files` excludes the generated/index files, the
    detector-proposal reports (`-proposed.md`), and the PRIVATE user-mem/ subtree
    — the same filter every editor/librarian site now shares (TRDD-87935f21)."""
    return memory_scopes.iter_note_files(scope_dir)


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


def _uncovered_modules(changed: dict[str, int], scope_dirs: list[tuple[str, Path]]) -> list[str]:
    """The module FILENAMES that CHANGED but that no memory note anywhere MENTIONS.

    This is the coverage signal the recency window never had. `changed` maps a source file's
    BASENAME WITH ITS EXTENSION (`state.py`, not `state`) to how many substantive commits
    touched it; a module is COVERED if any LOCAL/PROJECT note's text contains that filename.
    Returns the uncovered filenames, most-churned first.

    THE EXTENSION IS LOAD-BEARING, and dropping it inverted this function's own safety claim.
    Matching the bare STEM as an unanchored substring means a module whose stem is an ordinary
    English word is "covered" by any note that happens to use that word: measured against this
    repo's PROJECT corpus on 2026-08-04, the stem `state` matched 32 of 48 notes and `auth` 30
    of 48, so `scripts/lib/state.py` could churn indefinitely and never be nudged about. That
    is FALSE SILENCE — the exact direction the docstring below claims cannot happen — and it is
    invisible, because a nudge that never fires looks identical to a corpus that is up to date.
    Word-boundary anchoring does NOT fix it (`\\bstate\\b` still matches the English word; it
    matched all 13 stems tested). Requiring `state.py` does: it flipped `markers`, `renderer`,
    `posture`, `suppression`, `tickets` and `memory` from "covered" to correctly uncovered,
    while a page that genuinely discusses a module names the file.

    WHY MENTION AND NOT `globs:` OWNERSHIP: the wikimem model reserves `globs:` for exactly
    this, but measured 2026-08-04 not one page in this corpus declares it, so an ownership
    query would compute over an empty relation and call EVERYTHING uncovered. A filename
    mention is weaker but true today, and it fails in the safe direction — a page that
    discusses a module almost always names its file, so false NUDGES are the error mode, not
    false silence. Swap in `globs:` once pages carry it."""
    if not changed:
        return []
    corpus: list[str] = []
    for label, d in scope_dirs:
        if label == "USER":
            continue
        for note in _note_files(d):
            try:
                corpus.append(note.read_text(errors="replace"))
            except OSError:
                continue
    blob = "\n".join(corpus)
    uncovered = [name for name in changed if name not in blob]
    uncovered.sort(key=lambda s: (-changed[s], s))
    return uncovered


def _changed_modules(root: Path, secs: int) -> dict[str, int]:
    """{module FILENAME: substantive commits touching it} over the window. Source files only —
    a doc or config churn is not knowledge that needs capturing.

    Keyed on the basename WITH its extension (`state.py`), not the bare stem — see
    `_uncovered_modules` for why the extension is what keeps the coverage check honest. The
    `test_` skip still looks at the STEM, since that prefix is about the file's role."""
    out: dict[str, int] = {}
    for _subject, files in _substantive_records(root, secs, max_count=_MAX_COVERAGE_COMMITS):
        for f in files:
            if not f.endswith((".py", ".rs", ".ts", ".js", ".sh")):
                continue
            name = Path(f).name
            if name and not Path(f).stem.startswith("test_"):
                out[name] = out.get(name, 0) + 1
    return out


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
    return [subject for subject, _files in _parse_log(proc.stdout)]


def _parse_log(stdout: str) -> list[tuple[str, list[str]]]:
    """(subject, files) for each SUBSTANTIVE commit in a `_LOG_FORMAT` payload. PURE.

    Split out so the coverage scan reuses the FILES the log already carries — the old code
    parsed `--name-only`, used it for the substantive test, and threw it away."""
    records: list[tuple[str, list[str]]] = []
    for chunk in stdout.split("\x01"):
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        header = lines[0]
        if "\x1f" not in header:
            continue
        _sha, subject = header.split("\x1f", 1)
        files = [ln for ln in lines[1:] if ln.strip()]
        if _is_substantive(subject, files):
            records.append((subject, files))
    return records


def _substantive_records(root: Path, secs: int, *, max_count: int = _MAX_COMMITS) -> list[tuple[str, list[str]]]:
    """`_substantive_commits_since` but keeping each commit's file list.

    `max_count` is separate from the nudge's own `_MAX_COMMITS` because the two scans want
    different things. The SUBJECT list only needs enough to say "N+ commits" — 50 is plenty.
    The COVERAGE scan needs the whole window, and truncating it reintroduces the exact bug
    this detector was just fixed for: measured 2026-08-04, this repo took 66 substantive
    commits in three days, so a 50-commit cap could not see back even two days — the
    injection commits that motivated the fix read as UNCHANGED, and their module as covered.
    A cap that silently shortens the window is indistinguishable from having no gap."""
    if secs <= 0:
        return []
    proc = state.run_subprocess(
        [
            "git", "log",
            f"--since={secs} seconds ago",
            f"--max-count={max_count}",
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
    return _parse_log(proc.stdout)


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
    _note_count_only, note_count = _last_memory_mtime(scope_dirs)

    # ADOPTION GATE: by default stay silent unless the wiki is in use here.
    if require_adoption and note_count == 0:
        return 0

    now = int(time.time())
    # WINDOW IS THE FULL 14 DAYS, NOT "since the last memory note" (fixed 2026-08-04).
    #
    # It used to be `cutoff = max(last_mem, now - _MAX_WINDOW_S)`, so the newest mtime of ANY
    # note on ANY subject moved the cutoff forward and permanently discarded every uncaptured
    # commit behind it. That measured RECENCY OF WRITING, not COVERAGE OF WORK, and it made
    # the detector blindest exactly when the agent was most diligent: memorizing topic A hid
    # topic B forever.
    #
    # Measured, the miss that forced this: on 2026-08-02 seven commits landed on the keystroke
    # injector — including the owner's three ratified rules — interleaved with eight memory
    # commits about other subjects. Each of those eight pushed the cutoff past the injection
    # commits, so the nudge never fired for them and structurally never could. Two days later
    # the mechanism was re-derived from scratch, wrongly, because nothing in the corpus
    # recorded it. `last_mem` is still read for the ADOPTION gate; it no longer gates time.
    secs = _MAX_WINDOW_S
    subjects = _substantive_commits_since(root, secs)

    if len(subjects) < max(1, min_commits):
        return 0

    # COVERAGE, not recency: nudge only about modules that changed and that NO note mentions.
    # This is what makes a memory write silence the nudge for the thing it actually covered,
    # and only that thing — the property the old window claimed and did not have.
    uncovered = _uncovered_modules(_changed_modules(root, secs), scope_dirs)
    if not uncovered:
        return 0

    raw_latest = subjects[0]
    clipped = raw_latest[:_SUBJ_TRUNC] + ("…" if len(raw_latest) > _SUBJ_TRUNC else "")
    latest = state.sanitize_for_drift_line(clipped)
    n = len(subjects)
    more = "" if n < _MAX_COMMITS else "+"  # we capped the scan; show it's a floor
    named = ", ".join(uncovered[:_MAX_NAMED_MODULES])
    if len(uncovered) > _MAX_NAMED_MODULES:
        named += f" (+{len(uncovered) - _MAX_NAMED_MODULES} more)"
    msg = (
        f"[memorize-nudge] {n}{more} substantive commit(s) in the last 14d changed code that "
        f"NO memory note mentions: {state.sanitize_for_drift_line(named)} "
        f'(latest: "{latest}"). Capture what changed + WHY in the wiki — '
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
