#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Cron-fire entry point for the janitor heartbeat — Python port of dispatch.sh.

Invoked by the CronCreate heartbeat armed by /janitor-arm. Each fire is a
fresh user turn inside the running Claude Code session: the cron prompt
shells out to this script, captures stdout, and surfaces any drift lines
to the model. Exits silently with no output when nothing is drifting.

Behavior:
  1. If rate-limited.flag exists, emit a single [janitor-resume] line and
     clear the flag. The cron fire itself proves the API is reachable
     again, so the model treats the line as a cue to resume the prior task.
  2. If the heartbeat cron is approaching its 7-day auto-expiry, emit a
     single [janitor-renew] line so Claude re-runs /janitor-arm before the
     cron dies. The skill is idempotent.
  3. Otherwise run each drift detector in --one-shot mode, respecting its
     configured internal cadence via per-detector last-run state files.
  4. Emit only new findings — the detectors' seen-files handle dedupe.

State:
  $PROJECT_ROOT/.janitor/state/rate-limited.flag
  $PROJECT_ROOT/.janitor/state/rate-limited-since.ts
  $PROJECT_ROOT/.janitor/state/last-run-<detector>.ts
  $PROJECT_ROOT/.janitor/state/heartbeat-armed-at.ts   # written by /janitor-arm
  $PROJECT_ROOT/.janitor/state/heartbeat-renew-seen.txt

Exit code: 0 on normal completion (including no drift). Non-zero only on
unrecoverable errors.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import dedupe  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402

