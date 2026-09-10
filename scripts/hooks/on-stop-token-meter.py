#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Stop hook — the session token meter (TRDD-a4e41e89 Phase 1; widened by TRDD-DLI76AUC #4).

Fires at the end of EVERY turn, sums that turn's token usage from the transcript
tail, and appends one line to `$PROJECT/.janitor/state/token-meter.jsonl`, tagged
`heartbeat: true|false`. `/janitor-token-report` and the token-usage-anomaly
detector read it.

It used to log heartbeat turns ONLY. That made the janitor's own cost telemetry
blind to every INTERACTIVE turn — including a user-typed `/janitor-arm`, i.e.
precisely the turn TRDD-DLI76AUC set out to make cheaper, which could therefore
be argued about but not measured. The same blindness silently under-counted the
report's rolling 5h/7d window sums, since the user's own turns are usually the
expensive ones. Consumers that still want only the beat can filter on the tag;
they must default a MISSING tag to True, because every record written before this
change was a heartbeat.

This is a SEPARATE hook from the survival-critical on-stop / on-stop-failure
hooks ON PURPOSE: a meter bug must never be able to break rate-limit resume. It
reads only the transcript TAIL (never the whole multi-MB file), always exits 0,
and never raises — a failure here means one missing data point, nothing more.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        return 0  # no plugin root → can't import lib; silently skip (never block)

    # Drain stdin (the Stop hook delivers a JSON payload with transcript_path).
    transcript_path = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                transcript_path = str(payload.get("transcript_path") or "")
        except ValueError:
            transcript_path = ""
    if not transcript_path:
        return 0

    try:
        sys.path.insert(0, str(Path(plugin_root) / "scripts"))
        sys.path.insert(0, str(Path(plugin_root) / "scripts" / "lib"))
        import token_meter  # noqa: E402
        from lib import state  # noqa: E402  -- local package, not PyPI

        usage = token_meter.tail_turn_usage(transcript_path)
        if usage is None:
            return 0  # turn boundary not found in the tail → nothing to log

        state.init_state()
        log_path = state.state_dir() / "token-meter.jsonl"
        token_meter.append_log(log_path, usage, int(time.time()))
        token_meter.trim_log(log_path)
    except Exception as exc:  # never let the meter break a turn's completion
        sys.stderr.write(f"[on-stop-token-meter] skipped ({exc})\n")
        return 0
    return 0


if __name__ == "__main__":
    main()
