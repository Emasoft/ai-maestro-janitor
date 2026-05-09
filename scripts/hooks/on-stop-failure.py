#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""StopFailure hook — Python port of on-stop-failure.sh.

Fires when an API error (rate-limit, auth failure, etc.) ends the turn
instead of Stop. Writes a flag file that the heartbeat cron's dispatch
reads on its next fire. When the API is reachable again, that fire
succeeds, dispatch sees the flag, clears it, and emits [janitor-resume]
so Claude picks up where it left off.

This is the ONE hook that absolutely must never silently fail — if the
flag isn't written, resume is disabled for this rate-limit window. The
guard below exits 0 with a stderr note rather than non-zero, because
Claude Code treats non-zero hook exits as blocking, and we'd rather
degrade (no resume cue) than block the session on a plugin misconfig.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    # All side-effecting code lives inside main() so the hook script is
    # safely importable. We put scripts/ (NOT scripts/lib/) on sys.path
    # and `from lib import state` so the CPV hook validator recognises
    # this as a local-sibling import. The validator's local_sibling
    # detector scans scripts/ for direct .py children and for subdirs
    # that contain __init__.py — `lib` is now a package thanks to
    # scripts/lib/__init__.py, so it counts as a local sibling and the
    # validator no longer demands a PEP 723 declaration for `state`.
    # (state is NOT on PyPI; declaring it in the `# /// script` block's
    # dependencies = [...] would break `uv run --script`.)
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        print(
            "[on-stop-failure] CLAUDE_PLUGIN_ROOT unset; resume cue will not be captured for this turn",
            file=sys.stderr,
        )
        return 0

    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    from lib import state  # noqa: E402  -- local package, not PyPI

    state.init_state()
    flag = state.state_dir() / "rate-limited.flag"
    flag.touch()
    state.atomic_write(state.state_dir() / "rate-limited-since.ts", str(int(time.time())))
    state.log_line(
        "stop-failure",
        "rate-limit captured; dispatch will emit resume cue on next heartbeat fire",
    )
    return 0


if __name__ == "__main__":
    # Bare main() rather than sys.exit(main()) — main() always returns 0
    # on this hook (the early CLAUDE_PLUGIN_ROOT guard returns 0 too), so
    # the natural exit code is 0. The CPV validator's _walk_module_scope
    # treats the body of `if __name__ == "__main__":` as module scope and
    # flags any sys.exit / raise SystemExit there as "kills the hook
    # process at import time". Dropping sys.exit silences the false
    # positive without changing exit-code behaviour for our hooks.
    main()
