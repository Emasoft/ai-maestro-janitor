---
description: Set the maximum byte size of a wikimem page before the SPLIT pass divides it into an overview + sub-pages. Positive integer (bytes). Run with NO number to revert to the default (12000). Global — machine-wide, not per-repo. Trigger with /janitor-memory-split-maxsize-set or by asking to change the memory-page split size threshold.
argument-hint: "[bytes]"
---

# /janitor-memory-split-maxsize-set

Set the global **maximum page size** (in bytes) above which a wikimem page
becomes a SPLIT candidate. A positive integer. With **no argument** it reverts to
the default (`12000`). Settings are **global** (machine-wide).

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_settings_cli.py" set split_max_bytes "$ARGUMENTS"
```

Surface the script's one-line confirmation verbatim.
