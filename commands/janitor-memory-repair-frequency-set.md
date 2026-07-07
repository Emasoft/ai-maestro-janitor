---
description: Set how many times per DAY the wikimem REPAIR (page-shape / metadata backfill) pass runs. Times-per-day float (0.5 = once every 48h; 0 = disabled). Run with NO number to revert to the default (0 = disabled — the pass is opt-in). Global — machine-wide, not per-repo. Trigger with /janitor-memory-repair-frequency-set or by asking to change how often malformed memory pages are repaired.
argument-hint: "[times-per-day]"
---

# /janitor-memory-repair-frequency-set

Set the global cadence of the wikimem **REPAIR** pass (it completes/corrects the
shape of malformed wiki pages in place). The value is **times per day** (a float:
`0.5` = once every 48h; `0` disables the pass). With **no argument** it reverts to
the default (`0` — REPAIR is opt-in, off by default per the USER cost decision
2026-06-30). All wikimem-editor settings are **global** (machine-wide), never
per-repo.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" set repair_per_day "$ARGUMENTS"
```

Surface the script's one-line confirmation verbatim.