# Detector roster: (name, default cadence in seconds, env-var override).
# Order matches dispatch.sh — detectors with shorter cadences run first
# only because that order is human-readable (cadence is enforced
# per-detector via last-run files, not by ordering).
_DETECTORS: list[tuple[str, int, str]] = [
    ("pr-reconciler",    900,   "CLAUDE_PLUGIN_OPTION_PR_RECONCILER_INTERVAL"),
    ("worktree-janitor", 900,   "CLAUDE_PLUGIN_OPTION_WORKTREE_JANITOR_INTERVAL"),
    ("trdd-drift",       3600,  "CLAUDE_PLUGIN_OPTION_TRDD_DRIFT_INTERVAL"),
    ("trdd-reminder",    14400, "CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL"),
    ("task-pr-mismatch", 1800,  "CLAUDE_PLUGIN_OPTION_TASK_PR_MISMATCH_INTERVAL"),
    ("stale-task",       1800,  "CLAUDE_PLUGIN_OPTION_STALE_TASK_INTERVAL"),
    ("dirty-tree",       300,   "CLAUDE_PLUGIN_OPTION_DIRTY_TREE_INTERVAL"),
    ("subagent-report",  3600,  "CLAUDE_PLUGIN_OPTION_SUBAGENT_REPORT_INTERVAL"),
    ("version-update",   300,   "CLAUDE_PLUGIN_OPTION_VERSION_CHECK_INTERVAL"),
    ("trashcan-purge",   86400, "CLAUDE_PLUGIN_OPTION_TRASHCAN_PURGE_INTERVAL"),
    # screenshot-purge runs hourly: 72h is the default age threshold so a
    # 1h cadence catches expiries promptly AND re-probes free disk while
    # the user is mid-task. Skipped silently when reports/screenshots/ is
    # absent, which is the common case on non-UI projects.
    ("screenshot-purge", 3600,  "CLAUDE_PLUGIN_OPTION_SCREENSHOT_PURGE_INTERVAL"),
    # v0.4.0 additions:
    ("remote-credentials",      3600,  "CLAUDE_PLUGIN_OPTION_REMOTE_CREDENTIALS_INTERVAL"),
    ("stale-stash",             86400, "CLAUDE_PLUGIN_OPTION_STALE_STASH_INTERVAL"),
    ("nested-git-safety",       3600,  "CLAUDE_PLUGIN_OPTION_NESTED_GIT_SAFETY_INTERVAL"),
    ("tracked-ignored",         3600,  "CLAUDE_PLUGIN_OPTION_TRACKED_IGNORED_INTERVAL"),
    # marketplace-refresh runs BEFORE the plugin-* detectors so the
    # marketplace cache is fresh by the time those consult the manifest.
    ("marketplace-refresh",     300,   "CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_INTERVAL"),
    # user-plugins-update is Track 1 of the auto-update directive — cron-
    # global, project-agnostic, no enabled filter (all user-scope plugins).
    ("user-plugins-update",     300,   "CLAUDE_PLUGIN_OPTION_USER_PLUGINS_UPDATE_INTERVAL"),
    # local-plugins-update is Track 2a — per-project, reads
    # .claude/settings.local.json, filters to enabled, no git mutation
    # (settings.local.json is gitignored by convention).
    ("local-plugins-update",    300,   "CLAUDE_PLUGIN_OPTION_LOCAL_PLUGINS_UPDATE_INTERVAL"),
    # project-plugins-update is Track 2b — per-project, reads
    # .claude/settings.json (git-tracked), filters to enabled. On
    # settings.json drift, emits a [project-plugins-commit-needed]
    # drift line for Claude to commit via porcelain `git commit`.
    ("project-plugins-update",  300,   "CLAUDE_PLUGIN_OPTION_PROJECT_PLUGINS_UPDATE_INTERVAL"),
    ("plugin-updates",          300,   "CLAUDE_PLUGIN_OPTION_PLUGIN_UPDATES_INTERVAL"),
    ("mcp-config-drift",        3600,  "CLAUDE_PLUGIN_OPTION_MCP_CONFIG_DRIFT_INTERVAL"),
    ("settings-scope-drift",    3600,  "CLAUDE_PLUGIN_OPTION_SETTINGS_SCOPE_DRIFT_INTERVAL"),
    ("subagent-scope-drift",    3600,  "CLAUDE_PLUGIN_OPTION_SUBAGENT_SCOPE_DRIFT_INTERVAL"),
    ("claude-md-scope-drift",   3600,  "CLAUDE_PLUGIN_OPTION_CLAUDE_MD_SCOPE_DRIFT_INTERVAL"),
    ("cross-scope-reference-drift", 3600, "CLAUDE_PLUGIN_OPTION_CROSS_SCOPE_REFERENCE_DRIFT_INTERVAL"),
    # v0.5.1 additions — security monitoring (CI/CD + repo hardening). Both
    # are READ-ONLY: they surface findings, they never mutate the repo.
    #   workflow-security runs every heartbeat — the detector content-hashes
    #   the workflow files and short-circuits when nothing changed, so an
    #   unchanged-workflows fire is ~free, while a newly-introduced injection
    #   or secret-leak surfaces within one cadence.
    ("workflow-security",   300,   "CLAUDE_PLUGIN_OPTION_WORKFLOW_SECURITY_INTERVAL"),
    #   branch-protection polls the GitHub API (gh), so it runs on a slow 6h
    #   cadence — branch rulesets change rarely; its seen-file nags once until
    #   fixed and re-arms (emit_forget) if protection is later removed.
    ("branch-protection",   21600, "CLAUDE_PLUGIN_OPTION_BRANCH_PROTECTION_INTERVAL"),
    # package-manager-policy is the DETECTION complement to the
    # pre-tool-pkg-guard PreToolUse hook: the hook PREVENTS weakening at
    # call-time, this detector REPORTS missing hardening at fire-time so
    # a project can be hardened before the next supply-chain attack lands.
    # Content-hash short-circuit keeps no-op fires near-free.
    ("package-manager-policy", 21600, "CLAUDE_PLUGIN_OPTION_PKG_MANAGER_POLICY_INTERVAL"),
]


def _detector_is_due(name: str, interval: int) -> bool:
    last_file = state.state_dir() / f"last-run-{name}.ts"
    if not last_file.exists():
        return True
    last = state.read_int_state(last_file, 0)
    return (int(time.time()) - last) >= interval


def _mark_detector_ran(name: str) -> None:
    state.atomic_write(state.state_dir() / f"last-run-{name}.ts", str(int(time.time())))


def _run_detector(name: str, interval: int) -> None:
    script = _HERE / "detectors" / f"{name}.py"
    if not script.is_file() or not os.access(script, os.X_OK):
        state.log_line("dispatch", f"detector '{name}' missing at {script}")
        return
    if not _detector_is_due(name, interval):
        return
    # stdout passes through to the cron prompt as drift findings; stderr
    # goes to the detector's own log via state.log_line.
    proc = subprocess.run(
        [str(script), "--one-shot"],
        capture_output=False,
        check=False,
    )
    if proc.returncode != 0:
        state.log_line("dispatch", f"detector '{name}' exited non-zero")
    _mark_detector_ran(name)


