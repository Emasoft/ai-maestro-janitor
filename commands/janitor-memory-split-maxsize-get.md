---
description: Show the current maximum wikimem page byte size before the SPLIT pass divides a page. Read-only. Trigger with /janitor-memory-split-maxsize-get or by asking the memory-page split size threshold.
---

# /janitor-memory-split-maxsize-get

Show the current global **maximum page size** (bytes) above which a wikimem page
is a SPLIT candidate. Read-only.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" get split_max_bytes
```

Surface the script's one-line output verbatim.
