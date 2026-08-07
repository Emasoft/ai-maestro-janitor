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

This CLI is the fix: it prints EXACTLY the candidates `memory_content_precheck`
considers due, using the SAME predicates the scheduler's due-ness gates call
(`repair_defect` / `atomize_defect` / `consolidate_group_defect`), honouring the
refusal ledger exactly as the precheck does. The repair/atomize/consolidate skills
consume this instead of re-deriving candidacy from `memgrep lint` or their own scan.

    memory_candidates_cli.py --intervention repair --scope LOCAL --root <memdir>
    memory_candidates_cli.py --intervention atomize --scope LOCAL --root <memdir>
    memory_candidates_cli.py --intervention consolidate --scope LOCAL --root <memdir> --max-bytes 40000

Prints one TAB-separated line per candidate: `<page-relative-path>\\t<reason-slug>`.
For `consolidate` the candidate unit is a GROUP, not one page (a merge needs a PAIR to
even consider) — the page column carries the group's pages COMMA-JOINED, e.g.
`a.md,b.md,c.md\\tsame-tier-type`. Empty output (exit 0) means no candidates.
Read-only — it names candidates, it never edits or records refusals itself.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_content_precheck  # noqa: E402
import memory_refusals  # noqa: E402


def _rel(root: Path, path: Path) -> str:
    """`path` printed relative to `root` when possible (matches the precheck's own paths)."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def repair_candidates(
    root: Path, *, scope: str, now: int | None, max_bytes: int
) -> list[tuple[str, str]]:
    """Every page `memory_content_precheck.repair_defect` flags, MINUS pages the
    refusal ledger already covers — the exact set the scheduler's `repair_has_work`
    treats as "there is work", named individually instead of collapsed to a bool."""
    out: list[tuple[str, str]] = []
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
        out.append((_rel(root, p), reason))
    return out


def atomize_candidates(
    root: Path, *, scope: str, now: int | None, max_bytes: int
) -> list[tuple[str, str]]:
    """Every page `memory_content_precheck.atomize_defect` flags, MINUS pages the
    refusal ledger already covers — mirrors `repair_candidates` exactly (janitor#227
    follow-up: the atomize skill used to re-derive candidacy from `memgrep -l`, which
    could disagree with `atomize_has_work`)."""
    out: list[tuple[str, str]] = []
    for p in memory_content_precheck._candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue  # unreadable — the precheck fails OPEN (dispatches); nothing to name here
        reason = memory_content_precheck.atomize_defect(text)
        if not reason:
            continue
        if memory_refusals.is_refused("atomize", scope, root, [p], now=now):
            continue
        out.append((_rel(root, p), reason))
    return out


def consolidate_candidates(
    root: Path, *, scope: str, now: int | None, max_bytes: int
) -> list[tuple[str, str]]:
    """Every `(tier, type)` GROUP `memory_content_precheck.consolidate_group_defect`
    flags, MINUS groups the refusal ledger already covers whole — the exact set
    `consolidate_has_work` treats as "there is work" (its gate 1 + gate 4), named as
    groups instead of collapsed to a bool.

    A merge fuses exactly TWO pages (see the janitor-memory-consolidate skill's
    default-abstain posture), so a group with more than 2 members still names ALL its
    members — the skill picks the actual pair from among them; narrowing that choice
    is the skill's own semantic judgment (same subject?), not this CLI's.

    Refusal coverage is checked against the group's OWN member set (`candidate_key`
    is keyed on the exact sorted page list) — a refusal recorded on a DIFFERENT subset
    of the same group does not match here and the group stays a candidate (fail-open,
    matching every other predicate in this module)."""
    by_key = memory_content_precheck._group_candidates_by_tier_type(root)
    if by_key is None:
        return []  # unreadable — the precheck fails OPEN (dispatches); nothing to name here
    out: list[tuple[str, str]] = []
    for pages in by_key.values():
        reason = memory_content_precheck.consolidate_group_defect(pages, max_bytes=max_bytes)
        if not reason:
            continue
        if memory_refusals.is_refused("consolidate", scope, root, pages, now=now):
            continue
        rels = sorted(_rel(root, p) for p in pages)
        out.append((",".join(rels), reason))
    return out


_INTERVENTIONS = {
    "repair": repair_candidates,
    "atomize": atomize_candidates,
    "consolidate": consolidate_candidates,
}


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_candidates_cli")
    ap.add_argument("--intervention", required=True, choices=sorted(_INTERVENTIONS))
    ap.add_argument("--scope", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument(
        "--max-bytes", type=int, default=0,
        help="the split-cap size gate (consolidate gate 4, #210); 0 = size check skipped",
    )
    args = ap.parse_args()

    fn = _INTERVENTIONS.get(args.intervention)
    if fn is None:
        print(f"REFUSED: unsupported --intervention {args.intervention!r}", file=sys.stderr)
        return 2

    root = Path(args.root).expanduser()
    now = int(time.time())
    for page_field, reason in fn(root, scope=args.scope, now=now, max_bytes=args.max_bytes):
        print(f"{page_field}\t{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
