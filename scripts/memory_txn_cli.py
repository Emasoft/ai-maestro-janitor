#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing CLI for ONE atomic wikimem memory edit (TRDD-b92a9dd0, TRDD-A foundation).

A skill-agent uses this to run a single merge / split through the crash-safe,
hash-guarded, flock-serialized transaction core (`memory_txn.py`) with the
content-loss verifier (`memory_edit_verify.py`) as the commit gate. The agent
never mutates a live page directly; it edits COPIES inside a staging dir.

The contract is two-phase so the agent can do its semantic work between them:

  begin <scope_root> <op> [<source_rel>...]
      Snapshot + copy each source page into a fresh staging dir. Prints
      `txn_id=<id>` and `staging=<abs dir>`. The agent then edits INSIDE staging:
        - overwrite a copied source .md  → a WRITE (changed page)
        - add a brand-new .md            → a WRITE (new page)
        - delete a copied source .md     → a DELETE (page removed)

  commit <scope_root> <txn_id> --op <merge|split|repair|atomize>
      RECONSTRUCT the write/delete set by DIFFING staging vs the recorded sources
      (a new or content-changed staged file → stage_write; a recorded source whose
      staged copy was removed → stage_delete), run verify_merge / verify_split, and
      on PASS apply atomically via the txn. On verify FAIL print the reasons and
      exit non-zero (the txn is aborted; the live tree is left untouched).

  abort <scope_root> <txn_id>       Discard a not-yet-committed transaction.
  resume <scope_root>               Roll forward / clean interrupted transactions.

Staleness / keepalive (M-9): a staging-phase txn whose JOURNAL file goes
untouched for 6 h is discarded by any later `resume` as a crashed pass. The
window is journal-MTIME-based, so a long pass (rate-limit stall, slow model)
keeps its txn alive simply by touching the journal —
`touch <scope_root>/.maint-staging/<txn_id>.json` — between begin and commit.

Fail-fast: every error exits non-zero with a one-line `error:` message; a clean
commit / abort / resume exits 0.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_bridge  # noqa: E402
import memory_edit_verify as verify  # noqa: E402
import memory_scopes  # noqa: E402
import memory_txn  # noqa: E402
from memory_txn import MemoryTxn, MemoryTxnError  # noqa: E402


def _slug_of(rel_path: str, text: str) -> str:
    """The wiki slug a page retires under: its frontmatter `name`, else the file
    stem (the wikimem model: `name == filename stem`)."""
    name = verify.parse_frontmatter(text).get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return Path(rel_path).stem


def _staged_md_paths(staging_dir: Path) -> list[str]:
    """Every `.md` rel-path currently in the staging tree (the journal file lives
    one level UP, in the staging ROOT, so it is never enumerated here)."""
    return sorted(
        str(p.relative_to(staging_dir))
        for p in staging_dir.rglob("*.md")
        if p.is_file()
    )


def _reconstruct_changes(txn: MemoryTxn) -> tuple[dict[str, str], list[str]]:
    """Diff the staging tree against the recorded sources to recover the agent's
    intent. Returns ({rel -> new content} writes, [rel] deletes).

    - A staged .md that is NOT a recorded source → a NEW page → write.
    - A staged .md that IS a recorded source but whose content differs from the
      live (begin-time) source → an overwrite → write.
    - A recorded source whose staged copy was removed by the agent → a delete.
    An unchanged staged source is neither (the agent left it alone)."""
    sources = set(txn.sources)
    staged = set(_staged_md_paths(txn.staging_dir))

    writes: dict[str, str] = {}
    for rel in sorted(staged):
        staged_text = (txn.staging_dir / rel).read_text(encoding="utf-8")
        if rel not in sources:
            writes[rel] = staged_text                     # brand-new page
            continue
        live = txn.scope_root / rel
        live_text = live.read_text(encoding="utf-8") if live.exists() else None
        if staged_text != live_text:
            writes[rel] = staged_text                     # overwritten source

    deletes = sorted(rel for rel in sources if rel not in staged)
    return writes, deletes


