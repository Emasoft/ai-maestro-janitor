---
description: Set how many times per DAY the wikimem ATOMIZE pass runs (it adds leading block-property markers to page facts so recall can rank atoms). Times-per-day float (0.5 = once every 48h; 0 = disabled). Run with NO number to revert to the default (0 = disabled — the pass is opt-in). Global — machine-wide, not per-repo. Trigger with /janitor-memory-atomize-frequency-set or by asking to change how often memory pages are atomized.
argument-hint: "[times-per-day]"
---

# /janitor-memory-atomize-frequency-set

Set the global cadence of the wikimem **ATOMIZE** pass (it inserts leading
`^id [desc:…, keywords:…]` markers above each fact so recall ranks atoms). The
value is **times per day** (a float: `0.5` = once every 48h; `0` disables the
pass). With **no argument** it reverts to the default (`0` — ATOMIZE is opt-in,
off by default per the USER cost decision 2026-06-30). All wikimem-editor settings
are **global** (machine-wide), never per-repo.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" set atomize_per_day "$ARGUMENTS"
```

Surface the script's one-line confirmation verbatim.
