---
description: Show how many times per DAY the wikimem REPAIR (page-shape / metadata backfill) pass currently runs (the global cadence, with its derived every-N-hours interval, or DISABLED if 0). Read-only. Trigger with /janitor-memory-repair-frequency-get or by asking how often malformed memory pages are repaired.
---

# /janitor-memory-repair-frequency-get

Show the current global cadence of the wikimem **REPAIR** pass (times per day +
the derived interval, or `DISABLED` when set to 0). Read-only.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" get repair_per_day
```

Surface the script's one-line output verbatim.