def _live_pages_excluding(scope_root: Path, exclude: set[str]) -> dict[str, str]:
    """Every live `.md` page in the scope keyed by rel-path, minus `exclude` (the
    pages the txn writes or deletes). Used as the OTHER-pages set for the
    dangling-link (LINK-LAW) check so a missed backlink redirect anywhere in the
    corpus is caught, not just inside the edited pages."""
    # M-3 (wikimem audit 2026-07-07): route through the SSOT note scan, never a
    # private rglob. The local walk read the PRIVATE user-mem/ store into the
    # verifier (its rel paths could leak into agent-visible failure reasons) and
    # let non-notes (MEMORY.md stub, index docs, detector reports) false-fail
    # the LINK-LAW check via their stale [[links]].
    out: dict[str, str] = {}
    for p in memory_scopes.iter_note_files(scope_root):
        rel = str(p.relative_to(scope_root))
        if rel in exclude:
            continue
        out[rel] = p.read_text(encoding="utf-8")
    return out


# The four memgrep-lint authoring classes this gate reasons about, keyed to a stable message
# substring of the Rust check (TRDD-DOJ2LE1G). Only the first three BLOCK (near-zero pre-existing
# in the corpus + unambiguous defects); `oversized` only WARNS (a judgment call, 36 pre-existing).
_AUTHORING_CLASSES = {
    "unquoted-desc": "unquoted prose",
    "empty-lesson-body": "but no body",
    "superseded-without-body": "SUPERSEDED BODY",
    "oversized-atom": "decompose it into",
}
_AUTHORING_BLOCKING = ("unquoted-desc", "empty-lesson-body", "superseded-without-body")


