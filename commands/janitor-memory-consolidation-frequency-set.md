---
description: Set how many times per DAY the wikimem MERGE / consolidation pass runs. Times-per-day float (0.5 = once every 48h; 0 = disabled). Run with NO number to revert to the default (2.5/day). Global — machine-wide, not per-repo. Trigger with /janitor-memory-consolidation-frequency-set or by asking to change how often memories are merged/consolidated.
argument-hint: "[times-per-day]"
---

# /janitor-memory-consolidation-frequency-set

Set the global cadence of the wikimem **MERGE / consolidation** pass (it merges
notes about the same subject into one page). The value is **times per day** (a
float: `0.5` = once every 48h; `0` disables the pass). With **no argument** it
reverts to the default (`2.5`/day). All wikimem-editor settings are **global**
(machine-wide), never per-repo.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" set consolidation_per_day "$ARGUMENTS"
```

Surface the script's one-line confirmation verbatim.