def _phase_paused() -> bool:
    """Return True if the heartbeat is paused (and we should exit early)."""
    paused_file = state.state_dir() / "paused"
    if not paused_file.is_file():
        return False
    paused_until = state.read_int_state(paused_file, 0)
    now_ts = int(time.time())
    if paused_until == 0 or now_ts < paused_until:
        state.log_line("dispatch", f"skipped: paused (until={paused_until})")
        return True
    # Expiry passed → auto-resume. Remove the sentinel and continue.
    try:
        paused_file.unlink()
    except FileNotFoundError:
        pass
    state.log_line("dispatch", f"auto-resumed: pause expiry passed (was {paused_until})")
    return False


def _phase_log_retention() -> None:
    """Bound .janitor/logs/ growth. Fires at most once per LOCAL day.

    Successive heartbeats inside the same day re-read the stamp and skip
    the cleanup; the cost per fire is one stat() + one string compare.
    """
    days = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_LOG_RETENTION_DAYS"), 30)
    if days <= 0:
        return
    stamp = state.state_dir() / "log-retention-last-day.txt"
    today = datetime.now().astimezone().strftime("%Y%m%d")
    prev = ""
    try:
        prev = stamp.read_text().strip()
    except (FileNotFoundError, OSError):
        pass
    if prev == today:
        return

    cutoff = time.time() - (days * 86400)
    log_root = state.log_dir()
    if log_root.is_dir():
        for f in log_root.iterdir():
            if not f.is_file():
                continue
            name = f.name
            if not (name.endswith(".log") or name.endswith(".log.1")):
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except (FileNotFoundError, OSError):
                pass
    state.atomic_write(stamp, today)


def _phase_rate_limit_recovery() -> bool:
    """Return True if a [janitor-resume] line was emitted (caller should exit)."""
    flag = state.state_dir() / "rate-limited.flag"
    if not flag.is_file():
        return False

    since_file = state.state_dir() / "rate-limited-since.ts"
    now = int(time.time())
    since = state.read_int_state(since_file, now)
    age = now - since

    if age > 0:
        print(
            f"[janitor-resume] rate-limit cleared after {age}s — API is reachable again. "
            f"Resume the previous pending task."
        )
    else:
        # since-file was missing or in the future (clock skew); still cue resume.
        print(
            "[janitor-resume] rate-limit cleared (duration unknown) — API is reachable again. "
            "Resume the previous pending task."
        )

    for p in (flag, since_file):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    state.log_line("dispatch", f"rate-limit cleared after {age}s, resume cue emitted")
    return True


def _phase_plugin_reload() -> None:
    """Emit a bare `[janitor-reload]` marker once when the daemon flags a reload.

    The global daemon writes `reload-needed.flag` after a `claude plugin update`
    actually changes a plugin's version. This phase reads + clears that flag and
    surfaces a single bare marker line; the cron prompt's silent-execute clause
    runs `/reload-plugins` without echoing the marker. Together with the
    daemon-restart phase below, plugin auto-updates are fully autonomous: new
    hook/skill code is in effect within one heartbeat cadence of an update.

    No dedupe stamp — the flag itself is the source of truth, and clearing it
    immediately after emission is enough. If a second update lands in the same
    heartbeat window the daemon re-arms the flag and we emit again next fire.
    """
    if not gs.reload_flag_present():
        return
    gs.clear_reload_flag()
    print("[janitor-reload]")
    state.log_line("dispatch", "reload-needed.flag → [janitor-reload] emitted, flag cleared")


def _phase_daemon_restart_if_stale() -> None:
    """SIGTERM the daemon when its script path no longer matches the live cache.

    Symptom this defends against: janitor plugin auto-updates land while the
    daemon process is alive. Hook/skill reload via `/reload-plugins` swaps the
    plugin's surface, but the daemon's Python interpreter keeps running the
    OLD daemon.py from the previous cache version. Detector code shipped in
    the new version would be invisible to that daemon. The fix: detect the
    mismatch by reading the running process's argv, SIGTERM the stale one,
    let `ensure_daemon_running()` (next phase) lazy-spawn a fresh daemon from
    the current cache. Phase order matters: restart-if-stale precedes the
    ensure_daemon call so the spawn happens this same fire.

    Wrapped defensively — a ps failure, a foreign-uid permission denial, or a
    flaky filesystem must never crash the heartbeat. Worst case the stale
    daemon keeps running until it dies on its own (then ensure-daemon spawns
    the new one from current cache).
    """
    try:
        if gs.daemon_needs_restart():
            gs.request_daemon_restart()
    except Exception as exc:  # noqa: BLE001
        state.log_line("dispatch", f"daemon-restart-if-stale failed: {exc}")


