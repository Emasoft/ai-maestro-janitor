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


def _cron_liveness_nudge(state, session_id: str) -> None:  # noqa: ANN001 - local module type
    """W2 (TRDD-82OP4EN9): one context line asking the fresh session to arm/verify
    the heartbeat cron. Re-arm on every wake (janitor#77 item A, TRDD-EFTQB9RR).

    Some Claude Code builds downgrade `durable: true` crons to session-only,
    and the 7-day expiry can eat one — either way the heartbeat silently stops
    firing and an unattended night loses its resume pulse. A hook cannot call
    CronList/CronCreate (session tools), so the strongest thing a SessionStart
    hook CAN do is put ONE verification line into the fresh session's context.

    The gate is the POSITIVE opt-out — only `disarmed.flag` suppresses the nudge.
    It used to be the PRESENCE of `heartbeat-armed-at.ts`, and that stamp cannot
    bear the weight: `/janitor-arm` writes it at step 6, one step AFTER CronCreate,
    so a turn that rate-limits in between leaves a firing cron with no stamp and
    this project is never nudged again, while a Claude restart leaves a stamp with
    no cron. Both lying directions were observed live on this machine (janitor#77
    item 2). `/janitor-arm` is idempotent — it deletes existing `[janitor-heartbeat]`
    crons before creating one — so an unconditional re-arm is correct whether or not
    a stamp claims it already happened. That sidesteps the stamp rather than trying
    to make it trustworthy.

    Deduped per session id (a single stamp file — bounded state; an absent
    session_id skips the dedupe rather than the nudge, because losing the nudge
    is the failure mode this exists to prevent).
    """
    try:
        if (state.state_dir() / state.DISARMED_FLAG).is_file():
            return  # the user opted out of THIS project — sacrosanct, never nudge
        seen = state.state_dir() / "cron-liveness-nudged.session"
        prev = ""
        try:
            prev = seen.read_text(encoding="utf-8").strip()
        except OSError:
            prev = ""
        if session_id and session_id == prev:
            return
        if session_id:
            state.atomic_write(seen, session_id)
        print(
            "janitor: verify the cron exists for this project "
            "(CronList: a job whose prompt starts with [janitor-heartbeat]); if it is missing, "
            "silently run /janitor-arm — it is idempotent, and some Claude Code builds drop "
            "durable crons on restart. To opt this project out permanently: /janitor-disarm."
        )
    except Exception as exc:  # noqa: BLE001 -- advisory only; never break session start
        state.log_line("session-start", f"cron-liveness nudge skipped: {exc}")


