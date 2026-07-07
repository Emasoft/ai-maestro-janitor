---
description: Set how many times per DAY the wikimem SPLIT pass runs (it splits an oversized page into an overview + linked sub-pages). Times-per-day float (0.5 = once every 48h; 0 = disabled). Run with NO number to revert to the default (0 = DISABLED — USER cost decision 2026-06-30; opting in requires an explicit number). Global — machine-wide, not per-repo. Trigger with /janitor-memory-split-frequency-set or by asking how often oversized memory pages are split.
argument-hint: "[times-per-day]"
---

# /janitor-memory-split-frequency-set

Set the global cadence of the wikimem **SPLIT** pass (it splits a page that
exceeds the max size into an overview + linked sub-pages, recursively). The value
is **times per day** (`0.5` = once/48h; `0` disables). With **no argument** it
reverts to the default (`0` = DISABLED — the USER cost decision of 2026-06-30
turned every editorial pass off by default; enabling requires an explicit
number). Settings are **global** (machine-wide).

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" set split_per_day "$ARGUMENTS"
```

Surface the script's one-line confirmation verbatim.
