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


def _active_global_stop(gs) -> tuple[str, str, int] | None:
    """(kind, reason, since_epoch) for the active machine-wide stop, or None.

    Read STRAIGHT from the flag file so the SessionStart reminder can name WHEN the
    stop was set and WHY. The bare "the janitor is stopped" line this replaces was
    ignored for ~33 h once (the disarmed-and-forgotten failure): a temporary
    /janitor-global-disarm for a token-burn fix was never re-armed, and nothing carried
    the duration or reason that would have made it stick. Kill-switch (disarm) dominates
    a pause when both are set. Pure read; a stat/read failure degrades to empty, never
    raises — this must never break session start.
    """
    gsd = gs.global_state_dir()
    for kind, fname in (("DISARMED", "kill-switch.flag"), ("PAUSED", "global-pause.flag")):
        p = gsd / fname
        if not p.exists():
            continue
        try:
            reason = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            reason = ""
        try:
            since = int(p.stat().st_mtime)
        except OSError:
            since = 0
        return (kind, reason, since)
    return None


def _format_stop_reminder(kind: str, reason: str, since: int, now: int) -> str:
    """Build the rich SessionStart disarmed-state reminder. Pure (clock + flag data are
    passed in) so it unit-tests without touching the filesystem or the real clock. Names
    the duration (days+hours) and the reason so a forgotten temporary stop is impossible
    to miss — the bare line it replaces carried neither and was ignored for ~33 h."""
    import time  # stdlib -- local keeps module scope import-clean

    ago = ""
    if since > 0:
        secs = max(0, now - since)
        days, hours = secs // 86400, (secs % 86400) // 3600
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(since))
        ago = f" since {when} ({days}d {hours}h ago)" if days else f" since {when} ({hours}h ago)"
    reason_str = f' — reason: "{reason}"' if reason else ""
    return (
        f"⚠ [ai-maestro-janitor] The janitor is globally {kind}{ago}{reason_str}. "
        "Drift detection, rate-limit recovery, and post-compaction auto-resume are OFF "
        "until you run /janitor-global-arm (or /janitor-global-unpause). "
        "(SessionStart safety net so a temporary stop can't silently persist.)"
    )


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
    from lib import global_state as gs  # noqa: E402  -- local package, not PyPI
    from lib import memory_scopes, rules_installer, state  # noqa: E402  -- local package, not PyPI

    state.init_state()

    # Seed this project's reload-ack to the CURRENT reload generation at a TRUE
    # session start: a fresh process has just loaded the current plugin versions,
    # so the heartbeat's `[janitor-reload]` nudge should fire only for updates
    # that land AFTER now — not replay a past update. Seed ONLY on a fresh load
    # (startup/resume); a `compact` or `clear` keeps the same plugins loaded in
    # the SAME process, so re-seeding then would wrongly mark a since-gone-stale
    # session "current" and suppress the reload it actually needs. The hook input
    # JSON (on stdin) carries `source`; read it best-effort and never block a TTY.
    import json  # noqa: E402  -- stdlib

    source = "startup"
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                source = str(json.loads(raw).get("source", "startup"))
    except Exception:  # noqa: BLE001 -- best-effort; never break session start
        source = "startup"
    if source in ("startup", "resume"):
        state.atomic_write(state.state_dir() / "reload-acked.ts", str(gs.reload_generation()))
        # Same seed for the STANDALONE-skills reload generation (TRDD-LQU7OXXV): a
        # fresh process already carries the current non-plugin skills, so it should
        # act on `[janitor-reload-skills]` only for a /janitor-global-reload-skills
        # issued AFTER now — not replay a past one.
        state.atomic_write(
            state.state_dir() / "skills-reload-acked.ts", str(gs.skills_reload_generation())
        )

    # Clear any stale flag from a prior session crash. If the last session
    # ended mid-rate-limit, the flag is preserved and the heartbeat cron
    # will emit a resume cue on its next fire — which is what we want.
    # So only clear flags that cannot represent valid cross-session state.
    keepalive = state.state_dir() / "keepalive-sent.flag"
    try:
        keepalive.unlink()
    except FileNotFoundError:
        pass

    # Record this session's terminal identity (TRDD-dccb0b8a NPT) so the GLOBAL
    # daemon's session-liveness watchdog knows WHICH pane to inject recovery into
    # if this session ever freezes. The 2026-06-20→21 freeze proved a dead
    # in-session cron cannot rescue itself; the daemon must reach in from outside,
    # and it can only target a pane it can name. A detached daemon cannot read
    # this session's environment, and TMUX_PANE / ITERM_SESSION_ID do not
    # propagate to arbitrary subprocesses — only this hook, spawned by the session
    # at start, sees them. Best-effort; a failure must never break session start.
    try:
        from lib import session_liveness  # noqa: E402  -- local package, not PyPI

        ident = session_liveness.capture_terminal_identity(os.environ)
        if ident:
            import time  # noqa: E402  -- stdlib

            ident["pid"] = str(os.getppid())  # the session process, not this hook
            ident["recorded_at"] = str(int(time.time()))
            state.atomic_write(
                state.state_dir() / "terminal-identity.json",
                json.dumps(ident, separators=(",", ":")),
            )
    except Exception as exc:  # noqa: BLE001 -- best-effort; never break session start
        state.log_line("session-start", f"terminal-identity capture skipped: {exc}")

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

    # Partial-uninstall self-heal (TRDD-H9IBY95W): remove provenance-marked janitor
    # rules from any KNOWN .claude/rules/ dir the janitor is NO LONGER installed into
    # (e.g. the project scope after a project-scope uninstall while still user-installed,
    # or a redundant project mirror of a user-scope rule per issue #36). Marker-gated,
    # so a user's own rule and every MEMORY store are untouched. Full last-scope
    # uninstall can't self-heal from a hook (the plugin is gone) — the daemon's
    # cleanup_user_orphans_if_uninstalled + each rule's own inert-guard cover that.
    removed = rules_installer.remove_orphaned_rules()
    if removed:
        state.log_line(
            "session-start",
            f"removed orphaned janitor rule(s) from non-install scope(s): {', '.join(removed)}",
        )

    # USER-memory backup MIRROR (TRDD-GFT33HT9): keep `~/.claude/ai-maestro-janitor-memory/`
    # in sync with the canonical corpus in the plugin DATA dir, so a plain `claude plugin
    # uninstall` (which deletes the data dir) never loses memory — and on a fresh install
    # with an empty primary, RESTORE it from the mirror. Additive, best-effort, NEVER
    # deletes a note; a mirror hiccup can't break session start.
    synced = memory_scopes.sync_user_memory_mirror()
    if synced == "restored":
        state.log_line(
            "session-start",
            "restored USER memory from the uninstall-safe mirror (primary was empty)",
        )

    # Self-heal the lean-ctx shell allowlist (TRDD-ZGLCGC6A). On a machine that
    # runs the lean-ctx Bash-allowlist wrapper, the heartbeat cron's bare
    # `dispatcher-stub.py` invocation is BLOCKED until the allowlist permits it,
    # which can stall an armed session (and tempts dangerous bypasses like
    # `shell_security=off`). The ONLY correct fix is the ADDITIVE
    # `lean-ctx allow <cmd>`, so we run it here once per janitor-required token.
    # No-op when lean-ctx is absent or the feature is disabled, and it NEVER
    # disables shell security. Best-effort and fully isolated: any failure must
    # NEVER disrupt session start, so it is wrapped and swallowed.
    try:
        from lib import leanctx_allowlist  # noqa: E402  -- local package, not PyPI

        allowed = leanctx_allowlist.ensure_janitor_allowed()
        if allowed:
            state.log_line(
                "session-start",
                f"lean-ctx allowlist self-heal: ensured {', '.join(allowed)}",
            )
    except Exception as exc:  # noqa: BLE001 -- best-effort; never break session start
        state.log_line("session-start", f"lean-ctx allowlist self-heal skipped: {exc}")

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
                    f"oauth-rotator-supervisor (fast-path): alerts={_res.alerts or '[]'}",
                )
    except Exception as exc:  # noqa: BLE001 -- best-effort; never break session start
        state.log_line("session-start", f"oauth-supervisor fast-path skipped: {exc}")

    # `last-activity.ts` was previously written here too, but no detector
    # ever read it — dropped to avoid carrying dead state. The
    # session-start nudge below is what callers actually rely on.
    state.log_line("session-start", f"state initialized at {state.state_dir()}")

    # Stdout from this hook becomes additional context for the first user turn. Normally we
    # remind Claude to arm the heartbeat cron — but when a MACHINE-WIDE stop flag is set
    # (/janitor-global-disarm or /janitor-global-pause), re-arming would re-create the very
    # heartbeat the user globally stopped (the pre-RQ9FIFX6 bug where a disarmed machine kept
    # re-arming a fresh ~618k-token-per-fire cron on every new/resumed session). So when stopped,
    # do NOT nudge /janitor-arm; tell the user how to resume. /janitor-global-arm (or -unpause)
    # clears the flag and the next session start re-arms normally.
    # Machine-wide stop set → do NOT nudge /janitor-arm (re-arming re-creates the very
    # heartbeat the user globally stopped). Surface a RICH reminder — WHEN it was set +
    # WHY — so a temporary stop can't silently persist (the disarmed-and-forgotten
    # failure: a bare "it's stopped" line went unnoticed for ~33 h). This is the ONLY
    # surface while stopped (the heartbeat is deliberately silent — RQ9FIFX6), but hooks
    # fire even while disarmed, so it is free (SessionStart runs anyway). It only helps
    # the NEXT session start, not a session disarmed mid-flight — that residual case
    # needs an out-of-band reminder (documented follow-up).
    stop = _active_global_stop(gs)
    if stop is not None:
        kind, reason, since = stop
        state.log_line("session-start", f"global stop active ({kind}) -> not nudging /janitor-arm")
        import time  # noqa: E402  -- stdlib

        print(_format_stop_reminder(kind, reason, since, int(time.time())))
        return 0

    # /janitor-arm is idempotent, so even if the durable cron survived a previous
    # session, re-arming is safe.
    print("[ai-maestro-janitor] The janitor heartbeat keeps drift detection and rate-limit recovery running in this session. If you have not done so yet (or if the previous cron hit its 7-day auto-expiry), run /janitor-arm to arm it. The skill is idempotent — safe to re-run.")
    return 0


if __name__ == "__main__":
    # Bare main() — see on-stop-failure.py for the rationale (CPV's
    # _walk_module_scope flags sys.exit inside `if __name__ == "__main__":`
    # as module-scope; main() always returns 0 here so dropping sys.exit
    # is behaviour-neutral).
    main()
