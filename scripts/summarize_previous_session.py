#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Summarize the PREVIOUS session's transcript at SessionStart (TRDD-2F3I2P18).

WHY THIS EXISTS AS ITS OWN ENTRY POINT. `external_handoff_clear.py` covers the case where the
JANITOR fires the clear. It cannot cover the case where a HUMAN ends a session — `/clear` has no
hook, and `claude -n` is a brand-new process. Both are the same event from the transcript's point
of view: a session stopped, its `.jsonl` is complete on disk, and the next session starts blank
beside it.

THE ORDERING IS THE POINT, and it is the owner's ruling of 2026-09-01. The new session is ALREADY
cheap — it starts at base context — so there is nothing to save by summarizing first. What must
not happen is the session picking up work before the summary lands, because then it does that work
blind and the injection arrives into a context that has already moved on. So: capture, hold,
summarize, release.

NOTHING HERE COSTS CLAUDE TOKENS. `llm-ext` runs out of process against its own free models; this
script's whole job is to name the source, take the hold, and wait.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402
import handoff_files  # noqa: E402
import state  # noqa: E402

_LOG = "session-summary"


def previous_transcript(root: Path, current_session_id: str) -> Path | None:
    """The newest transcript that is NOT this session's.

    `current_session_id` is excluded by STEM, not by mtime: at SessionStart the new transcript may
    already exist and may already be the newest, so "newest" alone would summarize the blank
    session that just started — the same empty-source trap the post-clear path guards against,
    arriving by a different route.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415

        newest = cold_cache_compact.newest_transcript(root)
        if newest is None:
            return None
        parent = newest.parent
        candidates = [
            p for p in parent.glob("*.jsonl")
            if p.is_file() and p.stat().st_size > 0 and current_session_id not in p.stem
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except (OSError, ValueError, ImportError):
        return None


def main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    sd = state.state_dir()
    now = int(time.time())
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    prev = previous_transcript(root, session_id)
    if prev is None:
        state.log_line(_LOG, "no previous transcript to summarize — nothing to do")
        return 0

    key = handoff_files.session_key(str(prev))
    # ALREADY SUMMARIZED? Do not pay for it twice. A session that restarts several times in a row
    # would otherwise re-summarize the same transcript on every start, which is exactly the kind
    # of repeated external work this whole card exists to stop paying for.
    if any(p.is_file() for p in handoff_files.newest_group(sd) if key and key in p.name):
        state.log_line(_LOG, f"a handoff already exists for {key} — skipping")
        return 0

    pending = ehc._capture_summary_source(sd, {"transcript": str(prev)}, now)
    if pending is None:
        state.log_line(_LOG, f"previous transcript unreadable ({prev}) — no hold taken")
        return 0

    print(f"SUMMARY_HOLD_TAKEN {prev.name}")
    state.log_line(_LOG, f"holding this session while llm-ext summarizes {prev.name}")

    # The retry deadline is the HOLD's deadline, not a separate budget. Two independent timeouts
    # would guarantee one of them is wrong: a longer retry than hold means the summary lands after
    # the session already degraded and gets written for nobody, and a shorter one wastes the
    # remaining hold doing nothing. One clock, read from the record that is already on disk.
    got = ec.summarize_with_retry(str(prev), deadline=float(pending["expires"]))
    text = (got.text or "").strip()
    if not text:
        # The hold's TTL releases the session onto the mechanical handoff. Do NOT clear the hold
        # early here: an immediate release would hand the session a blank context with no
        # explanation, whereas letting the TTL expire produces the documented degrade path.
        state.log_line(
            _LOG,
            f"llm-ext produced no summary ({got.outcome}: {got.detail}) — leaving the hold to "
            "expire onto the mechanical precompact handoff",
        )
        print("SUMMARY_FAILED degrading to the mechanical handoff on TTL")
        return 0

    handoff_files.write(sd, key or handoff_files.UNKEYED_KEY, text, now=now)
    ehc._release_summary_hold(sd)
    print(f"SUMMARY_READY {len(text.encode('utf-8'))}B for {prev.name}")
    state.log_line(_LOG, f"summary ready ({len(text)} chars) — hold released")
    return 0


if __name__ == "__main__":
    sys.exit(main())
