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


def _probe_ignored(root: Path) -> "object":
    """Return a callable answering git's own 'would you ignore this path?'.

    `git check-ignore -q` exits 0 when the path IS ignored, 1 when it is not. Any other exit
    (or a timeout, which `run_subprocess` reports as None) is treated as NOT ignored, which is
    the loud direction: a coverage detector that goes quiet when it cannot ask is useless.
    """
    def ask(rel: str) -> bool:
        res = state.run_subprocess(
            ["git", "-C", str(root), "check-ignore", "-q", "--no-index", rel],
            timeout=10, detector_name="gitignore-coverage",
        )
        return bool(res is not None and res.returncode == 0)

    return ask


def main() -> int:
    root = state.project_root()
    if not (root / ".git").exists():
        return 0

    ask = _probe_ignored(root)
    uncovered = gc.uncovered_classes(ask)  # type: ignore[arg-type]

    tracked_res = state.run_subprocess(
        ["git", "-C", str(root), "ls-files"], timeout=30, detector_name="gitignore-coverage",
    )
    offenders: list[str] = []
    if tracked_res is not None and tracked_res.returncode == 0:
        offenders = gc.tracked_offenders(
            (ln for ln in tracked_res.stdout.splitlines() if ln.strip()), ask,  # type: ignore[arg-type]
        )

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
        shown = ", ".join(offenders[:5])
        more = f" +{len(offenders) - 5} more" if len(offenders) > 5 else ""
        print(
            f"⟦gitignore-coverage⟧ {len(offenders)} file(s) are ignored by a rule yet still "
            f"TRACKED: {shown}{more} — adding the rule did not untrack them; remedy is "
            f"`git rm --cached <path>` (never a working-tree delete)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
