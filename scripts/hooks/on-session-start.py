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
import time
from pathlib import Path


def _early_log(message: str) -> None:
    """Append ONE dated line to session-start.log WITHOUT importing the `lib` package.

    The runtime half of the janitor#80 guardrail. `tests/test_hooks_execute.py` now
    executes every hook, so an import-time death cannot pass as silence *in the repo* —
    but it says nothing about a DEPLOYMENT where the import breaks: a half-written plugin
    cache, a version skew, a partial update. That is the janitor's own domain, and it is
    exactly how the original outage stayed invisible: from 2026-06-20 to 2026-07-11 a
    missing `sys.path` entry raised ModuleNotFoundError before this hook's first statement,
    Claude Code surfaced nothing, and the only symptom was the absence of things nobody
    watches.

    So this DELIBERATELY DUPLICATES `lib.state.log_dir()`'s resolution (JANITOR_LOG_DIR →
    $CLAUDE_PROJECT_DIR → git toplevel → cwd, then `/.janitor/logs`) instead of calling it.
    Calling it would import the very package whose failure this exists to report. The
    duplication is the point, not an oversight — and it is the reason to keep the ladder
    in step with `state.log_dir()` if that ever changes.

    stdlib-only and best-effort BY CONTRACT: every path is wrapped and swallowed, because a
    logging fault must never become the new way session start breaks. The line format
    matches `state.log_line` so both writers interleave cleanly in one file.
    """
    try:
        import subprocess  # stdlib -- local keeps module scope import-clean
        from datetime import datetime  # stdlib

        override = os.environ.get("JANITOR_LOG_DIR", "").strip()
        if override:
            logs = Path(override).expanduser()
        else:
            proj = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
            if proj:
                root = Path(proj)
            else:
                try:
                    # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes
                    # .git/index.lock and collides with a concurrent
                    # `publish.py` commit (janitor#245).
                    git_env = dict(os.environ)
                    git_env["GIT_OPTIONAL_LOCKS"] = "0"
                    out = subprocess.run(
                        ["git", "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True, check=True, timeout=5,
                        env=git_env,
                    ).stdout.strip()
                    root = Path(out) if out else Path.cwd()
                except (OSError, subprocess.SubprocessError):
                    root = Path.cwd()
            logs = root / ".janitor" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        prefix = f"[{ts}] [s:{sid[:8]}] " if sid else f"[{ts}] "
        with (logs / "session-start.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}{message}\n")
    except Exception:  # noqa: BLE001,S110 -- a logging fault must never break session start
        pass


def _active_global_stop(gs) -> tuple[str, str, int] | None:
    """(kind, reason, since_epoch) for the active machine-wide stop, or None.

    So the SessionStart reminder can name WHEN the stop was set and WHY. The bare
    "the janitor is stopped" line this replaces was ignored for ~33 h once (the
    disarmed-and-forgotten failure): a temporary /janitor-global-disarm for a
    token-burn fix was never re-armed, and nothing carried the duration or reason
    that would have made it stick. Kill-switch (disarm) dominates a pause when both
    are set.

    Uses the dual/triple-read `*_present()` + `read_flag_provenance()` helpers
    (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X) rather than reading `global_state_dir()`
    directly — the six mode flags now live at the fixed control_dir(), so a direct
    read of the old location would silently stop seeing a set flag. Pure read; a
    stat/read failure degrades to empty, never raises — this must never break
    session start.
    """
    # PAUSED was a second row here. The global-pause flag is retired (owner directive
    # 2026-07-31) — a stop that leaves everything running while doing nothing is what made
    # the silent-disable incident invisible in the first place.
    for kind, fname, present in (
        ("DISARMED", "kill-switch.flag", gs.kill_switch_present),
    ):
        if not present():
            continue
        prov = gs.read_flag_provenance(fname)
        return (kind, prov.get("reason", ""), prov.get("set_at", 0))
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


def _seed_overview_if_absent(state, memory_bridge, scope_name: str, scope_root: Path) -> None:  # noqa: ANN001 - local module type
    """janitor#129 — the per-machine half of #112: seed a minimal `*-overview.md` entry
    page for a LOCAL/USER memory scope that has none yet.

    #112 shipped the PROJECT overview IN THE REPO, so every cloner inherits it for free.
    LOCAL (`~/.claude/projects/<slug>/memory/`) and USER (the plugin DATA dir) live
    OUTSIDE any repo and ship with nothing — so on a fresh machine, or a project newly
    adopting the janitor, `memory_bridge.find_overview_page` returns None for both,
    `ensure_bridge_line` returns `OUTCOME_NO_OVERVIEW`, and those two scopes have no
    entry point at all. Nothing errors; the only symptom is `memgrep overview
    <local-or-user-memdir>` saying "no `<project>-overview.md`" — the exact condition
    #112 fixed, just per-machine instead of repo-wide.

    NEVER for PROJECT scope — that page is the repo's own, authored deliberately; an
    auto-seeded stub would compete with a curated hub and land in someone's `git status`.
    Idempotent (only writes when `find_overview_page` finds nothing — never touches an
    existing page) and fail-open (a seeding fault must never cost a session), mirroring
    the bridge line it feeds.
    """
    if scope_name == "PROJECT":
        return
    try:
        if memory_bridge.find_overview_page(scope_root) is not None:
            return  # already seeded (by this hook, /janitor-memory-bootstrap, or by hand)
        scope_root = Path(scope_root)
        if not scope_root.is_dir():
            return
        project_name = Path(state.project_root()).name or "project"
        stem = f"{project_name}-{scope_name.lower()}-overview"
        target = scope_root / f"{stem}.md"
        if target.exists():
            return  # race with another session between the check above and here
        from datetime import datetime  # noqa: PLC0415 - local: not needed on the hot path

        now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        body = (
            "---\n"
            f"name: {stem}\n"
            f'description: "{scope_name} memory scope entry point for {project_name}"\n'
            f"ocd: {now}\n"
            f"lmd: {now}\n"
            "metadata: {node_type: memory, type: overview, tier: hub}\n"
            "---\n\n"
            f"# {project_name} — {scope_name} memory overview\n\n"
            f"This is the entry point for the {scope_name}-scope memory of "
            f"**{project_name}**. It was seeded empty by SessionStart because no "
            "`*-overview.md` page existed yet in this scope (janitor#129) — replace "
            f"this stub the first time you write real {scope_name}-scope knowledge here.\n\n"
            f'Recall by symptom: `memgrep recall "<symptom>" {scope_root}`.\n\n'
            "## Notes and lessons learned\n"
        )
        state.atomic_write(target, body)
        state.log_line("session-start", f"seeded a stub {scope_name} overview page: {target}")
    except Exception as exc:  # noqa: BLE001 -- fail OPEN; a seeding fault never costs a session
        state.log_line("session-start", f"{scope_name} overview seed skipped: {exc}")


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
    # The breadcrumb pair that makes an import death AUDIBLE on a broken deployment. The
    # "entered" line is written BEFORE the import that can die, so a log holding "entered"
    # with no "imports ok" after it names the fault precisely — that is the whole signal the
    # 3-week silent outage lacked. Re-raise after logging: a hook that cannot import its own
    # library must still fail, just not invisibly.
    _early_log(f"entered (plugin_root={plugin_root})")
    try:
        from lib import global_state as gs  # noqa: E402  -- local package, not PyPI
        from lib import harness_backend, memory_scopes, rules_installer, settings_ensurer, state  # noqa: E402  -- local package, not PyPI
    except Exception as exc:  # noqa: BLE001 -- logged, then re-raised; never swallowed
        _early_log(f"FATAL: lib import failed ({type(exc).__name__}: {exc}) — hook aborted")
        raise
    _early_log("imports ok")

    state.init_state()

    # #J THIN MODE (TRDD-PZLVT2RN): inside an ai-maestro harness agent this hook keeps
    # only its self-scoped work (state init, breadcrumb, TRDD surfacing, arm nudge) and
    # SKIPS every outside-world writer below — rules/settings/references (the settings
    # write would collide with the server's own claude-settings-enforcer), the memory
    # mirror, the lean-ctx allowlist, and the OAuth beacon/supervisor (the server owns
    # Family-A + token surfaces for harness agents; janitor#100).
    thin_harness = harness_backend.is_harness_session()
    if thin_harness:
        state.log_line("session-start", "harness thin mode (#J): outside-world writers skipped")

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
    except Exception:  # noqa: BLE001 -- best-effort; never break session start
        source = "startup"
    # Record what was parsed. Several branches below (the clear-observed stamp, the reload
    # ack seeding) are gated on `source`, and from outside a wrong `source` is
    # INDISTINGUISHABLE from the branch having run and failed — both leave no file. One log
    # line makes that difference readable after the fact.
    state.log_line("session-start", f"source={source}")

    # THE "a /clear actually happened" signal (TRDD-Z582IKIR follow-up). `/clear` has
    # no hook of its own, but it re-enters SessionStart with source=clear — this is the
    # ONLY unambiguous observation of it. dispatch.py's `_phase_clear_resume` gates on
    # this stamp instead of the mere PRESENCE of `resume-after-clear.flag`, because that
    # flag is a PRE-marker: `clear_trigger.py` writes it BEFORE firing /clear, so a
    # heartbeat landing in the gap would otherwise consume a resume for a clear that has
    # not happened yet — and the fresh session then sits idle with no cue at all.
    # Stamped unconditionally on every clear (even with no flag pending): a stamp older
    # than a later flag never arms it, so a spurious stamp is inert, whereas a MISSING
    # one strands the resume forever. Best-effort — a fault here must never break start.
    if source == "clear":
        try:
            state.atomic_write(state.state_dir() / "clear-observed.ts", str(int(time.time())))
        except Exception as exc:  # noqa: BLE001 -- never break session start
            # LOG, never swallow silently: a lost stamp means the post-clear resume never
            # fires and the fresh session sits idle — the exact silent-disable shape this
            # project treats as a defect. Logging keeps the failure diagnosable without
            # ever raising into session start.
            state.log_line("session-start", f"clear-observed stamp failed: {exc!r}")
            print(f"[on-session-start] clear-observed stamp failed: {exc!r}", file=sys.stderr)

    # "fork" added for CC 2.1.214 ("SessionStart hooks now report source 'fork' when a
    # session begins as a fork instead of 'resume'"). A fork is a NEW process that loaded
    # the CURRENT plugins, exactly like startup/resume — so it must seed the ack too.
    #
    # This is not cosmetic. dispatch._phase_plugin_reload treats an ABSENT stamp as 0 and
    # self-heals by emitting `[janitor-reload]` once. So before this line covered "fork", a
    # forked session reloaded plugins it was already running — and since TRDD-VHPYSN56 a
    # reload above the context threshold SHRINKS FIRST, meaning the fork would `/clear` the
    # very conversation it was forked to preserve. A missing enum value became destructive
    # by composition with a feature added months later.
    if source in ("startup", "resume", "fork"):
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
        from lib import fleet_restart, session_liveness  # noqa: E402  -- local package

        ident = session_liveness.capture_terminal_identity(os.environ)
        # MIRROR-THE-LAUNCH (owner directive 2026-07-29): record the argv claude was
        # ACTUALLY started with, so recovery replays THAT instead of a guessed line. This is
        # load-bearing for rung 5 (`dead`), where the pid is already gone and there is no
        # live command line left to read — only the session itself can capture it, and only
        # here: our parent IS the claude process (verified — getppid() resolves to
        # `claude …`, not to a shell wrapper). Recorded even when no pane resolved, because
        # rung 7 (resurrect) needs no pane and would otherwise lose the flags too.
        argv = fleet_restart.live_cmdline(os.getppid())
        if fleet_restart.argv_is_claude(argv):
            ident["argv"] = argv
        if ident:
            # `time` is imported at module scope (the clear-observed stamp above needs it
            # earlier in THIS function); a second function-local import here would make
            # the name local for the whole body and leave that earlier use unbound.
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
        if not thin_harness and any(c is not None and (c / "state.json").is_file() for c in _candidates):
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
    copied = [] if thin_harness else rules_installer.install_rules(Path(plugin_root))
    if copied:
        state.log_line(
            "session-start",
            f"installed plugin rule(s): {', '.join(copied)}",
        )

    # Ensure the recommended Claude Code settings exist in ~/.claude/settings.json (TRDD-EQ792YPX):
    # 8 env keys ADD-IF-MISSING + askUserQuestionTimeout ENFORCED. Idempotent, atomic, fail-safe
    # (a malformed settings.json is left untouched). settings.json is read at Claude Code STARTUP,
    # so a change here applies on the NEXT launch — the notice below says so. Best-effort: a
    # failure must never break session start.
    try:
        changed = (
            {"env_added": [], "top_level_set": []}
            if thin_harness  # the SERVER's claude-settings-enforcer owns settings.json for harness agents
            else settings_ensurer.ensure_recommended_settings()
        )
        n = len(changed["env_added"]) + len(changed["top_level_set"])
        if n:
            keys = ", ".join(changed["env_added"] + changed["top_level_set"])
            print(
                f"[ai-maestro-janitor] Updated {n} recommended setting(s) in ~/.claude/settings.json "
                f"({keys}). They take effect on the NEXT Claude Code launch (settings.json is read "
                f"at startup).",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 -- best-effort; never break session start
        state.log_line("session-start", f"settings-ensurer failed: {exc}")

    # Ship the rules' FULL reference docs to <DATA>/rules-reference/ (TRDD-YRPUSIFY axis
    # B). They live OUTSIDE any .claude/rules/ dir on purpose: everything in a rules dir
    # is loaded into the context prefix of every session AND every cold subagent
    # machine-wide, so parking 87 KB of schemas/cheat-sheets/migration guides there made
    # every fan-out re-write them into cache. Here they cost ZERO tokens until an agent
    # actually reads one.
    refs = [] if thin_harness else rules_installer.install_references(Path(plugin_root))
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
    removed = [] if thin_harness else rules_installer.remove_orphaned_rules()
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
    synced = None if thin_harness else memory_scopes.sync_user_memory_mirror()
    if synced == "restored":
        state.log_line(
            "session-start",
            "restored USER memory from the uninstall-safe mirror (primary was empty)",
        )

    # MEMORY.md ↔ wikimem BRIDGE (owner directive 2026-07-25). MEMORY.md is the
    # HARNESS's file and the two memory systems COEXIST; the janitor maintains
    # EXACTLY ONE line in it — a link to the scope's `<project>-overview.md` — and
    # interferes with nothing else. Verified once per session and re-added if the
    # line was deleted. Append-only by construction (see lib/memory_bridge.py), so
    # it can never repeat the old "stub it" regression that ate harness pointers.
    try:
        from lib import memory_bridge  # noqa: E402  -- local package, not PyPI

        for _scope_name, _scope_root in memory_scopes.resolve_scope_dirs():
            _seed_overview_if_absent(state, memory_bridge, _scope_name, _scope_root)
            outcome = memory_bridge.ensure_bridge_line(_scope_root)
            if outcome == memory_bridge.OUTCOME_ADDED:
                state.log_line(
                    "session-start",
                    f"re-added the wikimem bridge line to {_scope_name} MEMORY.md",
                )
    except Exception as exc:  # noqa: BLE001 -- fail OPEN; an index line never costs a session
        state.log_line("session-start", f"memory bridge skipped: {exc}")

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

        allowed = [] if thin_harness else leanctx_allowlist.ensure_janitor_allowed()
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

        _facts = None if thin_harness else oauth_supervisor.gather_facts()
        if _facts is not None and _facts.opt_in:
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

    # Findings inbox (TRDD-FENWWB4E, ARCHITECTURE.md §4 — ratified rev 3): surface the
    # UNREAD entries of THIS project's findings ledger — the per-project mailbox where
    # the daemon (and past sessions' detectors) indexed findings while no session was
    # alive. Capped (~10 lines + one fold, ≤ ~1 KB — the owner's context-budget
    # constraint); the cursor advances on surfacing, so it prints once. Printed BEFORE
    # the global-stop return on purpose: an unattended project's inbox is exactly what
    # a session on a stopped machine must still see (like the memory breadcrumb, the
    # mailbox outlives the heartbeat). Silent on an empty inbox.
    try:
        from lib import findings_ledger  # noqa: E402  -- local package, not PyPI

        block = findings_ledger.surface_block(None)
        if block:
            print(block)
    except Exception as exc:  # noqa: BLE001 -- advisory only; never break session start
        state.log_line("session-start", f"findings inbox skipped: {exc}")

    # Harness self-test (TRDD-B0SABNP8): the janitor is coupled to Claude Code harness
    # internals, and several CC releases have BROKEN that coupling SILENTLY (2.1.207
    # dropped plugin-option DELIVERY; 2.1.208 reset the context window → a destructive
    # /compact on a bogus number; 2.1.211 changed accepted int spellings). This fast,
    # fail-open self-test SHOUTS (a drift line + a findings-ledger entry) when the harness
    # moved under us, instead of degrading with no error.
    #
    # PLACEMENT IS PINNED (ATOM-B0SA-PLCE): HERE — after the findings surface_block, BEFORE
    # the _active_global_stop check — so it runs even on a stopped machine (a harness break
    # is something even a disarmed session must be told), the same pre-stop-return slot the
    # breadcrumb and findings inbox use. It is its OWN try/except and MUST NEVER return or
    # raise, so the arm-nudge / stop-reminder survival emissions below are never stranded
    # (D4's form of the D1/D2/D5 unifying invariant: an actuation block must never strand a
    # survival emission on an early return). Skips thin #J harness sessions — the ai-maestro
    # server owns harness compat there. DEDUPES on a content-hash of the failure set so an
    # unchanged break shouts ONCE (protecting the ~1 KB SessionStart surface budget); a
    # CHANGED set re-shouts, and a CC fix that empties the set clears the stamp.
    try:
        if not thin_harness:
            from lib import harness_selftest  # noqa: E402  -- local package, not PyPI

            if harness_selftest.selftest_enabled():
                _failures = harness_selftest.run_selftest()
                _seen = state.state_dir() / "harness-selftest-seen"
                if _failures:
                    _digest = harness_selftest.failure_digest(_failures)
                    try:
                        _prev = _seen.read_text(encoding="utf-8").strip()
                    except OSError:
                        _prev = ""
                    if _digest != _prev:
                        print(harness_selftest.format_drift_line(_failures))
                        from lib import findings_ledger as _fl  # noqa: E402  -- local package

                        for _code, _sev, _msg in _failures:
                            _fl.record(sev=_sev, code=_code, src=harness_selftest.SRC, msg=_msg)
                        state.atomic_write(_seen, _digest)
                elif _seen.is_file():
                    # A CC upgrade fixed the break: the set emptied → clear the stamp so the
                    # NEXT distinct break shouts again (ATOM-B0SA-DDUP self-clear).
                    try:
                        _seen.unlink()
                    except OSError:
                        pass
    except Exception as exc:  # noqa: BLE001 -- MUST NOT strand the survival emissions below
        state.log_line("session-start", f"harness self-test skipped: {exc}")

    stop = _active_global_stop(gs)
    if stop is not None:
        # A maintenance override used to sit here: maintenance-mode WON over a global stop,
        # so the arm nudge still fired and that one session kept its cache warm with cheap
        # do-nothing fires. Both the mode and the override are gone (owner directive
        # 2026-07-31) — a stop is now unambiguous, and an armed-but-inert session is exactly
        # the state that made a disabled fleet look healthy.
        kind, reason, since = stop
        state.log_line("session-start", f"global stop active ({kind}) -> not nudging /janitor-arm")
        print(_format_stop_reminder(kind, reason, since, int(time.time())))
        return 0

    # /janitor-arm is idempotent, so even if the durable cron survived a previous
    # session, re-arming is safe.
    #
    # TRDD-TUIBWHT7 ("arm once, armed forever"): once `armed_state()` says "armed", every
    # later session re-plumbs its own session-only cron from that persistent claim with NO
    # user-facing ceremony — the nag banner below is for the genuinely-first-install case
    # only (`armed_state()` returns "absent"). `stop` above already handled "disarmed" (the
    # machine-wide kill-switch), so only "armed" vs "absent" remain here.
    try:
        armed = gs.armed_state()
    except Exception as exc:  # noqa: BLE001 -- must never break session start
        state.log_line("session-start", f"armed_state() failed, defaulting to absent: {exc}")
        armed = "absent"
    if armed == "armed":
        # ONLY on a fresh PROCESS. `clear` and `compact` re-enter SessionStart inside the
        # SAME process, where the session-only cron is still registered and firing — so a
        # nudge there is a pure mid-session RE-ARM: 4 tool calls plus a CronDelete/CronCreate
        # to replace a live cron with an identical one. That is the exact waste the owner
        # banned ("rearmed randomly in the middle of the sessions", directive 2026-08-08,
        # TRDD-BRHJHWW0/TUIBWHT7) — the tier controller was deleted for it, and this hook was
        # left as the surviving emitter. Measured 2026-08-11: cron id 73fb3358 recorded on
        # 08-08 was still the live id after both a /clear and a compaction, i.e. neither
        # event kills the cron. A cron lost to the 7-day auto-expiry is NOT this branch's
        # job either — dispatch.py's `_phase_heartbeat_renew` emits `[janitor-renew]` for
        # that, so gating here leaves no coverage gap.
        if source not in ("startup", "resume"):
            state.log_line("session-start", f"armed; source={source} keeps the live cron -> no re-arm")
            return 0
        print(
            "[janitor] armed (persistent) — re-plumbing the session heartbeat. "
            "Silently run /janitor-arm (its 4 tool calls); do not narrate this to the user."
        )
        return 0
    print("[ai-maestro-janitor] The janitor heartbeat keeps drift detection and rate-limit recovery running in this session. If you have not done so yet (or if the previous cron hit its 7-day auto-expiry), run /janitor-arm to arm it. The skill is idempotent — safe to re-run.")
    return 0


if __name__ == "__main__":
    # Bare main() — see on-stop-failure.py for the rationale (CPV's
    # _walk_module_scope flags sys.exit inside `if __name__ == "__main__":`
    # as module-scope; main() always returns 0 here so dropping sys.exit
    # is behaviour-neutral).
    main()
