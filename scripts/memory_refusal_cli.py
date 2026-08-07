#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Record (or inspect) a memory-chore refusal — the write surface of the ledger (issue #131).

The abstaining agent already knows it declined a candidate and why; today that knowledge dies in a
gitignored report, so the scheduler re-dispatches and pays ~170k-260k tokens to re-derive the same
"no". This is where the agent writes it down instead.

    memory_refusal_cli.py record --intervention conflict --scope USER --root <memdir> \
        --page a.md --page b.md --reason "different subjects; the shared words are incidental"
    memory_refusal_cli.py check  --intervention conflict --scope USER --root <memdir> \
        --page a.md --page b.md
    memory_refusal_cli.py list   --intervention conflict --scope USER --root <memdir>
    memory_refusal_cli.py clear  --intervention conflict --scope USER --root <memdir> \
        --page a.md --page b.md

A refusal expires by itself when the named pages CHANGE, and after a 7-day TTL. Recording one is
therefore not a permanent silence — but it IS a claim, so `--reason` is required: the next reader has
to be able to re-check the verdict, and a refusal nobody can re-check is indistinguishable from the
chore quietly breaking.

**A ledger entry is the mechanism, not the artifact.** When the verdict belongs where a human will
meet it — "these two pages look mergeable and are not" — write it into the pages themselves as a
cross-linked note, and let this record that you did. The next reader finds the answer at the point of
confusion rather than in `.janitor/state/`.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_refusals  # noqa: E402


def _resolve(root: Path, pages: list[str]) -> list[Path]:
    """Page arguments → absolute paths under `root` (a bare name means a page in the scope)."""
    return [p if (p := Path(page)).is_absolute() else root / page for page in pages]


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_refusal_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("record", "check", "clear", "list"):
        p = sub.add_parser(name)
        p.add_argument("--intervention", required=True)
        p.add_argument("--scope", required=True)
        p.add_argument("--root", required=True)
        if name != "list":
            p.add_argument("--page", action="append", default=[], required=True)
        if name == "record":
            p.add_argument("--reason", required=True)
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    now = int(time.time())

    if args.cmd == "list":
        ledger = memory_refusals.read(args.intervention, args.scope, root)
        if not ledger:
            print("no refusals recorded")
            return 0
        for key, entry in sorted(ledger.items(), key=lambda kv: -int(kv[1].get("ts", 0))):
            age_d = max(0, now - int(entry.get("ts", 0))) // 86400
            print(f"{key}  ({age_d}d ago)  {entry.get('reason', '')}")
        return 0

    pages = _resolve(root, args.page)

    if args.cmd == "record":
        if not args.reason.strip():
            print("REFUSED: --reason is required — a verdict nobody can re-check is not a refusal")
            return 2
        if not memory_refusals.record(
            args.intervention, args.scope, root, list(pages), reason=args.reason, now=now
        ):
            # No content hash ⇒ the entry could never be invalidated by an edit, so it would be a
            # permanent silence rather than a refusal. Refuse to write it.
            print("REFUSED: could not read every named page — nothing recorded")
            return 1
        print(f"recorded: {memory_refusals.candidate_key(root, list(pages))} will not re-dispatch")
        print("  it re-arms automatically when those pages change, and after 7 days")
        return 0

    if args.cmd == "check":
        entry = memory_refusals.refusal(args.intervention, args.scope, root, list(pages), now=now)
        if entry is None:
            print("not refused — this candidate would dispatch")
            return 1
        age_d = max(0, now - int(entry.get("ts", 0))) // 86400
        print(f"refused {age_d}d ago: {entry.get('reason', '')}")
        return 0

    if args.cmd == "clear":
        removed = memory_refusals.clear(args.intervention, args.scope, root, list(pages))
        print("refusal lifted" if removed else "no such refusal")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
