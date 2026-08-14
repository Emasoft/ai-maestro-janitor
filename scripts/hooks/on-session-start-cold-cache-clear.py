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

        if not ec.enabled():
            return 0
        root = Path(cwd) if cwd else Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd())
        state.set_project_dir_override(str(root))
        sd = state.state_dir()

        # Guard 2 — one fire per session id, whatever SessionStart does. `emit_once` returns
        # None on a repeat, which is exactly "already fired for this session".
        key = f"cold-cache-clear@{session_id or 'no-session-id'}"
        already = dedupe.emit_once(sd / _FIRED_STAMP, key, "x") is None

        newest = cold_cache_compact.newest_transcript(root)
        verdict = ec.should_clear_on_resume(
            source=source,
            # The ONE subprocess, and only once the local facts have failed to refuse. It costs a
            # bounded ~20 s worst case, which is why it must not run on the `compact` path above.
            cache_expired=None if already else ec.cache_certainly_expired(root),
            context_tokens=cold_cache_compact.context_tokens_for(newest),
            min_context=ec.min_context_tokens(),
            in_cooldown=cold_cache_compact.clear_in_cooldown(sd, now=int(time.time())),
            already_fired_this_session=already,
        )
        state.log_line(
            "cold-cache-clear",
            f"source={source} fire={verdict.fire} trigger={verdict.trigger or '-'} why={verdict.why}",
        )
        if not verdict.fire:
            return 0

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
        # LAUNCHED UNDER THE MANAGED INTERPRETER, NEVER `uv run` (TRDD-DB1P25S4 / GH#92). This
        # child's whole purpose is to drive osascript to type into iTerm, and macOS TCC persists
        # an Automation grant against a STABLE client binary. `uv run --script` mints a fresh
        # ephemeral `~/.cache/uv/builds-v0/.tmpXXXX/bin/python` on every respawn, so the grant
        # can never attach to the same client twice and every injection is denied — uv is a
        # LAUNCHER, and a launcher can never be the grantee. Falling back to `uv` when no managed
        # interpreter resolves is deliberate: a watcher that runs and gets denied at least logs
        # the denial, where no watcher at all is silent.
        managed = gs._managed_python_path()
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
