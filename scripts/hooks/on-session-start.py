#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""SessionStart hook — Python port of on-session-start.sh.

Initializes .janitor state and reminds Claude to arm the heartbeat cron
if this is a fresh session. Runs as part of the plugin's hook lifecycle,
NOT at cron-fire time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    # All side-effecting code lives inside main() so the hook script is
    # safely importable (no module-scope sys.exit, no module-scope
    # third-party imports). The PEP 723 dependency-completeness check
    # only inspects module-scope imports, so doing `import state` below —
    # AFTER sys.path is extended with scripts/lib/ — keeps the validator
    # from flagging `state` as a missing PyPI dependency. (`state` is a
    # LOCAL module under scripts/lib/, not on PyPI; declaring it in the
    # PEP 723 `dependencies` block would break `uv run --script`.)
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        print(
            "[on-session-start] CLAUDE_PLUGIN_ROOT unset; skipping",
            file=sys.stderr,
        )
        return 0

    # Put scripts/ on sys.path (NOT scripts/lib/) and import via the
    # `lib` package so the CPV hook validator recognises this as a
    # local-sibling import. The validator's local_sibling detector
    # scans scripts/ for direct .py children and subdirs that contain
    # __init__.py — `lib` is now a package thanks to scripts/lib/__init__.py.
    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    from lib import rules_installer, state  # noqa: E402  -- local package, not PyPI

    state.init_state()

    # Clear any stale flag from a prior session crash. If the last session
    # ended mid-rate-limit, the flag is preserved and the heartbeat cron
    # will emit a resume cue on its next fire — which is what we want.
    # So only clear flags that cannot represent valid cross-session state.
    keepalive = state.state_dir() / "keepalive-sent.flag"
    try:
        keepalive.unlink()
    except FileNotFoundError:
        pass

    # Propagate the plugin's shipped rules (rules/*.md) into the active
    # scope's .claude/rules/ directory so Claude Code's rule loader picks
    # them up on the next session-start. `install_rules` is idempotent:
    # files already present at the destination are LEFT ALONE so a user
    # who edited the rule keeps their version. Adding new rule files to
    # the plugin and shipping a release is enough to roll them out — no
    # explicit migration step required.
    copied = rules_installer.install_rules(Path(plugin_root))
    if copied:
        state.log_line(
            "session-start",
            f"installed plugin rule(s): {', '.join(copied)}",
        )

    # OAuth-rotator supervisor FAST-PATH (TRDD-32acd15f, P2). The daemon Task
    # runs the same alert-only governance on a 10-min cadence; firing it here too
    # surfaces the human-actionable conditions (pinning env var, expiring
    # setup-token, opted-in non-macOS host) the moment ANY session starts. Since
    # TRDD-f892e109 decision 3 the supervisor heals nothing — the daemon's 60 s
    # oauth-rotator-tick Task owns rotation — so this is purely a "surface the
    # alerts early" path. TOTAL no-op unless /janitor-auto-manage-oauth-on wrote
    # the opt-in flag. Best-effort and fully isolated: any failure here must
    # NEVER disrupt session start, so it is wrapped and swallowed.
    try:
        sys.path.insert(0, str(Path(plugin_root) / "scripts" / "oauth_rotator"))
        import supervisor as oauth_supervisor  # noqa: E402  -- local module, not PyPI

        _facts = oauth_supervisor.gather_facts()
        if _facts.opt_in:
            _findings = oauth_supervisor.diagnose(_facts)
            if _findings:
                _res = oauth_supervisor.apply(
                    _findings,
                    log=lambda m: state.log_line("session-start", m),
                )
                state.log_line(
                    "session-start",
                    f"oauth-rotator-supervisor (fast-path): "
                    f"alerts={_res.alerts or '[]'}",
                )
    except Exception as exc:  # noqa: BLE001 -- best-effort; never break session start
        state.log_line("session-start", f"oauth-supervisor fast-path skipped: {exc}")

    # `last-activity.ts` was previously written here too, but no detector
    # ever read it — dropped to avoid carrying dead state. The
    # session-start nudge below is what callers actually rely on.
    state.log_line("session-start", f"state initialized at {state.state_dir()}")

    # Stdout from this hook becomes additional context for the first user
    # turn. Remind Claude to arm the heartbeat cron. /janitor-arm is
    # idempotent, so even if the durable cron survived a previous
    # session, re-arming is safe.
    print(
        "[ai-maestro-janitor] The janitor heartbeat keeps drift detection and rate-limit recovery "
        "running in this session. If you have not done so yet (or if the previous cron hit its 7-day "
        "auto-expiry), run /janitor-arm to arm it. The skill is idempotent — safe to re-run."
    )
    return 0


if __name__ == "__main__":
    # Bare main() — see on-stop-failure.py for the rationale (CPV's
    # _walk_module_scope flags sys.exit inside `if __name__ == "__main__":`
    # as module-scope; main() always returns 0 here so dropping sys.exit
    # is behaviour-neutral).
    main()
