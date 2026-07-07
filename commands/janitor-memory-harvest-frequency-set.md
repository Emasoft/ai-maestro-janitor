---
description: Set how many times per DAY the wikimem HARVEST pass runs (it mirrors newly-created harness buffer memories into the curated wiki). Times-per-day float (0.5 = once every 48h; 0 = disabled). Run with NO number to revert to the default (0 = disabled — the pass is opt-in). Global — machine-wide, not per-repo. Trigger with /janitor-memory-harvest-frequency-set or by asking to change how often new memories are harvested/mirrored into the wiki.
argument-hint: "[times-per-day]"
---

# /janitor-memory-harvest-frequency-set

Set the global cadence of the wikimem **HARVEST** pass (it mirrors new raw buffer
memories into curated `wiki/` pages, never touching the buffer). The value is
**times per day** (a float: `0.5` = once every 48h; `0` disables the pass). With
**no argument** it reverts to the default (`0` — HARVEST is opt-in, off by default
per the USER cost decision 2026-06-30). All wikimem-editor settings are **global**
(machine-wide), never per-repo.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" set harvest_per_day "$ARGUMENTS"
```

Surface the script's one-line confirmation verbatim.
