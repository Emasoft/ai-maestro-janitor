---
description: Show how many times per DAY the wikimem ATOMIZE pass currently runs (the global cadence, with its derived every-N-hours interval, or DISABLED if 0). Read-only. Trigger with /janitor-memory-atomize-frequency-get or by asking how often memory pages are atomized.
---

# /janitor-memory-atomize-frequency-get

Show the current global cadence of the wikimem **ATOMIZE** pass (times per day +
the derived interval, or `DISABLED` when set to 0). Read-only.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" get atomize_per_day
```

Surface the script's one-line output verbatim.