def _phase_heartbeat_renew() -> None:
    """Emit a bare `[janitor-renew]` marker when the cron approaches 7-day expiry.

    Durable recurring CronCreate jobs auto-expire after 7 days. dispatch
    can't call CronCreate itself (that's session-tool territory), so the
    renewal goes through a protocol token: dispatch prints a single line of
    exactly `[janitor-renew]`, the cron prompt teaches Claude to execute
    /janitor-arm SILENTLY when it sees that token (do NOT echo the marker),
    and /janitor-arm idempotently replaces the cron with a fresh 7-day one.
    Result: zero user-visible noise; renewal happens behind the scenes.

    Backward compat: existing crons armed with the pre-v0.5.2 prompt do NOT
    have the silent-execute clause — they will surface the bare marker once,
    Claude still acts on it (the token is documented), the user re-arms once,
    and from then on the new prompt makes future renewals silent. So the
    upgrade path is "one visible line per session, ever."

    Dedupe by day bucket so repeated heartbeat fires don't spam the marker.
    """
    threshold_days = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_HEARTBEAT_RENEWAL_THRESHOLD_DAYS"), 6
    )
    threshold_sec = threshold_days * 86400
    armed_at_file = state.state_dir() / "heartbeat-armed-at.ts"
    if not armed_at_file.is_file():
        return
    armed_at = state.read_int_state(armed_at_file, 0)
    now = int(time.time())
    age = now - armed_at
    if armed_at <= 0 or age < threshold_sec:
        return
    age_days = age // 86400  # dedup key only — not user-visible in v0.5.2+
    line = dedupe.emit_once(
        state.state_dir() / "heartbeat-renew-seen.txt",
        f"renew@day{age_days}",
        "[janitor-renew]",  # bare marker — the cron prompt's silent-execute clause handles it
    )
    if line is not None:
        print(line)


def main() -> int:
    state.init_state()

    # Phase 0: paused sentinel.
    if _phase_paused():
        return 0

    # Phase 0.5: log retention.
    _phase_log_retention()

    # Phase 1: rate-limit recovery — if a [janitor-resume] was emitted,
    # skip drift detectors this fire so resume gets clean attention.
    if _phase_rate_limit_recovery():
        return 0

    # Phase 1.5: heartbeat auto-renew (silent on v0.5.2+ crons).
    _phase_heartbeat_renew()

    # Phase 1.6: plugin-reload signal — emit [janitor-reload] once when the
    # daemon's user-plugins-update task reports a real version change. The
    # cron prompt's silent-execute clause runs /reload-plugins.
    _phase_plugin_reload()

    # Phase 1.65: daemon staleness — if the running daemon's script path
    # doesn't match the current cache version, SIGTERM it so Phase 1.7 can
    # lazy-spawn a fresh one. Must precede ensure_daemon_running for the
    # respawn to happen this fire instead of next.
    _phase_daemon_restart_if_stale()

    # Phase 1.7: lazy-spawn the global janitor daemon (issue #7 fix). Cheap
    # no-op when the daemon is already alive; otherwise spawns it detached.
    # The daemon owns every machine-global auto-update task (marketplace
    # refresh, user-scope plugin updates), replacing the per-session pile-up
    # the pre-daemon design produced. Wrapped defensively so a global-state
    # filesystem error never crashes the heartbeat.
    try:
        gs.ensure_daemon_running()
    except Exception as exc:  # noqa: BLE001
        state.log_line("dispatch", f"ensure_daemon_running failed: {exc}")

    # Phase 2: drift detectors.
    for name, default_interval, env_var in _DETECTORS:
        interval = state.coerce_int(os.environ.get(env_var), default_interval)
        _run_detector(name, interval)

    state.rotate_log_if_big("dispatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
