#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""design-tracked — keep the PROJECT `design/` folder git-tracked (TRDD-58Q791FL).

`design/` is the project's kanban, requirements and specs: PROJECT scope, shared with every
contributor, and it must never be gitignored. Real incident: a `/design/` line in
`.git/info/exclude` (a per-clone file no `.gitignore` review ever sees) hid 467 cards from git,
so none of them was ever committed.

This is a FIXING detector. It asks git (`check-ignore -v -n --no-index`, never a hand parse)
whether four representative design paths are ignored and, if so:

  * the culprit is a line of `.git/info/exclude` that names `design` literally → that one line
    is deleted, every other byte of the file kept;
  * any other culprit but a nested `.gitignore` → `!/design/` + `!/design/**` are appended to the
    root `.gitignore` (root negations beat info/exclude and the global excludes file);
  * a nested `.gitignore` (or autofix off) → warn only; never edited from here.

It then re-probes and prints ONE line: fixed, or STILL HIDDEN. Separately, design cards that sit
untracked for over 24 h get one line per day. Silent when design/ does not exist and nothing is
tracked there, and when git cannot answer. LOCAL `.claude/local/design/` is out of scope.
Always exits 0.
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

_NAME = "design-tracked"
_PROBES = ("design/x.md", "design/tasks/x.md", "design/proposals/x.md", "design/archived/x.md")
_NEGATIONS = ("!/design/", "!/design/**")
_UNTRACKED_AGE_S = 24 * 3600
_NOISE_SUFFIXES = (".swp", ".swo", ".swx", "~")


def _git(root: Path, *args: str, stdin: str | None = None) -> str | None:
    res = state.run_subprocess(
        ["git", "-C", str(root), *args], timeout=30, detector_name=_NAME, input=stdin,
    )
    if res is None or res.returncode not in (0, 1):
        return None
    return res.stdout


def _first_ignored(root: Path) -> tuple[str, int, str] | None:
    """(source, line, pattern) of the first ignored probe; None when all are clear or git cannot answer."""
    out = _git(root, "check-ignore", "-v", "-n", "-z", "--no-index", "--stdin",
               stdin="\0".join(_PROBES) + "\0")
    if out is None:
        return None
    f = out.split("\0")
    for i in range(0, len(f) - 3, 4):
        source, line, pattern = f[i], f[i + 1], f[i + 2]
        if pattern and not pattern.startswith("!"):
            return (source, int(line) if line.isdigit() else 0, pattern)
    return None


def _same_file(root: Path, a: str, b: Path) -> bool:
    p = Path(a)
    return (p if p.is_absolute() else root / p).resolve() == b.resolve()


def _drop_exclude_line(exclude: Path, line_no: int, pattern: str) -> bool:
    """Delete exactly line `line_no` when it is `pattern`; every other byte is kept."""
    try:
        lines = exclude.read_bytes().splitlines(keepends=True)
        if not 1 <= line_no <= len(lines) or lines[line_no - 1].decode().strip() != pattern:
            return False
        del lines[line_no - 1]
        exclude.write_bytes(b"".join(lines))
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _append_negations(root: Path) -> bool:
    gi = root / ".gitignore"
    try:
        text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
        have = set(text.splitlines())
        missing = [n for n in _NEGATIONS if n not in have]
        if missing:
            sep = "" if not text or text.endswith("\n") else "\n"
            with gi.open("a", encoding="utf-8") as fh:
                fh.write(sep + "".join(m + "\n" for m in missing))
    except OSError as exc:
        state.log_line(_NAME, f"could not update .gitignore: {exc}")
        return False
    return True


def _enforce_tracked(root: Path, seen: Path) -> None:
    hit = _first_ignored(root)
    if hit is None:
        return
    removed: list[str] = []
    common = _git(root, "rev-parse", "--git-common-dir")
    exclude = (root / common.strip() / "info" / "exclude") if common else None
    autofix = state.autofix_enabled()
    for _ in range(4):  # a second `design` line may hide behind the first
        source, line_no, pattern = hit
        if not autofix:
            break
        if (exclude is not None and _same_file(root, source, exclude)
                and pattern.strip("/") == "design"):
            if not _drop_exclude_line(exclude, line_no, pattern):
                break
            removed.append(f"{source}:{line_no}:{pattern}")
        elif Path(source).name == ".gitignore" and not _same_file(root, source, root / ".gitignore"):
            break  # nested .gitignore: never edited from here
        else:
            if not _append_negations(root):
                break
            removed.append(f"{source}:{line_no}:{pattern} overridden by root .gitignore negations")
        hit = _first_ignored(root)
        if hit is None:
            break
    if hit is None:
        if removed:
            fixed = "; ".join(removed)
            msg = (f"[{_NAME}] design/ was gitignored and is fixed — {fixed}. "
                   "design/ is PROJECT scope and must never be gitignored; commit your cards by name.")
            line = dedupe.emit_once(seen, "fixed:" + "|".join(removed), msg)
            if line:
                print(line)
        return
    source, line_no, pattern = hit
    why = "" if autofix else " (autofix is off, nothing was edited)"
    msg = (f"[{_NAME}] design/ is STILL HIDDEN from git by {source}:{line_no} `{pattern}`{why} — "
           "a PROJECT design/ must never be gitignored. Remove that rule yourself, or add "
           "`!/design/` and `!/design/**` to the root .gitignore.")
    line = dedupe.emit_once(seen, f"hidden:{source}:{line_no}:{pattern}:{autofix}", msg)
    if line:
        print(line)


def _warn_untracked(root: Path, seen: Path) -> None:
    out = _git(root, "ls-files", "-z", "--others", "--exclude-standard", "design")
    if not out:
        return
    cutoff = time.time() - _UNTRACKED_AGE_S
    old: list[str] = []
    for rel in (p for p in out.split("\0") if p):
        name = Path(rel).name
        if name == ".DS_Store" or name.startswith(".#") or name.endswith(_NOISE_SUFFIXES):
            continue
        try:
            if (root / rel).stat().st_mtime < cutoff:
                old.append(name)
        except OSError:
            continue
    if not old:
        return
    line = dedupe.emit_once(
        seen, f"untracked:{date.today().isoformat()}",
        f"[{_NAME}] {len(old)} design card(s) untracked for over 24 h: {', '.join(sorted(old)[:5])}"
        f"{' …' if len(old) > 5 else ''} — design/ is PROJECT scope: `git add` them by name and commit.",
    )
    if line:
        print(line)


def main() -> int:
    state.init_state()
    root = state.project_root()
    if not (root / ".git").exists():
        return 0
    tracked = _git(root, "ls-files", "design")
    if not (root / "design").is_dir() and not (tracked and tracked.strip()):
        return 0
    seen = state.state_dir() / f"{_NAME}-seen.txt"
    _enforce_tracked(root, seen)
    _warn_untracked(root, seen)
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