def _maybe_cold_compact_on_session_start(
    state,  # noqa: ANN001 -- local module type
    plugin_root: str,
    source: str,
    transcript_path: str,
) -> bool:
    """Cold-cache auto-compact at SessionStart (TRDD-EUWIHP0G). Returns True iff it
    fired the detached /compact. NEVER raises — a fault here must not break session
    start (the hook's standing contract).

    After a >1h stop (a rate limit; the user exits and relaunches later; a
    logout/login) the 1h prompt-cache TTL has expired, so the FIRST resumed turn
    re-writes the WHOLE context as a cache-creation (~600k avg, ~1.25×), burning the
    5h window. When a RESUMED session (a fresh process) carries a context at/above
    the threshold, self-fire /compact NOW so it shrinks to ~50k — the rest of the
    window (and every FUTURE cold resume) then runs cheap. It canNOT avoid the
    immediate cold write (any first turn pays that); the win is ongoing + future.

    Gated to `source in {startup, resume}`: a `compact`/`clear` keeps the SAME
    (already-small) post-compact context in the SAME process, and a truly fresh
    `startup` has a tiny context — the size guard makes both a no-op, and the source
    gate is the belt to that suspenders (it also blocks a re-fire loop, since our own
    /compact re-enters this hook as `source=compact`). SOFT compact: the resumed REPL
    is idle, so the enqueued /compact never interrupts work. A cooldown stamp (shared
    with the heartbeat rate-limit path) blocks a double-fire before the compact lands.
    """
    if source not in ("startup", "resume"):
        return False
    try:
        import time  # noqa: E402  -- stdlib

        from lib import cold_cache_compact  # noqa: E402  -- local package, not PyPI

        now = int(time.time())
        if not cold_cache_compact.enabled() or cold_cache_compact.in_cooldown(
            state.state_dir(), now=now
        ):
            return False
        ctx = cold_cache_compact.context_tokens_for(transcript_path)
        if not cold_cache_compact.should_compact_on_resume(
            ctx, min_context_tokens=cold_cache_compact.min_context_tokens()
        ):
            return False
        compact_py = Path(plugin_root) / "scripts" / "compact_trigger.py"
        if not compact_py.is_file():
            return False
        # Stamp the cooldown BEFORE firing so a racing heartbeat can't also fire;
        # then fire the detached SOFT /compact with a self-correcting resume
        # directive (post-compact-resume + the HI0BGQGJ push auto-resume/re-arm).
        cold_cache_compact.mark_fired(state.state_dir(), now=now)
        directive = (
            "cold-cache resume: the prompt cache was cold and the context was large on "
            "session start — after this compaction, re-arm the heartbeat if needed "
            "(/janitor-arm) then continue your prior work (read the newest in-flight "
            "TRDD's STATE block first)."
        )
        import subprocess  # noqa: E402  -- stdlib

        subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
            [sys.executable, str(compact_py), "--directive", directive],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        state.log_line(
            "session-start",
            f"cold-cache compact fired (source={source}, "
            f"context={ctx} >= {cold_cache_compact.min_context_tokens()})",
        )
        return True
    except Exception as exc:  # noqa: BLE001 -- best-effort; never break session start
        state.log_line("session-start", f"cold-cache compact skipped: {exc}")
        return False


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

    # Put scripts/ on sys.path so `from lib import …` resolves — the CPV hook
    # validator's local_sibling detector recognises that package form (scripts/lib/ has
    # an __init__.py), which is why the package import is used here rather than a bare
    # `import global_state`.
    #
    # scripts/lib/ MUST ALSO be on the path, and that is NOT cosmetic. A `lib` module may
    # bare-import a sibling (`global_state.py` does `import state`) — an ABSOLUTE import
    # that resolves only if scripts/lib/ is itself on sys.path. Every detector gets that
    # for free by putting scripts/lib/ on the path directly; a hook importing the same
    # module as `lib.global_state` does not. Omitting this line is not a lint nit: it
    # raises ModuleNotFoundError at IMPORT time, so the hook dies before its first
    # statement — which is exactly what happened. From 4df60fc (2026-06-20, when this hook
    # first imported global_state) until 2026-07-11 this hook crashed on EVERY session and
    # nobody noticed: Claude Code does not surface a SessionStart hook crash, so the only
    # symptom was the absence of things nobody watches — rules stopped updating (a rule
    # added after that date, universal-kanban.md, never reached ~/.claude/rules at all),
    # the reference docs stopped shipping, the memory breadcrumb stopped printing, and the
    # USER-memory backup mirror stopped syncing. tests/test_hooks_execute.py now EXECUTES
    # every hook, so an import-time death can never again pass as silence.
    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    sys.path.insert(0, str(Path(plugin_root) / "scripts" / "lib"))
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
    session_id = ""
    transcript_path = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                payload = json.loads(raw)
                source = str(payload.get("source", "startup"))
                # W2 (TRDD-82OP4EN9): the cron-liveness nudge below dedupes on
                # the session id so a clear/compact restart of the SAME session
                # doesn't repeat it.
                session_id = str(payload.get("session_id", "") or "")
                # Cold-cache auto-compact (TRDD-EUWIHP0G) reads the resumed
                # context size from the transcript SessionStart provides.
                transcript_path = str(payload.get("transcript_path", "") or "")
    except Exception:  # noqa: BLE001 -- best-effort; never break session start
        source = "startup"

    # Cold-cache auto-compact (TRDD-EUWIHP0G) — the "before any expensive turn"
    # path. When a RESUMED session (a fresh process) carries a large context whose
    # 1h prompt cache has gone cold, self-fire /compact NOW so the inevitable ~600k
    # cache-creation re-write shrinks to ~50k for the rest of the window. See the
    # helper's docstring for the full rationale + gating. Best-effort by contract.
    _maybe_cold_compact_on_session_start(state, plugin_root, source, transcript_path)
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

    # Live-identity BEACON (TRDD-7PYTX4E9 F2): this hook runs in the SESSION context,
    # which can read the primary live keychain item even when the headless daemon
    # cannot (a user /login writes a Claude-only-ACL item — the 2026-07-08 incident).
    # Stamp {fp, email, ts} into the rotator home so the daemon's mirror-source path
    # has independent ground truth for WHO is live. Detached (the email resolution may
    # hit /roles, ~1s — a hook must not block on it), lock-free (beacon writes only its
    # own atomic file), and gated on a configured rotator so machines without one pay
    # nothing. Best-effort: any failure must never break session start.
    try:
        import subprocess  # noqa: E402  -- stdlib

        _data_env = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
        _candidates = [
            Path(_data_env) / "oauth-rotator" if _data_env and "ai-maestro-janitor" in _data_env else None,
            Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins" / "oauth-rotator",
            Path.home() / ".claude" / "account-rotator",
        ]
        if any(c is not None and (c / "state.json").is_file() for c in _candidates):
            _rotator_py = Path(plugin_root) / "scripts" / "oauth_rotator" / "rotator.py"
            if _rotator_py.is_file():
                subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
                    [sys.executable, str(_rotator_py), "beacon"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
    except Exception as exc:  # noqa: BLE001 -- best-effort; never break session start
        state.log_line("session-start", f"live-identity beacon spawn skipped: {exc}")

    _cron_liveness_nudge(state, session_id)

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

    # Ship the rules' FULL reference docs to <DATA>/rules-reference/ (TRDD-YRPUSIFY axis
    # B). They live OUTSIDE any .claude/rules/ dir on purpose: everything in a rules dir
    # is loaded into the context prefix of every session AND every cold subagent
    # machine-wide, so parking 87 KB of schemas/cheat-sheets/migration guides there made
    # every fan-out re-write them into cache. Here they cost ZERO tokens until an agent
    # actually reads one.
    refs = rules_installer.install_references(Path(plugin_root))
    if refs:
        state.log_line(
            "session-start",
            f"installed rule reference doc(s): {', '.join(refs)}",
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
    # Memory breadcrumb (TRDD-98ISATJZ S2, janitor#62 gaps 2+3). ONE line naming the
    # per-scope note counts and the `memgrep overview` entry point, so a fresh session
    # LEARNS the 3-scope wikimem exists without already knowing memgrep. Printed BEFORE
    # the global-stop return on purpose: the memory system is independent of the
    # heartbeat and keeps working while the janitor is disarmed, so a stopped machine
    # must still get its corpus pointer. Counts only, never note content (see the lib's
    # docstring — a PROJECT-scope page is untrusted git input). Silent on an empty
    # corpus; best-effort, never breaks session start.
    try:
        from lib import memory_breadcrumb  # noqa: E402  -- local package, not PyPI

        crumb = memory_breadcrumb.breadcrumb()
        if crumb:
            print(crumb)
    except Exception as exc:  # noqa: BLE001 -- advisory only; never break session start
        state.log_line("session-start", f"memory breadcrumb skipped: {exc}")

    stop = _active_global_stop(gs)
    if stop is not None:
        # MAINTENANCE WINS OVER A GLOBAL STOP (TRDD-FPL60EKV): maintenance-mode exists
        # precisely so ONE session keeps its cache warm with cheap fires while the fleet
        # is stopped. Suppressing the arm nudge here would strand that session unarmed
        # at startup — the keep-warm never starts. Local sentinel OR machine-wide flag.
        maintenance = (state.state_dir() / "maintenance-mode").is_file() or gs.maintenance_mode_present()
        if not maintenance:
            kind, reason, since = stop
            state.log_line("session-start", f"global stop active ({kind}) -> not nudging /janitor-arm")
            import time  # noqa: E402  -- stdlib

            print(_format_stop_reminder(kind, reason, since, int(time.time())))
            return 0
        state.log_line("session-start", "global stop set but maintenance-mode active -> arm nudge proceeds")

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
