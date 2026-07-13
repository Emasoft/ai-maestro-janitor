---
description: Show or change how often the wikimem editorial passes run (consolidate, split, conflict, repair, harvest, atomize) and the split max-size. No args lists every setting. Global, machine-wide. Trigger with /janitor-memory-frequency or by asking how often memory pages are merged, split, repaired, harvested, atomized, or conflict-checked.
argument-hint: "[<pass>|split-maxsize] [<value>]"
---

# /janitor-memory-frequency

One command for every wikimem editorial-pass knob. Replaces the fourteen
`/janitor-memory-*-frequency-{get,set}` + `*-maxsize-{get,set}` commands: each cost
always-on listing tokens in EVERY session, forever, to be typed almost never.

**Settings are GLOBAL (machine-wide), not per-repo.**

## Usage

| Invocation | Effect |
|---|---|
| `/janitor-memory-frequency` | list every setting + its current value |
| `/janitor-memory-frequency <pass>` | show one pass's cadence |
| `/janitor-memory-frequency <pass> <times-per-day>` | set it (`0.5` = once/48h; `0` = DISABLED) |
| `/janitor-memory-frequency <pass>` *(with no value, to reset)* | see "Reverting" below |
| `/janitor-memory-frequency split-maxsize` | show the SPLIT size threshold (bytes) |
| `/janitor-memory-frequency split-maxsize <bytes>` | set it |

`<pass>` is one of: `consolidate` · `split` · `conflict` · `repair` · `harvest` · `atomize`.

Every editorial pass is **OFF by default** (`0` — the USER cost decision of 2026-06-30);
enabling one requires an explicit number.

## Run

Map `<pass>` → its settings key (`consolidate`→`consolidation_per_day`, else
`<pass>_per_day`; `split-maxsize`→`split_max_bytes`), then:

```bash
CLI="${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py"

# No argument → list everything.
uv run --script --quiet "$CLI" list

# One argument → get.
uv run --script --quiet "$CLI" get <key>

# Two arguments → set.
uv run --script --quiet "$CLI" set <key> <value>
```

**Reverting to the default:** `set <key>` with NO value reverts that key. Since the
one-argument form of this command means *get*, pass the default explicitly instead
(`0` for a pass, `36000` for `split-maxsize`), or run the bare
`uv run --script --quiet "$CLI" set <key>` yourself.

Surface the script's output verbatim — one line per setting, nothing added.
