---
name: janitor-memory-frequency
description: Show or change how often the wikimem editorial passes run (consolidate, split, conflict, repair, harvest, atomize, retro-lesson) and the split max-size. No args lists every setting. Global, machine-wide. Use when the user asks how often memory pages are merged, split, repaired, harvested, atomized, retro-lesson-backfilled, or conflict-checked, or asks to change / enable / disable a wikimem editorial-pass cadence.
---

# Janitor memory-frequency

## Overview

One skill for every wikimem editorial-pass knob (replaces the fourteen
`/janitor-memory-*-frequency-{get,set}` + `*-maxsize-{get,set}` commands). **Settings are GLOBAL
(machine-wide), not per-repo.** Every editorial pass is **OFF by default** (`0` — the USER cost
decision of 2026-06-30); enabling one requires an explicit number.

## When to use

- The user asks how often memory pages are consolidated / split / conflict-checked / repaired /
  harvested / atomized / retro-lesson-backfilled.
- The user asks to enable, disable, or change one of those cadences, or the split max-size.

## Instructions

`<pass>` is one of: `consolidate` · `split` · `conflict` · `repair` · `harvest` · `atomize` · `retro-lesson`.

| Invocation | Effect |
|---|---|
| `/janitor-memory-frequency` | list every setting + its current value |
| `/janitor-memory-frequency <pass>` | show one pass's cadence |
| `/janitor-memory-frequency <pass> <times-per-day>` | set it (`0.5` = once/48h; `0` = DISABLED) |
| `/janitor-memory-frequency split-maxsize` | show the SPLIT size threshold (bytes) |
| `/janitor-memory-frequency split-maxsize <bytes>` | set it |

Map `<pass>` → its settings key (`consolidate`→`consolidation_per_day`, else `<pass>_per_day`;
`split-maxsize`→`split_max_bytes`), then run the CLI with the args the user gave:

```bash
CLI="${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py"
uv run --script --quiet "$CLI" list                 # no argument → list everything
uv run --script --quiet "$CLI" get <key>            # one argument → get
uv run --script --quiet "$CLI" set <key> <value>    # two arguments → set
```

**Reverting to the default:** `set <key>` with NO value reverts that key. Since the one-argument form
means *get*, pass the default explicitly instead (`0` for a pass, `36000` for `split-maxsize`), or run
the bare `uv run --script --quiet "$CLI" set <key>` yourself.

Surface the script's output verbatim — one line per setting, nothing added.

## Scope

Reads/writes ONLY the global wikimem editorial-pass settings (machine-wide). Changes no memory
content and runs no editorial pass itself — it only sets the cadence the scheduler honors.
