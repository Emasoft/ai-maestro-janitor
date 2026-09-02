#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""gitignore-coverage detector — does the ignore file cover every private class? TRDD-6WM4BFKF.

PREVENTIVE, not remedial. The three adjacent detectors (`tracked-ignored`, `memory-scope-leak`,
`project-memory-tracked`) all start from the assumption that `.gitignore` is already correct.
This one asks the prior question, because on Claude Code TRACKED == SHIPPED == PUBLIC: a plugin
ships its whole tracked repo, so a missing pattern publishes private data to every installer.

Coverage is decided by `git check-ignore`, never by parsing `.gitignore` here — see
`lib/gitignore_coverage`. Fails OPEN: no repo, no git, or an unreadable index means silence, not
a false alarm.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import gitignore_coverage as gc  # noqa: E402
import state  # noqa: E402


def _git_verdicts(root: Path, paths: list[str]) -> dict[str, str]:
    """Git's own answer for every path, in ONE call: {path: "ignored" | "negated" | "unmatched"}.

    `git check-ignore -v -n -z --stdin` over all paths replaces one `-q` call per tracked file
    (~1,800 on this repo, hourly). `-v -n` is also what makes a NEGATION visible: `-q` answers
    "not ignored" both for a path no rule mentions and for one a `!` line deliberately
    re-includes, and those must diverge — the re-included path is tracked ON PURPOSE (this
    repo's `.trashcan/` markers, the `.claude/project/memory/**` block) and must never be an
    offender even when it sits inside a private class by name. `-z` output is NUL groups of
    four: source, line, pattern, path; an empty pattern means no rule at all. Exit 1 only says
    "nothing ignored" and is a valid answer. A missing verdict reads as "unmatched" — the LOUD
    direction for coverage (the class is reported uncovered), so a failed call is never a
    silent pass.
    """
    if not paths:
        return {}
    res = state.run_subprocess(
        ["git", "-C", str(root), "check-ignore", "-v", "-n", "-z", "--no-index", "--stdin"],
        timeout=30, detector_name="gitignore-coverage", input="\0".join(paths) + "\0",
    )
    if res is None or res.returncode not in (0, 1):
        return {}
    fields = res.stdout.split("\0")
    verdicts: dict[str, str] = {}
    for i in range(0, len(fields) - 3, 4):
        pattern, path = fields[i + 2], fields[i + 3]
        verdicts[path] = (
            "negated" if pattern.startswith("!") else "ignored" if pattern else "unmatched"
        )
    return verdicts


def main() -> int:
    root = state.project_root()
    if not (root / ".git").exists():
        return 0

    tracked_res = state.run_subprocess(
        ["git", "-C", str(root), "ls-files", "-z"], timeout=30, detector_name="gitignore-coverage",
    )
    tracked: list[str] = []
    if tracked_res is not None and tracked_res.returncode == 0:
        tracked = [p for p in tracked_res.stdout.split("\0") if p]

    verdicts = _git_verdicts(root, [c.probe for c in gc.PRIVATE_CLASSES] + tracked)

    def ignored(rel: str) -> bool:
        return verdicts.get(rel) == "ignored"

    def negated(rel: str) -> bool:
        return verdicts.get(rel) == "negated"

    uncovered = gc.uncovered_classes(ignored)
    offenders = gc.tracked_offenders(tracked, ignored, negated)

    if uncovered:
        names = ", ".join(f"{c.name} (add `{c.pattern}`)" for c in uncovered[:6])
        more = f" +{len(uncovered) - 6} more" if len(uncovered) > 6 else ""
        print(
            f"⟦gitignore-coverage⟧ {len(uncovered)} private class(es) NOT covered by .gitignore: "
            f"{names}{more} — on Claude Code a plugin ships its whole TRACKED tree, so the next "
            f"such file is published to every installer."
        )
    if offenders:
        # Deliberately separate: a rule does not untrack anything, so this needs `git rm --cached`
        # and NOT a working-tree delete. Saying so at the point of the finding is the whole value.
        # "present or not": an offender may be tracked with NO rule for it (matched by the class
        # table) — the case the coverage line's "next such file" wording would otherwise hide.
        shown = ", ".join(offenders[:5])
        more = f" +{len(offenders) - 5} more" if len(offenders) > 5 else ""
        print(
            f"⟦gitignore-coverage⟧ {len(offenders)} file(s) in a private class are still "
            f"TRACKED: {shown}{more} — a rule, present or not, does not untrack them; remedy "
            f"is `git rm --cached <path>` (never a working-tree delete)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
