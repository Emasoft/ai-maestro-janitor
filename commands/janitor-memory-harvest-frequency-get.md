---
description: Show how many times per DAY the wikimem HARVEST pass currently runs (the global cadence, with its derived every-N-hours interval, or DISABLED if 0). Read-only. Trigger with /janitor-memory-harvest-frequency-get or by asking how often new memories are harvested/mirrored into the wiki.
---

# /janitor-memory-harvest-frequency-get

Show the current global cadence of the wikimem **HARVEST** pass (times per day +
the derived interval, or `DISABLED` when set to 0). Read-only.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" get harvest_per_day
```

Surface the script's one-line output verbatim.
