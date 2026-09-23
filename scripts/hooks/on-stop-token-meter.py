#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Stop hook — the session token meter (TRDD-a4e41e89 Phase 1; widened by TRDD-DLI76AUC #4)
AND the turn-boundary /clear trigger (TRDD-11GAS4LC, issue #306).

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

TRDD-11GAS4LC / issue #306: the PreToolUse context guard (pre-tool-context-usage.py)
used to ALSO type ESC+/compact into the pane at the same 85% trip point the hardstop
denies at, racing the harness's own auto-compact (fleet observation: compaction fired
at 866k = CLAUDE_CODE_AUTO_COMPACT_WINDOW(900000) minus its ~34k summary overhead).
Owner ruling (TRDD-7MGJYLY5): prefer a turn-boundary `/clear` over a mid-turn
`/compact` race. So THIS hook — which already fires exactly once per turn boundary —
is where that decision now lives: above CLAUDE_PLUGIN_OPTION_CLEAR_AT_PCT (default 83,
capped below the harness's own forced-compact point) it launches the existing external
clear chain (`clear_trigger.spawn_shrink_chain`, SOFT + detached — never blocks this
hook's own budget), UNLESS a background agent is live or the user just interrupted,
which DEFER (and log why) up to CLAUDE_PLUGIN_OPTION_CLEAR_CEILING_PCT (default 92),
past which it clears regardless. The stated fallback while deferred below the ceiling
is the harness's own auto-compact plus the janitor's C-a continuity nudge — there is no
other lever here, and none is added: this hook only ever ASKS for a clear, it never
forces one past what `clear_trigger`'s own chain already guards.

This is a SEPARATE hook from the survival-critical on-stop / on-stop-failure
hooks ON PURPOSE: a meter bug must never be able to break rate-limit resume. It
reads only the transcript TAIL (never the whole multi-MB file), always exits 0,
and never raises — a failure here means one missing data point, nothing more. The
/clear trigger below follows the SAME contract: it is a second, independent try
block so a fault in it can never suppress the token-meter write, and vice versa.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_DEFAULT_CLEAR_AT_PCT = 83  # ~750k of a 900k window -- the owner's "around 750k" (TRDD-11GAS4LC)
_DEFAULT_CLEAR_CEILING_PCT = 92  # past this, clear regardless of a live agent / interrupt
# Mirrors token_meter._DEFAULT_COMPACT_SUMMARY_OVERHEAD (kept as a local literal rather than
# reaching into that module's private name): the compact routine's own summary write costs
# ~this many tokens, so the harness's forced auto-compact actually fires at (window -
# overhead), not at the window itself. The janitor's own trip point must stay STRICTLY below
# that, or the two race each other the same way issue #306 did.
_COMPACT_SUMMARY_OVERHEAD = 34_000
# Mirrors dispatch._KEEP_GOING_AGENT_STALE_DEFAULT -- an agent whose transcript is younger
# than this is "still working" everywhere else in this codebase; a different number here
# would let dispatch call an agent live while this hook called the same one dead.
_AGENT_LIVE_STALE_S = 900

_CLEAR_DIRECTIVE = (
    "read the injected SessionStart handoff summary FIRST (follow its wikimem/TRDD "
    "links via memgrep recall on demand), then resume your prior in-flight task."
)


def _coerce_pct(raw: str | None, default: int) -> int:
    """Best-effort 1-100 int; anything else (unset, junk, out of range) -> default."""
    if not raw:
        return default
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return val if 0 < val <= 100 else default


def _harness_window(env, token_meter) -> int:
    """CLAUDE_CODE_AUTO_COMPACT_WINDOW when the harness set it -- the value it ACTUALLY
    auto-compacts this session at -- else token_meter's 1M/200K fallback."""
    raw = env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "")
    try:
        val = int(raw)
        if val > 0:
            return val
    except (TypeError, ValueError):
        pass
    return token_meter.default_window(env)


def _pct_tokens(window: int, pct: int) -> int:
    """`pct`% of `window`, capped strictly below the harness's own forced-compact point."""
    if window <= 0:
        return 0
    raw = (window * pct) // 100
    ceiling = window - _COMPACT_SUMMARY_OVERHEAD
    return min(raw, ceiling) if ceiling > 0 else raw


def _maybe_clear(project_dir: str, transcript_path: str, state, token_meter) -> None:
    """At the turn boundary, launch the external /clear chain once context is at/above
    the clear point -- unless a live background agent or a fresh user interrupt says
    otherwise (both DEFER and log why), up to the ceiling past which it clears regardless.

    `count_toward_cooldown=True` (TRDD-RAEGS1D5 card 5): this is an AUTOMATIC clear, so it
    must stamp the shared `cold_cache_compact` cooldown -- previously it stamped NOTHING, so
    the cooldown the idle nudge (dispatch.py) and the daemon path both respect was blind to a
    clear fired from THIS turn boundary, letting a second automatic trigger re-fire seconds
    later. `spawn_shrink_chain` now owns the stamp itself, at spawn time, so passing True here
    is the whole fix -- no separate `mark_clear_fired` call needed in this hook.

    `recovered_after=int(time.time())` (TRDD-RAEGS1D5 card 5, orchestrator review item 2):
    this hook only runs after a Stop that SUCCEEDED -- proof this session already ran a full
    turn past whatever earlier rate-limit/API-error `on-stop-failure.py` may have flagged,
    however fresh `rate-limited.flag` still reads on its own 24h clock. Without this, one
    transient error could lock EVERY automatic clear at this turn-boundary out for up to a
    day, while the harness's own ~95%-context auto-compact fires instead. The idle-nudge path
    (`dispatch.py`) passes no such evidence and keeps the plain age veto.
    """
    try:
        tokens = token_meter.latest_context_size(transcript_path)
    except Exception:  # noqa: BLE001 -- a read fault must never block the tool call / turn
        tokens = None
    if not tokens:
        return

    window = _harness_window(os.environ, token_meter)
    if window <= 0:
        return
    clear_at_pct = _coerce_pct(os.environ.get("CLAUDE_PLUGIN_OPTION_CLEAR_AT_PCT"), _DEFAULT_CLEAR_AT_PCT)
    clear_at = _pct_tokens(window, clear_at_pct)
    if tokens < clear_at:
        return

    pct = int(tokens * 100 / window)
    ceiling_pct = _coerce_pct(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CLEAR_CEILING_PCT"), _DEFAULT_CLEAR_CEILING_PCT
    )
    ceiling = _pct_tokens(window, ceiling_pct)

    if tokens < ceiling:
        now = int(time.time())
        try:
            import pending_agents  # noqa: PLC0415 -- lazy; scripts/lib is already on path

            entries = pending_agents.load_pending(now)
            live = [e for e in entries if pending_agents.agent_is_live(e, now, _AGENT_LIVE_STALE_S)]
        except Exception:  # noqa: BLE001 -- a probe fault must never force a clear
            live = []
        if live:
            state.log_line(
                "token-meter",
                f"clear deferred: {len(live)} agent(s) live, {pct}% < ceiling {ceiling_pct}% "
                "-- fallback: harness auto-compact + C-a continuity nudge",
            )
            return
        try:
            import user_intent  # noqa: PLC0415

            secs = user_intent.recently_interrupted(project_dir, transcript_path=transcript_path)
        except Exception:  # noqa: BLE001
            secs = None
        if secs is not None:
            state.log_line(
                "token-meter",
                f"clear deferred: user interrupted {int(secs)}s ago -- fallback: harness "
                "auto-compact + C-a continuity nudge",
            )
            return
    else:
        state.log_line(
            "token-meter", f"clear: past ceiling ({pct}% >= {ceiling_pct}%) -- clearing regardless"
        )

    try:
        import clear_trigger  # noqa: PLC0415 -- lazy; scripts/ is already on path

        spawned, why = clear_trigger.spawn_shrink_chain(
            then=list(clear_trigger.BOOTSTRAP_CMDS),
            directive=_CLEAR_DIRECTIVE,
            transcript_path=transcript_path,
            count_toward_cooldown=True,
            recovered_after=int(time.time()),
        )
        state.log_line("token-meter", f"clear at {pct}% ({tokens} tokens): {'spawned' if spawned else 'NOT spawned'} -- {why}")
    except Exception as exc:  # noqa: BLE001 -- the chain launch must never break this hook
        state.log_line("token-meter", f"clear: chain launch failed ({exc})")


def main() -> int:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        return 0  # no plugin root → can't import lib; silently skip (never block)

    # Drain stdin (the Stop hook delivers a JSON payload with transcript_path).
    transcript_path = ""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                transcript_path = str(payload.get("transcript_path") or "")
                if not project_dir:
                    project_dir = str(payload.get("cwd") or "")
        except ValueError:
            transcript_path = ""
    if not transcript_path:
        return 0

    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    sys.path.insert(0, str(Path(plugin_root) / "scripts" / "lib"))

    # TRDD-ECHOKVZC: publish THIS session's pane -> transcript mapping on EVERY Stop (this hook
    # already fires at the end of every turn) so `pane_actuate.act` can find it when the fleet
    # actuator later considers typing into this pane -- without it, that actuator has no route
    # to `recently_interrupted` and bypasses the 300s user-interrupt cooldown. Best-effort: a
    # write fault must never break this hook, so every failure is swallowed here, independent
    # of the token-meter logic below.
    try:
        import user_intent  # noqa: PLC0415

        user_intent.record_pane_transcript(transcript_path)
    except Exception as exc:  # noqa: BLE001 -- a mapping-write fault must never break the hook
        # Coordinator review finding (TRDD-ECHOKVZC): a silently swallowed fault here would
        # leave the mapping never written, and `pane_actuate.act` would then fail open forever
        # with no trace. `scripts/lib` is already on `sys.path` (above), so `state` is reachable
        # in the common case; stderr is the fallback.
        try:
            from lib import state  # noqa: E402  -- local package, not PyPI

            state.log_line(
                "user_intent",
                f"record_pane_transcript failed in on-stop-token-meter: {type(exc).__name__}: {exc}",
            )
        except Exception:  # noqa: BLE001 -- defensive
            print(
                f"[on-stop-token-meter] record_pane_transcript failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    try:
        import token_meter  # noqa: E402
        from lib import state  # noqa: E402  -- local package, not PyPI

        usage = token_meter.tail_turn_usage(transcript_path)
        if usage is not None:
            state.init_state()
            # Same epoch reused for the sidecar write below -- it is the join key
            # `top_kind_totals` matches a fire-kind tag back to its token-meter.jsonl
            # record by (TRDD-NEVQOHGS box 3: the pinned schema forbids a `kind` field
            # on the record itself, see token_meter.append_kind_log's docstring).
            now_epoch = int(time.time())
            log_path = state.state_dir() / "token-meter.jsonl"
            token_meter.append_log(log_path, usage, now_epoch)
            token_meter.trim_log(log_path)
            if usage.is_heartbeat:
                kind = token_meter.detect_fire_kind(transcript_path)
                if kind is not None:
                    token_meter.append_kind_log(state.state_dir() / "token-meter-kind.jsonl", now_epoch, kind)
    except Exception as exc:  # never let the meter break a turn's completion
        sys.stderr.write(f"[on-stop-token-meter] skipped ({exc})\n")

    # Independent of the metering above (its own try/except, per the module docstring's
    # contract): a fault in the clear trigger must never suppress the token-meter write.
    try:
        import token_meter  # noqa: E402
        from lib import state  # noqa: E402

        _maybe_clear(project_dir, transcript_path, state, token_meter)
    except Exception as exc:  # noqa: BLE001 -- never let the clear trigger break a turn
        sys.stderr.write(f"[on-stop-token-meter] clear-check skipped ({exc})\n")
    return 0


if __name__ == "__main__":
    main()
