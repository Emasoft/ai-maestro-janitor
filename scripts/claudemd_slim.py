#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""claudemd_slim — the slim janitor-managed CLAUDE.md CLI (TRDD-H12K9JYX).

Owner directive 2026-08-02: a janitor-managed CLAUDE.md carries ONLY the concise project
description, the repo URLs, the basic lint/build/test/publish instructions, the janitor
project map, and a topic-ordered index of the PROJECT-scope wikimem pages. This CLI is
the MECHANICAL half of that contract; the editorial half (which narrative becomes which
wikimem page) is the `janitor-project-cld-md-optimizer` skill.

  uv run scripts/claudemd_slim.py index            # insert-or-refresh the wikimem index
  uv run scripts/claudemd_slim.py index --stdout   # print the block, touch nothing
  uv run scripts/claudemd_slim.py check            # slim-contract + index freshness probe
  uv run scripts/claudemd_slim.py verify --old F   # preservation proof for a migration
  uv run scripts/claudemd_slim.py plan             # DECISION-only migration plan (writes nothing)

Exit codes: 0 = ok / written / fresh / preserved; 1 = check found violations or a stale
index, or verify found DROPPED content; 3 = error (no CLAUDE.md, malformed fences, lock
held, splice gave up).

The `index` write reuses the repo-map generator's anti-corruption machinery verbatim
(writer lock, lost-update retry loop, byte-preservation outside the fence, atomic
replace) — CLAUDE.md is co-owned by the human and the session's Claude, and the janitor
must never corrupt or silently discard their edits. See scripts/repomap_generate.py's
module docstring for the full contract; this CLI only swaps WHICH fence is spliced.

