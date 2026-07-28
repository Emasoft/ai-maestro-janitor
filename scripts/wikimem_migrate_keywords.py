#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Recover keyword phrases the atom-props parser silently drops (plan Phase 1.3).

THE DEFECT. An atom's props block is `^id [k: v, k: v, ...]`. Commas separate FIELDS and spaces
separate KEYWORDS, so the widespread hand-authored form

    keywords: requests hang forever, pool never recovers, connections leak

loses everything after the first comma — those segments carry no `key:` prefix, so the parser
discards them outright — and shreds the survivor into the loose words `requests`/`hang`/`forever`.
Since `keywords` IS the recall surface, most of such an atom's symptom phrases simply do not exist
as far as retrieval is concerned. Measured end to end: querying an atom with its own 5th declared
phrase does not return it at all.

WHY THIS IS RECOVERABLE, NOT GUESSWORK. Only the PARSE drops the text; the bytes are still in the
file. A dropped segment is exactly a comma-segment with no `key:` prefix, and it can only ever have
belonged to the key preceding it — so re-attaching it is deterministic, not inference.

THE TWO REPAIRS, chosen per key rather than applied uniformly:
  keywords -> underscore-join each phrase and separate phrases with spaces. Quotes cannot help
              here: after quote-stripping the value is still split on whitespace, so `"a b"` is
              two keywords either way. Underscores are the only thing that makes a phrase atomic.
  desc     -> re-quote the whole value. Quoting IS the sanctioned grammar-safety for prose
              (TRDD-AP2X9A0H replaced the old snake_case slug with ≤200-char quoted prose), and
              desc is display text, so its internal spaces are harmless.

Any OTHER key with orphans is REFUSED, never guessed: a key this tool has no rule for is a shape
nobody has thought about, and silently rewriting it would be the same class of quiet corruption
this script exists to undo.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# `^<block-id> [<props>]` at the start of a line — the LEADING atom marker.
_MARKER_RE = re.compile(r"^(\^[A-Za-z0-9_-]+)[ ]*\[(.*)\][ ]*$")
# A props key: lowercase kebab followed by a colon. Anything else is an orphan segment.
_KEY_RE = re.compile(r"^\s*([a-z][a-z0-9-]*)\s*:")


def split_top_level_commas(props: str) -> list[str]:
    """Split on commas that are NOT inside double quotes — mirrors the Rust splitter.

    Quote-awareness is what lets a quoted `desc:` legitimately contain commas; a naive split would
    corrupt exactly the pages that already use the correct grammar.
    """
    out: list[str] = []
    buf: list[str] = []
    in_q = False
    for ch in props:
        if ch == '"':
            in_q = not in_q
            buf.append(ch)
        elif ch == "," and not in_q:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def _slug(phrase: str) -> str:
    """Underscore-join a key-phrase so it survives as ONE keyword."""
    return "_".join(phrase.split())


class Refused(Exception):
    """A props block has orphans under a key with no defined repair. Nothing is rewritten."""


def repair_props(props: str) -> tuple[str, int]:
    """Return (repaired props, number of recovered orphan segments).

    Raises `Refused` when an orphan belongs to a key other than keywords/desc.
    """
    segments = split_top_level_commas(props)
    fields: list[tuple[str | None, str]] = []  # (key or None for orphan, raw text)
    for seg in segments:
        m = _KEY_RE.match(seg)
        fields.append((m.group(1), seg) if m else (None, seg))

    if not any(k is None for k, _ in fields):
        return props, 0

    rebuilt: list[str] = []
    recovered = 0
    i = 0
    while i < len(fields):
        key, raw = fields[i]
        if key is None:
            # An orphan with no preceding key at all — malformed beyond this tool's remit.
            raise Refused("orphan segment with no preceding key")
        # Collect the orphans that follow this key.
        orphans: list[str] = []
        j = i + 1
        while j < len(fields) and fields[j][0] is None:
            orphans.append(fields[j][1].strip())
            j += 1

        if not orphans:
            rebuilt.append(raw)
            i = j
            continue

        value = raw.split(":", 1)[1].strip()
        if key == "keywords":
            phrases = [value, *orphans]
            joined = " ".join(_slug(p) for p in phrases if p)
            rebuilt.append(f" keywords: {joined}" if raw.startswith(" ") else f"keywords: {joined}")
        elif key == "desc":
            merged = ", ".join([value.strip('"'), *[o.strip('"') for o in orphans]])
            rebuilt.append(f' desc: "{merged}"' if raw.startswith(" ") else f'desc: "{merged}"')
        else:
            raise Refused(f"orphan segment(s) under unsupported key {key!r}")
        recovered += len(orphans)
        i = j

    return ",".join(rebuilt), recovered


def repair_text(text: str) -> tuple[str, int, list[str]]:
    """Repair every atom marker in a page. Returns (new text, recovered count, refusals)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    total = 0
    refusals: list[str] = []
    for n, line in enumerate(lines, 1):
        stripped = line.rstrip("\n")
        m = _MARKER_RE.match(stripped)
        if not m:
            out.append(line)
            continue
        try:
            props, count = repair_props(m.group(2))
        except Refused as exc:
            refusals.append(f"line {n}: {exc}")
            out.append(line)
            continue
        if count == 0:
            out.append(line)
            continue
        total += count
        nl = "\n" if line.endswith("\n") else ""
        out.append(f"{m.group(1)} [{props}]{nl}")
    return "".join(out), total, refusals


def main() -> int:
    ap = argparse.ArgumentParser(description="recover dropped atom keyword phrases")
    ap.add_argument("paths", nargs="+", type=Path, help="memory dirs or pages")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    a = ap.parse_args()

    files: list[Path] = []
    for p in a.paths:
        files.extend(sorted(p.rglob("*.md")) if p.is_dir() else [p])

    total = 0
    changed = 0
    all_refusals: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        new, count, refusals = repair_text(text)
        for r in refusals:
            all_refusals.append(f"{f}: {r}")
        if count:
            total += count
            changed += 1
            print(f"{'apply ' if a.apply else 'dry   '} {f}: recovered {count} phrase(s)")
            if a.apply:
                tmp = f.with_suffix(f.suffix + ".tmp")
                tmp.write_text(new, encoding="utf-8")
                tmp.replace(f)

    for r in all_refusals:
        print(f"REFUSED {r}", file=sys.stderr)
    print(f"\n{changed} page(s), {total} phrase(s) recovered{'' if a.apply else ' (dry run)'}")
    if all_refusals:
        print(f"{len(all_refusals)} refusal(s) — left untouched", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
