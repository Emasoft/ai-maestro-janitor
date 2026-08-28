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
    memory_candidates_cli.py --intervention split-topic --scope LOCAL --root <memdir>

`split-topic` refuses at PAGE granularity on purpose, not per-atom: the ledger keys on paths, so
judging one atom on a page retires the WHOLE page from this list until the page changes again —
coarser than the atom it names, and it reuses the existing refusal ledger unchanged rather than
inventing a second, atom-granular keying scheme.

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
            # NAME it (review 2026-08-08): the scheduler fails OPEN on an unreadable page
            # and dispatches — a CLI that silently skips the same page hands the agent an
            # empty list with nothing to record a refusal on, recreating the #227 loop.
            # The SSOT guarantee is exactly this line: what makes the scheduler dispatch
            # must appear in the list. No refusal filter — an unreadable page cannot be
            # content-hashed, so it is always named until a human unbreaks or removes it.
            out.append((_rel(root, p), "unreadable-page"))
            continue
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
            out.append((_rel(root, p), "unreadable-page"))  # see repair_candidates — SSOT
            continue
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

    Refusal coverage is PAIR-granular, via the same
    `memory_content_precheck.group_has_unjudged_pair` rule the scheduler gate uses
    (review 2026-08-08): the merge-protocol records an abstain keyed on the judged
    PAIR, so a group is dropped only when EVERY pair within it is covered by a live
    refusal — which is exactly when no judgment work remains. The previous exact-set
    check never matched a pair-keyed refusal, so 3+-member groups re-listed forever."""
    by_key = memory_content_precheck._group_candidates_by_tier_type(root)
    if by_key is None:
        # The grouping helper cannot say WHICH page broke it, but the scheduler fails
        # OPEN on this same condition and dispatches — so the agent must get a NAME
        # (review 2026-08-08). Find and emit the unreadable page(s) directly.
        out = []
        for p in memory_content_precheck._candidate_pages(root):
            try:
                p.read_text(encoding="utf-8")
            except OSError:
                out.append((_rel(root, p), "unreadable-page"))
        return out
    out = []
    for pages in by_key.values():
        reason = memory_content_precheck.consolidate_group_defect(pages, max_bytes=max_bytes)
        if not reason:
            continue
        if not memory_content_precheck.group_has_unjudged_pair(root, scope, pages, now=now):
            continue
        rels = sorted(_rel(root, p) for p in pages)
        out.append((",".join(rels), reason))
    return out


def enrich_candidates(
    root: Path, *, scope: str, now: int | None, max_bytes: int
) -> list[tuple[str, str]]:
    """Every page `memgrep lint` flags with a thin/duplicated recall surface, MINUS pages
    the refusal ledger already covers — the same set `enrich_has_work` collapses to a bool.

    Unlike its siblings this one does NOT walk pages and apply a text predicate: the
    defect is a LINT RULE, so the candidate list comes from the linter in one subprocess
    (see `enrich_pages`). That is what keeps the scheduler's gate and this list identical
    — the SSOT guarantee the other candidate functions get from sharing `*_defect`.

    Consequence worth naming: when memgrep is missing this returns EMPTY, not
    everything. The scheduler's gate fails CLOSED here too, so the two still agree — an
    empty list from a missing linter is the honest answer, and the loud problem (no
    memgrep) surfaces elsewhere.

    One page can carry several findings; they are merged into ONE row per page with the
    slugs joined, because the agent fixes a page, not a finding.
    """
    by_page: dict[str, list[str]] = {}
    for path, slug in memory_content_precheck.enrich_pages(root):
        by_page.setdefault(path, [])
        if slug not in by_page[path]:
            by_page[path].append(slug)
    out: list[tuple[str, str]] = []
    for path, slugs in by_page.items():
        p = Path(path)
        if memory_refusals.is_refused("enrich", scope, root, [p], now=now):
            continue
        out.append((_rel(root, p), "+".join(sorted(slugs))))
    return sorted(out)


def split_topic_candidates(
    root: Path, *, scope: str, now: int | None, max_bytes: int
) -> list[tuple[str, str]]:
    """`(page#atom, "multi-topic")` for every plausibly-multi-topic atom
    (`memory_content_precheck.multi_topic_atom_candidates`), MINUS pages a live
    `split-topic` refusal already covers.

    Refusal coverage is PAGE-granular, not atom-granular: the ledger keys on paths, so a
    refusal recorded on the page retires every one of its atoms from this list until the
    page's bytes change — reusing the existing per-candidate ledger unchanged rather than
    inventing a second, atom-granular keying scheme."""
    out: list[tuple[str, str]] = []
    for rel, atom_id in memory_content_precheck.multi_topic_atom_candidates(root):
        p = root / rel
        if memory_refusals.is_refused("split-topic", scope, root, [p], now=now):
            continue
        out.append((f"{rel}#{atom_id}", "multi-topic"))
    return out


_INTERVENTIONS = {
    "repair": repair_candidates,
    "atomize": atomize_candidates,
    "consolidate": consolidate_candidates,
    "enrich": enrich_candidates,
    "split-topic": split_topic_candidates,
}


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_candidates_cli")
    ap.add_argument("--intervention", required=True, choices=sorted(_INTERVENTIONS))
    ap.add_argument("--scope", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument(
        "--max-bytes", type=int, default=None,
        help="the split-cap size gate (consolidate gate 4, #210). Omit to resolve the "
        "SAME `split_max_bytes` setting the scheduler dispatched under — passing a "
        "guessed value here reopens the scheduler-vs-CLI divergence this tool exists "
        "to close. 0 = size check explicitly skipped.",
    )
    args = ap.parse_args()
    if args.max_bytes is None:
        # Resolve from the shared knob (review 2026-08-08): the SKILL used to say
        # `--max-bytes <split_max_bytes>` with no way to resolve the placeholder, so an
        # agent could run the CLI under a different cap than the scheduler's gate used.
        try:
            import memory_settings  # noqa: PLC0415

            args.max_bytes = int(memory_settings.get("split_max_bytes") or 0)
        except Exception:  # noqa: BLE001 - unresolvable knob → size check skipped (fail-open)
            args.max_bytes = 0

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
