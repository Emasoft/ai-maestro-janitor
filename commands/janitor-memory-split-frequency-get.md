---
description: Show how many times per DAY the wikimem SPLIT pass currently runs (the global cadence + derived interval, or DISABLED if 0). Read-only. Trigger with /janitor-memory-split-frequency-get or by asking how often oversized memory pages are split.
---

# /janitor-memory-split-frequency-get

Show the current global cadence of the wikimem **SPLIT** pass (times per day +
the derived interval, or `DISABLED` when 0). Read-only.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" get split_per_day
```

Surface the script's one-line output verbatim.