def _authoring_class_counts(memgrep: str, texts: dict[str, str]) -> dict[str, int] | None:
    """Total occurrences of each authoring class across `texts`, via one `memgrep lint` over a temp
    dir. Counts are ORDER-INDEPENDENT (we compare totals, never per-file), so flat filenames are
    fine; other lint noise (link-law, required-field) is ignored by the substring filter. Returns
    None on any infra failure (→ the caller fails OPEN)."""
    counts = {name: 0 for name in _AUTHORING_CLASSES}
    if not texts:
        return counts
    try:
        with tempfile.TemporaryDirectory() as td:
            for i, text in enumerate(texts.values()):
                (Path(td) / f"p{i}.md").write_text(text, encoding="utf-8")
            out = subprocess.run(
                [memgrep, "lint", td], capture_output=True, text=True, timeout=30
            ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        for name, needle in _AUTHORING_CLASSES.items():
            if needle in line:
                counts[name] += 1
                break
    return counts


def _authoring_gate(txn: MemoryTxn, writes: dict[str, str]) -> tuple[bool, list[str], list[str]]:
    """DELTA authoring-integrity gate (TRDD-4ZTNMQL3): refuse a commit that INTRODUCES a malformed
    atom/lesson. Compares each authoring class's count on the BEFORE (live) vs AFTER (staged) texts
    and blocks the three unambiguous classes when the count INCREASES (a DELTA, so a page's
    pre-existing violation never blocks an unrelated edit); `oversized-atom` only warns. Fail-OPEN:
    no memgrep / any error skips the gate — it must never break a valid commit."""
    memgrep = shutil.which("memgrep")
    if not memgrep or not writes:
        return True, [], []
    before = {
        rel: (txn.scope_root / rel).read_text(encoding="utf-8")
        if (txn.scope_root / rel).exists()
        else ""
        for rel in writes
    }
    b = _authoring_class_counts(memgrep, before)
    a = _authoring_class_counts(memgrep, writes)
    if b is None or a is None:
        return True, [], []  # fail-open on any lint-infra problem
    reasons, warnings = [], []
    for name in _AUTHORING_BLOCKING:
        if a[name] > b[name]:
            reasons.append(
                f"{name}: this edit introduces {a[name] - b[name]} new occurrence(s) — "
                f"fix them (run `memgrep lint`) before committing"
            )
    if a["oversized-atom"] > b["oversized-atom"]:
        warnings.append(
            f"oversized-atom: {a['oversized-atom'] - b['oversized-atom']} new atom(s) exceed the "
            f"size budget — consider decomposing (non-blocking)"
        )
    return (not reasons), reasons, warnings


def _load_txn(scope_root: Path, txn_id: str) -> MemoryTxn:
    """Reconstruct a transaction from its on-disk journal (begin and commit run in
    SEPARATE processes — the journal IS the cross-process handoff)."""
    journal = MemoryTxn._staging_root(scope_root) / f"{txn_id}.json"
    if not journal.exists():
        raise MemoryTxnError(f"no transaction {txn_id} under {scope_root}")
    return MemoryTxn._load(journal)


def _verify_merge(txn, writes, deletes):
    """Build verify_merge inputs from the reconstructed change set. Sources are
    ALL of the txn's declared source pages — including a SURVIVOR the merge
    overwrites in place — read at begin-time content from the live tree (pre-
    commit the live tree IS begin-time content; commit's re-hash enforces it).
    H-1 (wikimem audit 2026-07-07): building sources from `deletes` alone let the
    merge-into-survivor shape (write a.md + delete b.md) drop the survivor's own
    lessons/facts unseen, and made ocd_lmd_ok_merge reward adopting the deleted
    page's YOUNGER ocd. `retired` stays deletes-only (only removed slugs retire).
    The union guards the degenerate case of a delete the agent forgot to declare
    as a source."""
    source_texts, source_metas, retired, surviving_texts = [], [], [], []
    delete_set = set(deletes)
    for rel in sorted(set(txn.sources) | delete_set):
        live = txn.scope_root / rel
        text = live.read_text(encoding="utf-8")
        source_texts.append(text)
        source_metas.append(verify.parse_frontmatter(text))
        if rel in delete_set:
            retired.append(_slug_of(rel, text))
        else:
            surviving_texts.append(text)

    # M-2 (wikimem audit 2026-07-07): structural legality is machine-checkable
    # from the metas already in hand, so enforce it AT COMMIT TIME — the
    # consolidate skill's pre-flight is convention, not enforcement, and a
    # confused agent could otherwise commit a cross-tier/cross-type merge.
    # EXEMPT the CONFLICT pass (journal op == "conflict", recorded at begin):
    # its loss-preserving pair-retirement is sanctioned "regardless of the
    # pair's tiers" (conflict-protocol.md) — a conflict pair contradicts about
    # ONE subject and the demoted fact survives as a lesson on the survivor,
    # so is_legal_merge's tier/type screen deliberately does not apply there.
    # Pairwise against the first meta suffices: legality is equality-based
    # (same mergeable tier, same type), hence transitive.
    if txn.op != "conflict":
        for i, meta in enumerate(source_metas[1:], start=2):
            legal, why = verify.is_legal_merge(source_metas[0], meta)
            if not legal:
                return False, [f"illegal merge (source #{i} vs #1): {why}"]

    if len(writes) != 1:
        # janitor#145: the one-write rule is deliberate, not a limitation to route
        # around — verify_merge proves knowledge preservation between the SOURCES
        # and the SURVIVOR only, so admitting an extra (e.g. backlink-holder) write
        # would let an UNVERIFIED edit ride inside a verified transaction. A
        # holder must be repointed in its OWN prior `--op repair` transaction
        # first (verify_merge's no_dangling_refs then refuses the merge until
        # that lands, so holder-first is the only order that can commit at all).
        # The guidance is spelled out HERE, in the refusal itself, rather than
        # left to a reference doc: a prose doc can drift out of sync with this
        # check (it did — janitor#145), but an error message cannot drift from
        # the code that raises it.
        raise MemoryTxnError(
            f"merge expects exactly ONE surviving page, found {len(writes)} write(s) — "
            "a backlink holder cannot ride along in this transaction; repoint it in "
            "a separate 'commit --op repair' transaction FIRST, then retry the merge "
            "with only the merge sources staged"
        )
    result_rel, result_text = next(iter(writes.items()))
    result_meta = verify.parse_frontmatter(result_text)

    touched = set(writes) | set(deletes)
    others = _live_pages_excluding(txn.scope_root, touched)

    # F2 (audit 2026-07-13): a CONFLICT resolution SUPERSEDES the retired page's claim
    # by construction — conflict-protocol Stage 4 makes the survivor's body the CURRENT
    # truth and reWORDS the obsolete claim into a `[^N]` lesson. Demanding that claim
    # still be a substring of the survivor's body therefore refused EVERY conflict
    # verdict (both DEMOTE and DELETE ride --op merge), so the pass burned its whole
    # adversarial fan-out each cadence and threw the result away at the gate. Narrow the
    # body-fact oracle to the SURVIVING sources: the survivor's own body stays sacred
    # (it is the page a conflict rewrites), while the retired page's superseded facts may
    # be demoted. lessons_preserved still guards every source's lessons, strictly.
    fact_sources = surviving_texts if txn.op == "conflict" else None

    # janitor#182 — the SECOND index. `verify_merge`'s `memory_md_text` is opt-in
    # (a caller that never supplies it asserts nothing about MEMORY.md), and this
    # call site never did — so a merge that forgot the mandated MEMORY.md redirect
    # (merge-protocol.md "THE SECOND INDEX") committed clean while leaving the
    # harness index pointing at a page this merge just deleted. Read the LIVE file
    # (not `writes`: under the one-write merge contract, a MEMORY.md redirect runs
    # as its own PRIOR `--op repair` transaction, exactly like any other backlink
    # holder — so by the time THIS txn commits, the correctly-redirected content is
    # already on disk, or the agent forgot and this check is what catches it).
    memory_md_path = txn.scope_root / memory_bridge.MEMORY_MD
    memory_md_text = (
        memory_md_path.read_text(encoding="utf-8") if memory_md_path.exists() else None
    )

    ok, reasons = verify.verify_merge(
        source_texts, source_metas, result_text, result_meta, retired, others,
        fact_source_texts=fact_sources, memory_md_text=memory_md_text,
    )
    return ok, reasons


def _verify_split(txn, writes, deletes, unsplittable=None):
    """Build verify_split inputs. The split has ONE source page; outputs are an
    overview (the write at the source's path, else the one carrying the source's
    slug as `<stem>-overview`) + sub-pages. `unsplittable` (L-8) = rel-paths the
    caller flags as over-cap atomic leaves (the CLI's --unsplittable)."""
    if len(txn.sources) != 1:
        raise MemoryTxnError(
            f"split expects exactly ONE source page, found {len(txn.sources)}"
        )
    source_rel = next(iter(txn.sources))
    # The source's ORIGINAL content is its begin-time live copy — still present in
    # the live tree (the txn has not committed) — NOT the (possibly edited) staged
    # copy. Lesson preservation must compare the sub-pages against the ORIGINAL.
    source_text = (txn.scope_root / source_rel).read_text(encoding="utf-8")
    source_meta = verify.parse_frontmatter(source_text)

    max_bytes = _split_max_bytes()
    # M-2 (wikimem audit 2026-07-07): enforce split legality at commit time,
    # mirroring the merge-side gate — a component is ONE element ("one element =
    # one page") and is never fragmented, and a seamless (<2-section) hub/aspect
    # splits only when oversized (seam synthesis). The split skill's own check is
    # convention; this is the enforcement.
    oversized = len(source_text.encode("utf-8")) > max_bytes
    legal, why = verify.is_legal_split(source_meta, source_text, oversized=oversized)
    if not legal:
        return False, [f"illegal split: {why}"]

    if not writes:
        raise MemoryTxnError("split produced no output pages")
    if source_rel in writes:
        overview_rel = source_rel
    else:
        # L-9 (wikimem audit 2026-07-07): when the split RETIRES the source slug,
        # sorted(writes)[0] could crown an alphabetically-first SUB-PAGE as the
        # overview — for a hub that guarantees a bogus "globs overlap" rejection
        # with a misleading reason. The overview is the write that carries the
        # source's slug forward; anything else is ambiguous and must be refused.
        src_stem = Path(source_rel).stem
        cands = [r for r in writes if Path(r).stem in (f"{src_stem}-overview", src_stem)]
        if len(cands) != 1:
            raise MemoryTxnError(
                "cannot identify the overview page: keep the source's path, or write "
                f"exactly one '{src_stem}-overview.md'; got {sorted(writes)}"
            )
        overview_rel = cands[0]
    overview_text = writes[overview_rel]
    subpages = {rel: txt for rel, txt in writes.items() if rel != overview_rel}
    subpage_texts = [subpages[r] for r in sorted(subpages)]
    subpage_metas = [verify.parse_frontmatter(t) for t in subpage_texts]

    page_sizes = {rel: len(txt.encode("utf-8")) for rel, txt in writes.items()}

    retired = [
        _slug_of(rel, (txn.scope_root / rel).read_text(encoding="utf-8"))
        for rel in deletes
    ]
    touched = set(writes) | set(deletes)
    others = _live_pages_excluding(txn.scope_root, touched)
    ok, reasons = verify.verify_split(
        source_text, source_meta, subpage_texts, subpage_metas, overview_text,
        page_sizes, max_bytes, unsplittable=set(unsplittable or ()), retired_slugs=retired,
        other_live_pages=others,
    )
    return ok, reasons


def _verify_repair(txn, writes, deletes):
    """Build verify_repair inputs. Repair edits ONE page IN PLACE: exactly one write
    at the source's path, ZERO deletes — a merge/split-shaped change set is a bug,
    not a repair, so reject it before verify even runs (TRDD-87935f21)."""
    if len(txn.sources) != 1:
        raise MemoryTxnError(
            f"repair expects exactly ONE source page, found {len(txn.sources)}"
        )
    if deletes:
        raise MemoryTxnError(
            f"repair must not delete any page (found {len(deletes)} delete(s))"
        )
    source_rel = next(iter(txn.sources))
    if list(writes) != [source_rel]:
        raise MemoryTxnError(
            f"repair must write exactly the source page {source_rel!r}, got {sorted(writes)}"
        )
    source_text = (txn.scope_root / source_rel).read_text(encoding="utf-8")
    source_meta = verify.parse_frontmatter(source_text)
    result_text = writes[source_rel]
    result_meta = verify.parse_frontmatter(result_text)
    return verify.verify_repair(source_text, source_meta, result_text, result_meta)


def _verify_atomize(txn, writes, deletes):
    """Build verify_atomize inputs. Atomize is a REPAIR-class in-place edit (TRDD-3b9b2040):
    ONE write at the source's path, ZERO deletes — it only ADDS `^id [keywords:…]` markers to
    a free-prose page's facts, losing nothing. A merge/split-shaped change set is a bug here."""
    if len(txn.sources) != 1:
        raise MemoryTxnError(
            f"atomize expects exactly ONE source page, found {len(txn.sources)}"
        )
    if deletes:
        raise MemoryTxnError(
            f"atomize must not delete any page (found {len(deletes)} delete(s))"
        )
    source_rel = next(iter(txn.sources))
    if list(writes) != [source_rel]:
        raise MemoryTxnError(
            f"atomize must write exactly the source page {source_rel!r}, got {sorted(writes)}"
        )
    source_text = (txn.scope_root / source_rel).read_text(encoding="utf-8")
    source_meta = verify.parse_frontmatter(source_text)
    result_text = writes[source_rel]
    result_meta = verify.parse_frontmatter(result_text)
    return verify.verify_atomize(source_text, source_meta, result_text, result_meta)


def _split_max_bytes() -> int:
    """The configured split size cap (memory_settings is a sibling lib on the path;
    `get` degrades to its own default internally, so this never needs a fallback)."""
    import memory_settings
    return int(memory_settings.get("split_max_bytes"))


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #

def cmd_begin(args) -> int:
    if not memory_txn.editor_enabled():
        print("error: wikimem editor disabled (kill-switch or option)", file=sys.stderr)
        return 2
    scope = Path(args.scope_root).expanduser()
    txn = MemoryTxn.begin(scope, args.op, args.sources)
    print(f"txn_id={txn.txn_id}")
    print(f"staging={txn.staging_dir}")
    return 0


def cmd_commit(args) -> int:
    scope = Path(args.scope_root).expanduser().resolve()
    txn = _load_txn(scope, args.txn_id)
    # L-7 (wikimem audit 2026-07-07): the journal's op — declared at begin — is the
    # txn's shape contract; verifying a merge-shaped txn with the repair oracle
    # proves nothing. A mismatched --op is a CALLER error: refuse WITHOUT aborting,
    # so a typo'd flag cannot destroy a valid staged edit. ONE sanctioned pairing:
    # a `conflict` journal commits via `--op merge` — conflict IS merge-shaped
    # (pair-retirement), and _verify_merge reads txn.op=="conflict" to apply its
    # legality exemption (conflict-protocol.md).
    if args.op != txn.op and not (txn.op == "conflict" and args.op == "merge"):
        print(
            f"error: --op {args.op!r} does not match the journal's recorded op "
            f"{txn.op!r} (declared at begin); re-run with that op or abort the txn",
            file=sys.stderr,
        )
        return 2
    writes, deletes = _reconstruct_changes(txn)
    if not writes and not deletes:
        txn.abort()
        print("error: no changes staged (nothing written, added, or removed)", file=sys.stderr)
        return 2

    try:
        if args.op == "merge":
            ok, reasons = _verify_merge(txn, writes, deletes)
        elif args.op == "split":
            ok, reasons = _verify_split(txn, writes, deletes, unsplittable=args.unsplittable)
        elif args.op == "atomize":
            ok, reasons = _verify_atomize(txn, writes, deletes)
        else:
            ok, reasons = _verify_repair(txn, writes, deletes)
    except MemoryTxnError:
        # L-10 (wikimem audit 2026-07-07): a shape error is as final as a verify
        # FAIL — abort, or staging+journal silently age out over 30 min. abort()
        # is H-2-guarded (no-op past the staging phase), so this can never
        # destroy a committing journal.
        txn.abort()
        raise
    except OSError as exc:
        # A source vanishing mid-verify printed a raw traceback; map it to the
        # CLI's `error:` contract and clean up the txn.
        txn.abort()
        raise MemoryTxnError(f"live-tree read failed during verify: {exc}") from exc

    if not ok:
        txn.abort()
        print(f"verify FAILED ({args.op}); transaction aborted:", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1

    # Authoring-integrity DELTA gate (TRDD-4ZTNMQL3): verify_* proves no KNOWLEDGE was lost; this
    # proves the hand-edit did not INTRODUCE malformed SYNTAX (unquoted desc, body-less lesson,
    # supersession missing its SUPERSEDED BODY). Fail-open — never breaks a valid commit.
    a_ok, a_reasons, a_warnings = _authoring_gate(txn, writes)
    for w in a_warnings:
        print(f"  warning: {w}", file=sys.stderr)
    if not a_ok:
        txn.abort()
        print(f"authoring-integrity gate FAILED ({args.op}); transaction aborted:", file=sys.stderr)
        for r in a_reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1

    # Verify passed → register the reconstructed change set into the journal and
    # commit atomically (the txn re-hashes sources for the stale-snapshot guard,
    # takes the per-scope flock, and applies writes-before-deletes via os.replace).
    try:
        for rel, content in writes.items():
            txn.stage_write(rel, content)
        for rel in deletes:
            txn.stage_delete(rel)
        txn.commit()
    except MemoryTxnError:
        # L-10: same clean-up contract for the apply half; abort() is H-2-guarded,
        # so a failure AFTER phase=committing keeps its roll-forward journal.
        txn.abort()
        raise
    print(f"committed {txn.txn_id} ({args.op}): "
          f"{len(writes)} write(s), {len(deletes)} delete(s)")
    return 0


def cmd_abort(args) -> int:
    scope = Path(args.scope_root).expanduser().resolve()
    txn = _load_txn(scope, args.txn_id)
    txn.abort()
    print(f"aborted {args.txn_id}")
    return 0


def cmd_resume(args) -> int:
    scope = Path(args.scope_root).expanduser().resolve()
    acted = memory_txn.resume_pending(scope)
    for line in acted:
        print(line)
    if not acted:
        print("resume: nothing pending")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_txn_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("begin", help="open a transaction; copy sources into staging")
    b.add_argument("scope_root")
    b.add_argument("op")
    b.add_argument("sources", nargs="*", help="source page rel-paths to copy into staging")

    c = sub.add_parser("commit", help="verify the staged edit and apply it atomically")
    c.add_argument("scope_root")
    c.add_argument("txn_id")
    c.add_argument("--op", required=True, choices=("merge", "split", "repair", "atomize"))
    c.add_argument(
        "--unsplittable", action="append", default=None, metavar="REL",
        help="rel-path of a split output allowed to stay over the size cap (an "
             "atomic leaf that cannot be split further); repeatable. L-8: without "
             "this the library's escape hatch was unreachable from the CLI.",
    )

    a = sub.add_parser("abort", help="discard a not-yet-committed transaction")
    a.add_argument("scope_root")
    a.add_argument("txn_id")

    r = sub.add_parser("resume", help="roll forward / clean interrupted transactions")
    r.add_argument("scope_root")

    args = ap.parse_args()
    handlers = {"begin": cmd_begin, "commit": cmd_commit, "abort": cmd_abort, "resume": cmd_resume}
    try:
        return handlers[args.cmd](args)
    except MemoryTxnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
