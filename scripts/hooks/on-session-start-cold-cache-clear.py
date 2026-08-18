#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""SessionStart hook — shrink a session RESUMED onto a dead prompt cache, before its first turn.

THE WINDOW THIS EXISTS FOR, and why nothing else can cover it. When Claude Code is launched
after being away, the whole prior conversation is reloaded. If the prompt cache died while it
was closed, the VERY FIRST turn re-reads all of it at full price — on a ~700k session, across a
fleet of concurrent sessions, that is the single most expensive event the janitor can prevent.
It is preventable only in the gap between "loaded" and "first turn", and nothing else watches
that gap: the cron dispatcher runs INSIDE a turn (the cost is already paid by the time it
executes), and so does every in-model lever.

WHAT THIS HOOK DOES NOT DO: the work itself. A hook gets seconds; composing the summary is a
map-reduce over the transcript that takes minutes, and a hook cannot type `/clear` at all. So
this decides and DETACHES, handing the whole job to `external_handoff_clear.py`, which composes
the handoff and then drives the ratified injection chain (`/clear`, wait for the fresh session,
type the bootstrap).

THE LOOP GUARD IS THE POINT. `SessionStart` also fires with `source=compact` and `source=clear`
— re-entries into a session that was JUST shrunk. Acting on those is an infinite loop: shrink →
SessionStart(compact) → shrink → … On this machine `compact` is not a theoretical risk, it is
the MOST COMMON source (measured 38 compact / 7 resume / 3 clear / 0 startup), so a hook that
merely forgot to exclude it would loop on its very first day. `external_clear.RESUME_SOURCES`
holds the allow-list and `should_clear_on_resume` enforces it; a second guard (a per-session-id
stamp) makes a repeated delivery of the SAME session a no-op too.

THE USER'S PRESENCE IS NOT CONSULTED, HERE OR ANYWHERE BELOW IT (owner, 2026-08-13). The
injector already handles keystrokes correctly — it defers 8 s from the last one and retries,
never cancelling — and a refusal at this layer would never reach it. That asymmetry is exactly
what left this whole feature dead before.

FAIL-OPEN THROUGHOUT: every failure path leaves the session untouched. A hook that breaks
SessionStart is worse than a cache miss.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
for _entry in (
    str(_PLUGIN_ROOT / "scripts"),
    str(_PLUGIN_ROOT / "scripts" / "lib"),
):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

# The stamp that makes a repeated SessionStart for one session a no-op. Lives beside the other
# per-project janitor state so it is swept with everything else.
_FIRED_STAMP = "cold-cache-clear-fired.txt"


def _fire_recorded(seen_file: Path, key: str) -> bool:
    """Has a fire ALREADY been recorded for `key`? READ-ONLY — never records.

    Deliberately not `dedupe.emit_once(...) is None`: that writes the key as a side effect of
    asking, which is what made a single non-firing SessionStart permanently disable the lever
    for a long-lived session. Fails OPEN (returns False) on any read error — a lost marker
    costs at most one extra clear, while a spurious True costs the whole feature, silently."""
    try:
        return key in seen_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False


def _payload() -> dict:
    """The hook's stdin JSON, or {} when there is none. Never raises."""
    try:
        if sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001 -- a malformed payload must not break session start
        return {}


