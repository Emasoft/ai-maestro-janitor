---
description: Set how many times per DAY the wikimem CONFLICT + fact-verification pass runs (it reconciles contradictory/obsolete memories against source + git history — the most token-costly pass). Times-per-day float (0.5 = once every 48h; 0 = disabled). Run with NO number to revert to the default (0 = DISABLED — USER cost decision 2026-06-30; opting in requires an explicit number). Global — machine-wide, not per-repo. Trigger with /janitor-memory-conflict-frequency-set.
argument-hint: "[times-per-day]"
---

# /janitor-memory-conflict-frequency-set

Set the global cadence of the wikimem **CONFLICT + fact-verification** pass (it
reconciles contradictory/obsolete memories against the source code + git history
— the most expensive pass, so the default is low). The value is **times per day**
(`0.5` = once every 48h; `0` disables). With **no argument** it reverts to the
default (`0` = DISABLED — the USER cost decision of 2026-06-30 turned every
editorial pass off by default; enabling requires an explicit number).
Settings are **global** (machine-wide).

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" set conflict_per_day "$ARGUMENTS"
```

Surface the script's one-line confirmation verbatim.
