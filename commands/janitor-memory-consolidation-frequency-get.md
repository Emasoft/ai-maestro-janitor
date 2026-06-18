---
description: Show how many times per DAY the wikimem MERGE / consolidation pass currently runs (the global cadence, with its derived every-N-hours interval, or DISABLED if 0). Read-only. Trigger with /janitor-memory-consolidation-frequency-get or by asking how often memories are merged/consolidated.
---

# /janitor-memory-consolidation-frequency-get

Show the current global cadence of the wikimem **MERGE / consolidation** pass
(times per day + the derived interval, or `DISABLED` when set to 0). Read-only.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" get consolidation_per_day
```

Surface the script's one-line output verbatim.
