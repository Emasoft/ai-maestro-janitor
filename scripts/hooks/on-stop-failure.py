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

    # ACTIVE 429 RECOVERY (TRDD-G4BCRUP7 R9) — best-effort, STRICTLY AFTER the critical
    # flag write. Until now this hook was PASSIVE: it recorded the rate limit and waited for
    # "when the API is reachable again", i.e. for the window to RESET. On a spent 7-day
    # window that is days of a dead session, which is exactly the failure the owner's
    # directive names ("if it misses it, escape the error or the retry countdown so it can
    # resume with the rotated token").
    #
    # THE ROTATION MUST HAPPEN OUTSIDE A CLAUDE TURN, which is why it lives here and not in
    # dispatch: a heartbeat fire IS a turn, so on a rate-limited account the fire that was
    # supposed to trigger recovery hits the same 429 and dies with it. This hook is a plain
    # subprocess and is the only recovery point the rate limit cannot reach.
    #
    # `auto` is the right verb rather than a forced switch: it is self-guarding (no live
    # credential, no SAFE alternate, or an anti-thrash dwell ⇒ no-op) so it can never strand
    # the session on an account that is itself near a limit. It also calls
    # `burn_gate.observe_wall`, which records this 429 as an effective-cap sample — so the
    # limit we just hit LOWERS the bar at which the next proactive rotation fires. That is
    # what turns "escape after the limit" into "rotate before it": each miss teaches the
    # gate where the real wall is.
    #
    # Gated on the rotator opt-in flag: without it, `auto` would still read the live
    # credential, and on macOS a credential read can raise a keychain prompt — a user who
    # never enabled rotation must not get one because an unrelated API call failed.
    # Detached (Popen, no wait) for the same reason as the delegation below: the network
    # calls exceed this hook's budget, and a detached child costs it nothing.
    try:
        # `scripts/lib` MUST be on the path too, not just `scripts`: global_state.py does a
        # BARE `import state`, so `from lib import global_state` raises ModuleNotFoundError
        # with only `scripts` inserted (on-session-start.py:272-273 inserts both for this
        # exact reason). Caught by verification, not by review — the except below would have
        # swallowed it and this recovery would have been permanently dead while looking
        # shipped, which is the same silent-disable shape this whole card exists to remove.
        sys.path.insert(0, str(Path(plugin_root) / "scripts" / "lib"))
        from lib import global_state as _gs  # noqa: E402  -- local package, not PyPI

        rotator = Path(plugin_root) / "scripts" / "oauth_rotator" / "rotator.py"
        opt_in = _gs.global_state_dir().parent / "oauth-rotator" / "opt-in.flag"
        if opt_in.exists() and rotator.is_file():
            import subprocess  # noqa: PLC0415 -- only needed on this rare path

            subprocess.Popen(  # noqa: S603 -- fixed argv, feature-detected script
                ["uv", "run", "--script", "--quiet", str(rotator), "auto"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=state.detached_uv_env(),
            )
            state.log_line(
                "stop-failure",
                "rate limit: fired detached rotator auto (rotate away + learn the wall)",
            )
    except Exception:  # noqa: BLE001 -- recovery MUST NOT break the resume-cue capture
        pass

    # #J delegation (TRDD-PZLVT2RN Phase D) — best-effort, STRICTLY AFTER the critical
    # flag write. Inside an ai-maestro harness agent the SERVER owns Family-A resume, so
    # also tell it this turn died on an API error: `aimaestro-continuity.sh ensure-resume
    # <self>` (idempotent per the Q3 contract — a live agent is a no-op). Fired DETACHED
    # (Popen, no wait): the CLI's own worst case (~11-13 s) exceeds the 5 s hooks.json
    # budget, and a detached child costs this hook nothing (the F9 lesson). The janitor's
    # own flag machinery above STAYS — belt and suspenders; the server merely gets the
    # earlier, richer signal. Feature-detected: no CLI or no self id ⇒ silently skip.
    try:
        from lib import harness_backend  # noqa: E402  -- local package, not PyPI

        if harness_backend.is_harness_session():
            cli = harness_backend.continuity_cli()
            ref = harness_backend.self_agent_ref()
            if cli and ref:
                import subprocess  # noqa: PLC0415 -- only needed on this rare path

                subprocess.Popen(  # noqa: S603 -- fixed argv, feature-detected CLI
                    [cli, "ensure-resume", ref],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                state.log_line(
                    "stop-failure",
                    f"harness: fired detached ensure-resume for agent {ref}",
                )
    except Exception:  # noqa: BLE001 -- delegation MUST NOT break the resume-cue capture
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
