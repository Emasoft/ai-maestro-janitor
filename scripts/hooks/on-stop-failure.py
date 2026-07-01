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
    now = int(time.time())
    state.atomic_write(state.state_dir() / "rate-limited-since.ts", str(now))
    state.log_line(
        "stop-failure",
        "rate-limit captured; dispatch will emit resume cue on next heartbeat fire",
    )

    # Best-effort — STRICTLY AFTER the critical flag write above, wrapped so a logging
    # bug can NEVER break the resume-cue capture (this hook's one hard contract). Snapshot
    # the 5h/7d token windows at this turn-ending API error; over time the MAX 5h/7d sum
    # across these events reveals the empirical Opus-4.8 window cap — "log when the window
    # is exhausted before the time" (TRDD-EDSFEQ5C). A non-rate-limit error logs a
    # low-usage snapshot that doesn't move the max, so the cap estimate stays sound.
    try:
        from lib import token_baseline, token_meter  # noqa: E402  -- local package

        records = token_meter.load_log(state.state_dir() / "token-meter.jsonl")
        token_meter.append_exhaustion_event(
            state.state_dir() / "window-exhaustion.jsonl",
            {
                "ts": now,
                "roll_5h": token_baseline.rolling_sum(records, 5 * 3600, now),
                "roll_7d": token_baseline.rolling_sum(records, 7 * 86400, now),
                "n": len(records),
            },
        )
    except Exception:  # noqa: BLE001 -- telemetry MUST NOT break the resume-cue capture
        pass
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