def main() -> int:
    data = _payload()
    source = str(data.get("source", "") or "").strip()
    session_id = str(data.get("session_id", "") or "").strip()
    cwd = str(data.get("cwd", "") or "").strip()

    # CHEAPEST GATE FIRST, and deliberately before any import that touches the filesystem: the
    # overwhelmingly common sources are `compact` and `clear`, and for those this hook must cost
    # essentially nothing. Reading state or probing a CLI for a fire we are about to refuse
    # would tax every compaction on the machine to serve the rare resume.
    try:
        import external_clear as ec  # noqa: PLC0415
    except Exception:  # noqa: BLE001 -- lib unavailable => feature simply absent
        return 0
    if source not in ec.RESUME_SOURCES:
        return 0

    try:
        import cold_cache_compact  # noqa: PLC0415
        import dedupe  # noqa: PLC0415
        import global_state as gs  # noqa: PLC0415 -- for the TCC-stable interpreter, see below
        import state  # noqa: PLC0415

        root = Path(cwd) if cwd else Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd())
        state.set_project_dir_override(str(root))
        sd = state.state_dir()

        # A disabled refusal MUST leave a trace (incident 2026-08-15: the feature shipped with
        # DEFAULT_ENABLED=False, the owner restarted a whole fleet expecting it, and every
        # session refused here SILENTLY — 7M tokens of cold re-reads with nothing anywhere
        # saying "the switch is off". One log line per resume is what makes a dark feature
        # distinguishable from a broken one.)
        if not ec.enabled():
            state.log_line(
                "cold-cache-clear",
                f"source={source} fire=False why=disabled "
                f"(set {ec.ENABLED_ENV}=true to enable the cold-cache clear)",
            )
            return 0

        # Guard 2 — one fire per session id, whatever SessionStart does.
        #
        # READ-ONLY here; the key is RECORDED only after `verdict.fire` is true (below). It used
        # to be written by an `emit_once` at THIS point, which consumed the session's single
        # allowance on the FIRST SessionStart regardless of outcome. Measured 2026-08-18: this
        # session recorded its key on a run whose verdict was `cache warm` — nothing was cleared
        # — and because a RESUMED session keeps its id indefinitely, every later reload logged
        # `already fired for this session` and the lever stayed dead for two days. The user
        # restarted after a 24 h gap, when the cache was certainly cold, and still got nothing:
        # this guard is checked BEFORE the cache check, so a stale key short-circuits a verdict
        # that would otherwise have fired.
        #
        # The guard's real job is narrow — make a DOUBLE-DELIVERED SessionStart a no-op — and a
        # marker named `…-fired` must therefore record FIRES, not ATTEMPTS.
        key = f"cold-cache-clear@{session_id or 'no-session-id'}"
        already = _fire_recorded(sd / _FIRED_STAMP, key)

        newest = cold_cache_compact.newest_transcript(root)
        now = int(time.time())
        # The probe answers when it can and WINS when it does; elapsed time is the fallback that
        # makes this lever reachable at all on a host without agentlensPro (TRDD-CEWVQ8DG). Before
        # this, an abstaining probe logged `why=cache state unknown — not clearing` and a whole
        # fleet of cold resumes each paid a full cache-creation write on its first turn.
        cache_expired = (
            None
            if already
            else ec.resolve_cache_expired(
                # The ONE subprocess, and only once the local facts have failed to refuse. It costs
                # a bounded ~20 s worst case, which is why it must not run on the `compact` path
                # above.
                ec.cache_certainly_expired(root),
                last_turn_age_s=cold_cache_compact.transcript_age_s(newest, now=now),
                ttl_minutes=ec.read_ttl_minutes(sd),
            )
        )
        verdict = ec.should_clear_on_resume(
            source=source,
            cache_expired=cache_expired,
            context_tokens=cold_cache_compact.context_tokens_for(newest),
            min_context=ec.min_context_tokens(),
            # `now`, not a second `time.time()`: one decision reads one clock, so the age and the
            # cooldown can never be judged against instants that straddle a second boundary.
            in_cooldown=cold_cache_compact.clear_in_cooldown(sd, now=now),
            already_fired_this_session=already,
        )
        state.log_line(
            "cold-cache-clear",
            f"source={source} fire={verdict.fire} trigger={verdict.trigger or '-'} why={verdict.why}",
        )
        if not verdict.fire:
            return 0

        # RECORD THE ONE-SHOT HERE — past the fire decision, so a refused verdict leaves the
        # allowance intact for the next SessionStart of this same (possibly long-lived) session.
        dedupe.emit_once(sd / _FIRED_STAMP, key, "x")

        watcher = _PLUGIN_ROOT / "scripts" / "external_handoff_clear.py"
        if not watcher.is_file():
            state.log_line("cold-cache-clear", f"watcher missing at {watcher} — nothing fired")
            return 0
        # BLOCKING, NOT DETACHED (owner directive 2026-08-13: *"of course this means to have a
        # huge timeout on all hooks, and making them blocking"*). Detaching here defeats the
        # entire feature: the hook would return 0, Claude Code would accept the first prompt, and
        # that turn re-reads the whole cold-cache conversation at full price — the exact ~700k
        # burn this exists to prevent — while the detached child was still composing the handoff
        # it would then use to clear a session that had ALREADY paid. The cost is only incurred
        # by a TURN, so the summarize must finish before one can start, which means waiting.
        #
        # The wait is bounded and the bound is chosen against the harness, not against hope:
        # `hooks.json` states this hook's OWN `timeout:` explicitly (2800 s), and it MUST stay
        # STRICTLY GREATER than `ec.DEFAULT_SUMMARY_DEADLINE_S` (2600 s) — NOT equal (USER
        # directive, TRDD-YOZ9TS3W). Past the deadline the watcher's fallback path composes the
        # network-free TEMPLATE handoff and fires the clear chain — and that compose-and-clear
        # work happens AFTER the deadline expires, so it needs its OWN headroom on top of the
        # deadline. 2800 = 2600 (the deadline) + ~200 s to run that fallback path to completion.
        # If the hook's timeout equalled the deadline exactly, Claude Code would kill the hook at
        # the very moment the fallback path begins — producing NO handoff and NO clear, which is
        # the one failure mode this whole feature must never have. Do NOT "tidy" this to match
        # the deadline exactly; the gap is load-bearing, not slack.
        #
        # (TRDD-YOZ9TS3W: this comment previously claimed the deadline "sits under Claude Code's
        # 600 s default `command`-hook timeout", which was false — `hooks.json` declared 120 s
        # here, far too short to let even one `LLM_EXT_TIMEOUT_S` attempt finish, and nobody had
        # checked the actual config against the claim.)
        #
        # Blocking here does NOT stall the janitor's other SessionStart hooks: the docs state
        # that all matching hooks run in parallel, so the drift/TRDD/watchpath hooks proceed
        # while this one waits.
        #
        # `--on-resume` tells the watcher to use the resume gate rather than the
        # abandoned-session one (which requires a long idle age that a just-loaded session
        # can never have).
        #
        # LAUNCHED UNDER A STABLY SIGNED INTERPRETER, NEVER `uv` (TRDD-DB1P25S4 / GH#92, and
        # the 2026-08-16 correction in `global_state.automation_python_path`). This child's
        # whole purpose is to drive osascript to type into iTerm, and macOS TCC persists an
        # Automation grant against a stable client IDENTITY — not merely a stable path. uv is a
        # LAUNCHER and a launcher can never be the grantee; worse, uv's managed CPython is
        # itself ad-hoc signed (`Identifier=-`), so pointing at it directly still leaves TCC
        # nothing durable to bind. Falling back when nothing better resolves is deliberate: a
        # watcher that runs and gets denied at least logs the denial, where no watcher at all
        # is silent.
        managed = gs.automation_python_path()
        argv = (
            [managed, str(watcher)]
            if managed
            else ["uv", "run", "--script", "--quiet", str(watcher)]
        )
        subprocess.Popen(  # noqa: S603 -- fixed argv, feature-detected script
            [*argv, "--project-root", str(root), "--on-resume"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=state.detached_uv_env(),
        )
        state.log_line("cold-cache-clear", f"fired detached watcher for {root}")
    except Exception as exc:  # noqa: BLE001 -- NEVER break session start
        try:
            import state  # noqa: PLC0415

            state.log_line("cold-cache-clear", f"skipped: {exc}")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
