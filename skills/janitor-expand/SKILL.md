---
name: janitor-expand
description: Use when an injected compacted context shows a pointer like `[[elided id=<uuid>:<n> tokens=<t> "<preview>"]]` and you need the original text it stands in for. Expands one pointer at a time — never reads the transcript file directly.
---

# Janitor expand

## What a pointer is

Jev compaction (TRDD-RAEGS1D5) elides most of an old session's transcript,
keeping only what scored relevant or decision-worthy. Everything else becomes a
one-line pointer:

```
[[elided id=a1b2c3-...-uuid:4 tokens=812 "fixed the auth null-check bug"]]
```

- `id` is `<entry uuid>:<block index>` — the position of that block in the
  original JSONL entry's own content list.
- `tokens` is the estimated size of the ORIGINAL text (not the pointer line).
- The quoted preview is the first line only, truncated to 80 chars.

## Getting the original text back

The compacted context's LAST line carries the full expand command, path
included:

```
pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript /path/to/the/old/session/transcript.jsonl <id>
```

Replace `<id>` with a pointer's id to expand it:

```bash
uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand \
  --transcript /path/to/the/old/session/transcript.jsonl a1b2c3-...-uuid:4
```

This prints the block's ORIGINAL bytes to stdout and exits 0, or prints why it
failed and exits 3 (bad id, unknown uuid, or the block index isn't in that
entry's content list).

Or replace `<id>` with `--list --grep TEXT` to list every item's id instead
(optionally filtered by `TEXT`), when you don't have an id yet:

```bash
uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand \
  --transcript /path/to/the/old/session/transcript.jsonl --list --grep auth
```

## NEVER Read the transcript file yourself

A session transcript is routinely 24–258 MB. A pointer deliberately never
carries a path so nothing tempts a direct `Read` of the transcript — `expand`
is the only sanctioned way in, because it prints ONE block, not the whole
file. Reading the transcript directly burns the exact context budget Jev
compaction exists to protect.

## Multiple pointers

Each pointer needs its own `expand` call — there is no batch form. Expand only
the pointers whose content the current task actually needs.
