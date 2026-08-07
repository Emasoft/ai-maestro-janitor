#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""List the pages an editorial chore should actually work — the janitor#227 fix.

The SCHEDULER (`memory_content_precheck.py`) and the janitor-memory-repair SKILL used
to have TWO independent definitions of "this page needs repair": the scheduler's
structural precheck, and `memgrep lint`. They disagreed — a page the precheck flagged
could return zero `memgrep lint` findings — so the agent, told to find candidates via
lint, found nothing to work, could not record a refusal, and the chore re-dispatched a
~200-280k-token agent forever (issue #227).

This CLI is the fix: it prints EXACTLY the pages `memory_content_precheck` considers
candidates, using the SAME predicate the scheduler's due-ness gate calls
(`memory_content_precheck.repair_defect`), honouring the refusal ledger exactly as the
precheck does. The skill consumes this instead of re-deriving candidacy from lint.

    memory_candidates_cli.py --intervention repair --scope LOCAL --root <memdir>

Prints one TAB-separated line per candidate: `<page-relative-path>\\t<reason-slug>`.
Empty output (exit 0) means no candidates. Read-only — it names candidates, it never
edits or records refusals itself.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_content_precheck  # noqa: E402
import memory_refusals  # noqa: E402


def repair_candidates(root: Path, *, scope: str, now: int | None) -> list[tuple[Path, str]]:
    """Every page `memory_content_precheck.repair_defect` flags, MINUS pages the
    refusal ledger already covers — the exact set the scheduler's `repair_has_work`
    treats as "there is work", named individually instead of collapsed to a bool."""
    out: list[tuple[Path, str]] = []
    for p in memory_content_precheck._candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue  # unreadable — the precheck fails OPEN (dispatches); nothing to name here
        reason = memory_content_precheck.repair_defect(text)
        if not reason:
            continue
        if memory_refusals.is_refused("repair", scope, root, [p], now=now):
            continue
        out.append((p, reason))
    return out


_INTERVENTIONS = {"repair": repair_candidates}


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_candidates_cli")
    ap.add_argument("--intervention", required=True, choices=sorted(_INTERVENTIONS))
    ap.add_argument("--scope", required=True)
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    fn = _INTERVENTIONS.get(args.intervention)
    if fn is None:
        print(f"REFUSED: unsupported --intervention {args.intervention!r}", file=sys.stderr)
        return 2

    root = Path(args.root).expanduser()
    now = int(time.time())
    for path, reason in fn(root, scope=args.scope, now=now):
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        print(f"{rel}\t{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
