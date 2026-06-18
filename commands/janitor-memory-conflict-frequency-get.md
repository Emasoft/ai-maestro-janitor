---
description: Show how many times per DAY the wikimem CONFLICT + fact-verification pass currently runs (the global cadence + derived interval, or DISABLED if 0). Read-only. Trigger with /janitor-memory-conflict-frequency-get.
---

# /janitor-memory-conflict-frequency-get

Show the current global cadence of the wikimem **CONFLICT + fact-verification**
pass (times per day + the derived interval, or `DISABLED` when 0). Read-only.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" get conflict_per_day
```

Surface the script's one-line output verbatim.
