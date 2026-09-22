#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Jev compaction CLI (TRDD-541CBN36 card 2).

This is its OWN PEP-723 script, separate from the stdlib-only hook scripts, because it is
the one place in this project that needs ``httpx`` — jevctx's ``HttpJevClient`` /
``OpenRouterJevClient`` are built on it (see scripts/lib/jevctx/VENDORED.md and the study
at reports/compaction-replacement/20260922_205137+0200-jev-compaction-study.md §H: "the
scorer must therefore be its OWN PEP-723 script ... and be called as a subprocess"). That
also gives it a CA bundle via ``httpx`` → ``certifi`` in the daemon lane, cf. TRDD-X6I04SAO.

Sub-commands:
  probe                            — one Noul question through the configured provider;
                                      prints ``probe ok noul=<f> cost=<usd> ms=<n>`` and
                                      exits 0, or prints the reason and exits 2.
  expand --transcript P ID         — prints the ORIGINAL bytes of one item (``ID`` =
                                      ``<uuid>:<n>``) from a transcript JSONL; exits 3 if
                                      the entry or the block index isn't found.
  compact ...                      — STUB. Card 3 fills this in; here it only exits 4.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

from jevctx.provider import make_client  # noqa: E402  -- needs the sys.path line above
from jevctx.types import JevError, Noul  # noqa: E402  -- needs the sys.path line above


def cmd_probe(_args: argparse.Namespace) -> int:
    """One Noul question through whichever provider `CLAUDE_PLUGIN_OPTION_JEV_PROVIDER`
    names. A probe failure must never look like a compaction failure to the caller, so it
    is always ONE line on stdout/stderr and a small, distinguishable exit code (2) —
    `arm_prepare.py` greps this line, it does not parse a traceback."""
    try:
        client = make_client()
    except JevError as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 2

    start = time.monotonic()
    try:
        answers = client.ask(
            state={"task": "probe", "items": [{"ref": "a", "text": "probe: is this text non-empty?"}]},
            questions={"a": Noul(instructions="Is the item's text non-empty?", true="non-empty", false="empty")},
        )
    except JevError as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 2
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    elapsed_ms = int((time.monotonic() - start) * 1000)

    answer = answers.get("a")
    noul = getattr(answer, "noul", None)
    if noul is None:
        print("probe failed: response carried no 'a.noul' answer", file=sys.stderr)
        return 2
    cost = getattr(getattr(client, "usage", None), "cost", 0.0)
    print(f"probe ok noul={noul} cost={cost} ms={elapsed_ms}")
    return 0


def _read_jsonl_entry(transcript: Path, target_uuid: str) -> dict[str, Any] | None:
    """Scan the transcript for the entry with ``uuid == target_uuid``.

    A plain linear scan, not an index: a transcript is read here once per `expand` call,
    which is an interactive, occasional operation (a pointer the model chose to follow) —
    not the hot path card 3's compaction pass walks. Building an index for a one-shot CLI
    invocation would be optimizing a call that happens a handful of times per session.
    """
    try:
        with transcript.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("uuid") == target_uuid:
                    return entry
    except OSError:
        return None
    return None


def _extract_block(entry: dict[str, Any], index: int) -> str | None:
    """The original bytes of block ``index`` of ``entry`` — user text (str content, index
    must be 0), or one block of a list-shaped ``user``/``assistant`` content (a
    ``text`` block's ``text``, or a ``tool_result`` block's ``content``, verbatim).
    ``thinking``/``tool_use`` blocks are not expandable on their own (card 3 pairs a
    ``tool_use`` with its ``tool_result`` — expanding the tool_result is the pointer)."""
    message = entry.get("message")
    content = (message.get("content") if isinstance(message, dict) else None) or entry.get("content")
    if isinstance(content, str):
        return content if index == 0 else None
    if not isinstance(content, list):
        return None
    if index < 0 or index >= len(content):
        return None
    block = content[index]
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        return text if isinstance(text, str) else None
    if block_type == "tool_result":
        result = block.get("content")
        if isinstance(result, str):
            return result
        if isinstance(result, list):
            # A structured tool_result: concatenate its own text sub-blocks verbatim.
            parts = [part.get("text", "") for part in result if isinstance(part, dict) and part.get("type") == "text"]
            return "\n".join(parts)
        return None
    return None


def cmd_expand(args: argparse.Namespace) -> int:
    transcript = Path(args.transcript)
    try:
        target_uuid, index_str = args.id.rsplit(":", 1)
        index = int(index_str)
    except ValueError:
        print(f"expand failed: malformed id {args.id!r}, expected '<uuid>:<n>'", file=sys.stderr)
        return 3

    entry = _read_jsonl_entry(transcript, target_uuid)
    if entry is None:
        print(f"expand failed: no transcript entry with uuid={target_uuid!r} in {transcript}", file=sys.stderr)
        return 3

    text = _extract_block(entry, index)
    if text is None:
        print(f"expand failed: no block {index} in entry {target_uuid!r}", file=sys.stderr)
        return 3

    print(text)
    return 0


def cmd_compact(_args: argparse.Namespace) -> int:
    print("compact: not implemented yet — card 3", file=sys.stderr)
    return 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jev_compact")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="one Noul question through the configured Jev provider")

    p_expand = sub.add_parser("expand", help="print the original bytes of one transcript item")
    p_expand.add_argument("--transcript", required=True)
    p_expand.add_argument("id")

    p_compact = sub.add_parser("compact", help="(card 3) compose the compacted context")
    p_compact.add_argument("--transcript")
    p_compact.add_argument("--out")
    p_compact.add_argument("--digest-tokens", type=int, default=4000)
    p_compact.add_argument("--budget-tokens", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "expand":
        return cmd_expand(args)
    return cmd_compact(args)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
