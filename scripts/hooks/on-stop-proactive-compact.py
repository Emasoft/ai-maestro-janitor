#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Stop hook — shrink a large context the moment the session goes idle (TRDD-D3PROACT).

THE PROBLEM (user 2026-07-17): a cron fire CANNOT compact before its own burn. A turn
re-reads the whole transcript to build its request BEFORE the model can call any tool, so
a cold fire has already paid the ~2x cache-creation write by the time dispatch.py runs.
The user's answer was right: *"if the chron cannot compact before a llm call happens, then
use a post compact hook or a sessionstart, or any possible event that can be useful."*

THIS IS THAT EVENT. Stop fires at the end of EVERY turn — while the cache is still WARM,
and BEFORE the next LLM call. Queueing a /compact here shrinks the context during a cheap
warm turn, so whatever comes next (an hour-later heartbeat, a rate-limit resume, a
restart) reads ~50k instead of ~600k. The burn is PREVENTED, not mitigated afterward.

WHY Stop BEATS THE HEARTBEAT PHASE for the motivating case: crons cannot fire mid-query,
so a >1h working turn builds a huge context with NO heartbeat in it; the cache then goes
cold during the idle that follows, and the next fire eats the write. Stop fires the
INSTANT that long turn ends — warm, before the gap — which is the one moment that can
prevent it. The heartbeat phase (dispatch._phase_proactive_idle_compact) remains as the
backstop for a session that goes idle later; both evaluate the SAME pure gate and share
ONE cooldown, so they can never double-compact. This mirrors the existing cold-cache
design, which already evaluates one decision at two trigger points (SessionStart + the
heartbeat rate-limit path).

GATES (the pure cold_cache_compact.should_compact_proactively_idle): the user must be
ABSENT from this pane (compaction is lossy — never fire out from under someone working;
a human turn leaves them present, so this stays silent during interactive work), nothing
may be pending (no resume / keep-going / directive / in-flight agent), and the context
must be large. Unattended agent + heartbeat turns are exactly the case that passes.

SEPARATE from the survival-critical on-stop / on-stop-failure hooks ON PURPOSE (the same
reason on-stop-token-meter is separate): a compact bug must NEVER be able to break
rate-limit resume. Always exits 0, never raises, reads only the transcript tail.
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

    try:
        sys.path.insert(0, str(Path(plugin_root) / "scripts"))
        sys.path.insert(0, str(Path(plugin_root) / "scripts" / "lib"))
        import cold_cache_compact  # noqa: E402
        import user_intent  # noqa: E402
        from lib import state  # noqa: E402  -- local package, not PyPI

        state.init_state()
        sd = state.state_dir()
        now = int(time.time())
        if not cold_cache_compact.proactive_idle_enabled() or cold_cache_compact.in_cooldown(sd, now=now):
            return 0
        # Cheap stat-only gates first — skip the transcript read entirely during
        # interactive work (the overwhelmingly common Stop).
        if user_intent.user_is_present(now=now):
            return 0
        if _active_waiting(sd, now):
            return 0

        ctx = cold_cache_compact.context_tokens_for(transcript_path)
        if ctx is None:
            ctx = cold_cache_compact.context_tokens_for(
                cold_cache_compact.newest_transcript(state.project_root())
            )
        # Stop is the RIGHT place to learn the floor: it is the first moment after a compaction
        # at which the resulting context size is observable at all (the post-compact size only
        # exists once a turn has run against it — PostCompact itself is too early to see it).
        floor = cold_cache_compact.refresh_floor(sd, ctx)
        if not cold_cache_compact.should_compact_proactively_idle(
            ctx,
            user_present=False,
            active_waiting=False,
            min_context_tokens=cold_cache_compact.min_context_tokens(),
            floor_tokens=floor,
            min_gain=cold_cache_compact.min_gain_tokens(),
        ):
            return 0

        compact_py = Path(plugin_root) / "scripts" / "compact_trigger.py"
        if not compact_py.is_file():
            return 0
        directive = (
            "proactive idle compaction: the turn ended with a large context and nobody at the "
            "keyboard, so it was compacted WHILE THE CACHE WAS WARM — the next cold resume is "
            "now cheap. Continue your prior pending task (read the newest in-flight TRDD's "
            "STATE block first)."
        )
        # 4s — deliberately WELL under this hook's 5s registered budget. compact_trigger
        # returns in under a second (its keystroke is detached internally), so 4s is already
        # generous; the point is that a Stop hook must never delay a turn's completion. On a
        # pre-2.1.210 CLI a hook timeout was misreported to the model as a USER REJECTION,
        # which stopped unattended sessions — the exact failure the janitor exists to prevent.
        # Overrun → no fire, no cooldown stamp → the heartbeat backstop retries. Fail-safe.
        proc = state.run_subprocess(
            [sys.executable, str(compact_py), "--directive", directive],
            timeout=4,
            capture=True,
            detector_name="on-stop-proactive-compact",
        )
        if not (proc and proc.returncode == 0 and "COMPACT_FIRED" in (proc.stdout or "")):
            # NO_ITERM / headless / trigger failed → no compaction happened, so do NOT stamp
            # the cooldown: a stamp with no compact would also suppress the SessionStart and
            # heartbeat trigger points. All three must agree on what "fired" means.
            return 0
        cold_cache_compact.mark_fired(sd, now=now)
        state.log_line("on-stop-proactive-compact", f"proactive idle compact fired at Stop (context={ctx})")
    except Exception as exc:  # never let this break a turn's completion
        sys.stderr.write(f"[on-stop-proactive-compact] skipped ({exc})\n")
        return 0
    return 0


def _active_waiting(sd: Path, now: int) -> bool:
    """Is something pending that must not be interrupted? Mirrors dispatch's
    _cadence_active_waiting on the signals a hook can cheaply read: a recent resume cue, an
    explicit keep-going opt-in, or a pending resume directive. Fail-CLOSED (any error →
    True → no compact): a lossy compaction must never fire on an unreadable state."""
    try:
        import pending_agents  # noqa: PLC0415
        from lib import state  # noqa: PLC0415

        last_resume = state.read_int_state(sd / "last-resume.ts", 0)
        if last_resume > 0 and 0 <= now - last_resume < 1800:
            return True
        if (sd / "keep-going").is_file():
            return True
        directive = sd / "resume-directive.txt"
        if directive.is_file() and directive.stat().st_size > 0:
            return True
        return len(pending_agents.pending_external(now)) > 0
    except Exception:
        return True  # unreadable → assume busy → never compact


if __name__ == "__main__":
    main()