`verify` is the gate Phase B (the actual migration) must pass BEFORE a slim CLAUDE.md is
committed: every substantive fact line AND every load-bearing token (paths, URLs, env
keys, versions — memory_edit_verify's oracles) of the OLD narrative must survive into the
NEW narrative or the PROJECT wikimem corpus. No content leaves CLAUDE.md unproven — the
same discipline the wikimem editor applies to its own merges.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import claudemd_migration_plan as cmig  # noqa: E402  # TRDD-LFSWY0C6 — DECISION-only planner
import memory_edit_verify as mev  # noqa: E402
import memory_scopes  # noqa: E402
import repomap_generate as rg  # noqa: E402  # the shared anti-corruption write machinery
from repomap import MalformedFences  # noqa: E402
from repomap.claudemd_slim import (  # noqa: E402
    WIKIMEM_FENCE_END,
    WIKIMEM_FENCE_START,
    index_is_stale,
    narrative_outside_fences,
    render_index,
    scan_pages,
    slim_violations,
)
from repomap.markers import _fence_span, insert_map_block, replace_map_block  # noqa: E402


def _memdir(root: Path) -> Path:
    return root / ".claude" / "project" / "memory"


def _verified_index_candidate(current: str, block: str) -> str:
    """Splice the INDEX block into `current` and PROVE the result safe to write: exactly
    one wikimem fence pair, and every byte outside it unchanged — including the repo-map
    fence, which this splice must never touch (the two fences must not eat each other)."""
    has = _fence_span(current, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END) is not None
    if has:
        candidate = replace_map_block(current, block, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END)
    else:
        candidate = insert_map_block(current, block, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END)
    if candidate.count(WIKIMEM_FENCE_START) != 1 or candidate.count(WIKIMEM_FENCE_END) != 1:
        raise MalformedFences("candidate does not contain exactly one wikimem-index fence pair")

    def outside(text: str) -> str:
        span = _fence_span(text, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END)
        return text if span is None else text[: span[0]] + text[span[1] :]

    if outside(candidate).rstrip("\n") != outside(current).rstrip("\n"):
        raise MalformedFences("candidate would alter bytes outside the wikimem-index fence")
    return candidate


def _splice_index(claude_md: Path, block: str) -> bool:
    """The lost-update write loop, mirroring rg.splice_with_verify for the index fence
    (same signature check + settle-delay torn-read handling; see the long notes there)."""
    for attempt in range(rg._SPLICE_ATTEMPTS):
        if attempt:
            time.sleep(rg._SPLICE_SETTLE_S)
        sig_before = rg._stat_sig(claude_md)
        current = claude_md.read_text(encoding="utf-8") if sig_before is not None else ""
        if sig_before is not None and not current.strip():
            time.sleep(rg._SPLICE_SETTLE_S)  # torn read — settle past a writer's truncate window
            current = claude_md.read_text(encoding="utf-8")
        candidate = _verified_index_candidate(current, block)
        if rg._stat_sig(claude_md) != sig_before:
            continue
        rg._atomic_replace(claude_md, candidate)
        return True
    return False


def cmd_index(root: Path, *, to_stdout: bool) -> int:
    pages = scan_pages(_memdir(root))
    if not pages:
        print(f"claudemd-slim: no PROJECT wikimem pages under {_memdir(root)}")
        return 3
    block = render_index(pages, generated_iso=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    if to_stdout:
        sys.stdout.write(block)
        return 0
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        print("claudemd-slim: no CLAUDE.md")
        return 3
    lock = rg._GenLock(root)
    if not lock.acquire():
        print("claudemd-slim: another generator holds the lock — skipping")
        return 3
    try:
        if not index_is_stale(claude_md.read_text(encoding="utf-8"), pages):
            print("claudemd-slim: index already current (digest match) — no write")
            return 0
        rg._backup(claude_md)
        if not _splice_index(claude_md, block):
            print("claudemd-slim: CLAUDE.md is being actively edited — giving up safely (retry later)")
            return 3
        print(f"claudemd-slim: wrote wikimem index ({len(pages)} pages) into {claude_md}")
        return 0
    finally:
        lock.release()


def cmd_check(root: Path) -> int:
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        print("claudemd-slim: no CLAUDE.md")
        return 3
    text = claude_md.read_text(encoding="utf-8")
    problems = slim_violations(text)
    if index_is_stale(text, scan_pages(_memdir(root))):
        problems.append("wikimem index is STALE vs the corpus (run scripts/claudemd_slim.py index)")
    if not problems:
        print("claudemd-slim: conforming and fresh")
        return 0
    for p in problems:
        print(f"claudemd-slim: {p}")
    return 1


def cmd_verify(root: Path, old_file: Path) -> int:
    """Prove the migration lost nothing: OLD narrative facts + load-bearing tokens must
    survive into the NEW narrative or the PROJECT wikimem corpus."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file() or not old_file.is_file():
        print("claudemd-slim: need both CLAUDE.md and --old <pre-migration copy>")
        return 3
    old_narrative = narrative_outside_fences(old_file.read_text(encoding="utf-8"))
    new_narrative = narrative_outside_fences(claude_md.read_text(encoding="utf-8"))
    corpus = []
    for p in scan_pages(_memdir(root)):
        try:
            corpus.append((_memdir(root) / p.filename).read_text(encoding="utf-8"))
        except OSError:
            continue
    haystack = "\n".join([new_narrative, *corpus])
    ok_facts, missing_facts = mev.body_facts_preserved([old_narrative], haystack)
    ok_tokens, missing_tokens = mev.fact_tokens_preserved([old_narrative], haystack)
    if ok_facts and ok_tokens:
        print("claudemd-slim: preservation PROVEN — every fact line and token survives")
        return 0
    for m in missing_facts:
        print(f"claudemd-slim: DROPPED fact line: {m[:160]}")
    for m in missing_tokens:
        print(f"claudemd-slim: DROPPED token: {m[:160]}")
    print("claudemd-slim: migration would LOSE the content above — move it into a wikimem page first")
    return 1


def cmd_plan(root: Path) -> int:
    """DECISION-only migration plan (TRDD-LFSWY0C6): reports what WOULD migrate where.
    Never writes CLAUDE.md, never writes/creates a memory page, never removes a line —
    the delivery half is a separate, later task."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        print("claudemd-slim: no CLAUDE.md")
        return 3
    text = claude_md.read_text(encoding="utf-8")
    roots = [scope_root for _label, scope_root in memory_scopes.resolve_scope_dirs()]
    plans = cmig.plan_migration(text, roots=roots)
    print(cmig.render_plan(plans), end="")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Slim janitor-managed CLAUDE.md — wikimem index + contract checks")
    ap.add_argument("--root", help="project root (default: $CLAUDE_PROJECT_DIR or cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_index = sub.add_parser("index", help="insert-or-refresh the wikimem index fence")
    p_index.add_argument("--stdout", action="store_true", help="print the block; touch nothing")
    sub.add_parser("check", help="slim-contract + index freshness probe (no write)")
    p_verify = sub.add_parser("verify", help="preservation proof for a migration")
    p_verify.add_argument("--old", required=True, help="pre-migration CLAUDE.md copy")
    sub.add_parser("plan", help="DECISION-only migration plan — writes nothing (TRDD-LFSWY0C6)")

    args = ap.parse_args()
    root = rg._resolve_root(args.root)
    try:
        if args.cmd == "index":
            return cmd_index(root, to_stdout=args.stdout)
        if args.cmd == "check":
            return cmd_check(root)
        if args.cmd == "plan":
            return cmd_plan(root)
        return cmd_verify(root, Path(args.old).resolve())
    except MalformedFences as exc:
        print(f"claudemd-slim: refusing to touch CLAUDE.md — {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
