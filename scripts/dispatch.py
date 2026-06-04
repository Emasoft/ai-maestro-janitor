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
    ("report-to-trdd-drift", 21600, "CLAUDE_PLUGIN_OPTION_REPORT_TO_TRDD_INTERVAL"),
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
    # marketplace-refresh: per-session, scoped to local+project marketplaces.
    # Global bulk refresh is the daemon's job (every 20 min). Runs BEFORE the
    # plugin-* detectors so the manifest is fresh by the time they consult it.
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
    # ai-context-poisoning audits installed packages for postinstall code
    # that writes to an agent-context file (CLAUDE.md, .cursorrules,
    # AGENTS.md, .claude/*). Content-hashes node_modules + site-packages so
    # an unchanged tree returns immediately. Default cadence 1h — fast
    # enough to notice a newly-installed malicious package within one
    # heartbeat window.
    ("ai-context-poisoning", 3600, "CLAUDE_PLUGIN_OPTION_AI_CONTEXT_POISONING_INTERVAL"),
    # mcp-rugpull fingerprints every installed MCP server's identity
    # (command/args/url/local-script content/npx-resolved version) on first
    # run, then alerts on any drift. Catches the rug-pull attack shape
    # where a trusted server silently rewrites its source / endpoint /
    # tool surface. Default 1h cadence — server inventory changes are rare
    # and the diff is near-free, but a malicious update must surface fast.
    ("mcp-rugpull", 3600, "CLAUDE_PLUGIN_OPTION_MCP_RUGPULL_INTERVAL"),
    # typosquat-watcher walks every supported lockfile and flags names
    # within Levenshtein distance ≤ 1 of a curated popular-package list.
    # Catches the canonical typosquat attack shape (react/reactt,
    # ethers/ethersr, etc.) BEFORE the advisory feed surfaces it.
    # Content-hash dedupe makes unchanged-lockfile fires almost free.
    ("typosquat-watcher", 3600, "CLAUDE_PLUGIN_OPTION_TYPOSQUAT_WATCHER_INTERVAL"),
    # repo-trust-score audits the project tree for the dropper-shape
    # pattern shared by the two known-malicious repos found in the
    # github-monitoring study (snakebite, Pipeline-Sentinel). Combines
    # suspicious-binary inventory + README download-funnel + SEO
    # stuffing + camouflage-ratio + missing-essentials signals into a
    # single trust-deficit score. Default 6h cadence — the relevant
    # signals (README content, binaries) change slowly.
    ("repo-trust-score", 21600, "CLAUDE_PLUGIN_OPTION_REPO_TRUST_SCORE_INTERVAL"),
    # historical-cache-scan walks every npm cacache / pnpm store / yarn
    # cache + every global node_modules path for known-malicious
    # package@version pairs listed in .janitor/incidents.txt. Catches
    # the "version pruned from package.json is still in the cache and
    # will silently re-fetch" case. Default 6h cadence — incident
    # lists change rarely and the scan is content-hashed.
    ("historical-cache-scan", 21600, "CLAUDE_PLUGIN_OPTION_HISTORICAL_CACHE_SCAN_INTERVAL"),
    # binary-magic-scanner walks `.github/`, `scripts/`, `docs/`,
    # `tests/`, `examples/`, `image*/`, `download*/`, `release*/`
    # for ELF/PE/Mach-O/Java-class/Wasm/Zip magic-byte prefixes.
    # Catches the dropper shape (snakebite / Pipeline-Sentinel /
    # Sentinel-main-3) from a different angle than repo-trust-score.
    # Default 6h cadence; content-hash dedupe makes unchanged-tree
    # fires near-free.
    ("binary-magic-scanner", 21600, "CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_INTERVAL"),
    # supply-chain-fingerprints aggregates 6 sub-checks per fire:
    # import-cluster pairing in setup.py / package.json scripts,
    # maintainer-join-vs-publish gap, wheel-absence heuristic for
    # PyPI deps, fresh-publisher first-release shape, HTTP 451 npm
    # security-hold surfacing, ghost-publisher reawake. Default 6h
    # cadence; the detector's content-hash dedupe + opt-in network
    # lookups keep no-op fires near-free.
    ("supply-chain-fingerprints", 21600, "CLAUDE_PLUGIN_OPTION_SUPPLY_CHAIN_FINGERPRINTS_INTERVAL"),
    # provenance-audit scans the project at release-time for SBOM +
    # cosign verify presence, npm provenance, in-toto attestations,
    # SLSA level floor. Default 6h cadence — release infrastructure
    # changes rarely; content-hash dedupe is cheap.
    ("provenance-audit", 21600, "CLAUDE_PLUGIN_OPTION_PROVENANCE_AUDIT_INTERVAL"),
    # janitor-self-integrity verifies the janitor's own scripts /
    # skills / CLAUDE.md against a checked-in SHA-256 manifest + an
    # HMAC chain on the audit log. OPT-IN by default — flip
    # CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED=true to
    # activate. Default 6h cadence.
    ("janitor-self-integrity", 21600, "CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_INTERVAL"),
    # oauth-cookie-reminder is OPT-IN by presence: silent no-op unless a local
    # multi-account rotator home with a state.json exists (~/.claude/account-rotator
    # or $CLAUDE_PLUGIN_DATA/oauth-rotator). When present, it reminds the user to
    # run /refresh-claude-logins BEFORE a per-account claude.ai session cookie
    # expires AND while OAuth is still healthy, so the two expiries never coincide
    # (TRDD-32acd15f). 6h cadence; machine-scoped daily dedupe keeps it gentle.
    ("oauth-cookie-reminder", 21600, "CLAUDE_PLUGIN_OPTION_OAUTH_COOKIE_REMINDER_INTERVAL"),
    # oauth-login-needed is the reactive sibling of oauth-cookie-reminder, same
    # opt-in-by-presence gate (a rotator home with a state.json). It surfaces the
    # accounts that need a ONE-TIME human login because they can neither self-renew
    # (no refreshToken) nor auto-bootstrap (no live claude.ai Chrome session), so
    # only a fresh sign-in via ~/.claude/account-rotator/open-login.sh can revive
    # them. Distinct from cookie-reminder (the cookie/OAuth expiry RACE). 6h cadence;
    # machine-scoped daily dedupe keeps it gentle.
    ("oauth-login-needed", 21600, "CLAUDE_PLUGIN_OPTION_OAUTH_LOGIN_NEEDED_INTERVAL"),
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
    #
    # A wall-clock `timeout` is mandatory: the detector roster is iterated
    # in order (main() Phase 2), so a single hung detector — an infinite
    # pure-Python loop, an un-timed inner subprocess / network / `gh` call,
    # a blocking flock wait — would wedge THIS fire and starve every detector
    # after it, every fire, until the cron process is killed. Mirrors the
    # guard phase (_phase_guard_branch_protection), which already bounds its
    # subprocess. Well-behaved detectors self-limit via state.run_subprocess
    # (timeout=10s), but that's a convention, not an enforced bound — this is
    # the enforced one.
    timeout = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT"), 120
    )
    try:
        proc = subprocess.run(
            [str(script), "--one-shot"],
            capture_output=False,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        state.log_line("dispatch", f"detector '{name}' timed out after {timeout}s — killed")
        # Stamp last-run even on timeout so a chronically-slow detector backs
        # off to its cadence instead of re-firing (and re-hanging) every fire.
        _mark_detector_ran(name)
        return
    except OSError as exc:
        state.log_line("dispatch", f"detector '{name}' spawn failed: {exc}")
        return
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

    # Also clear any pending post-compact resume flag: a rate-limit resume cue
    # already says "resume the pending task", which subsumes it. Clearing both
    # here prevents a second, redundant [janitor-resume] on the next fire when a
    # compaction and a rate-limit happened to overlap in the same window.
    sd = state.state_dir()
    for p in (
        flag,
        since_file,
        sd / "resume-after-compact.flag",
        sd / "resume-after-compact.ts",
    ):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    state.log_line("dispatch", f"rate-limit cleared after {age}s, resume cue emitted")
    return True


def _phase_compact_resume() -> bool:
    """Return True if a [janitor-resume] line was emitted for a post-compact resume.

    The PostCompact hook (scripts/hooks/post-compact-resume.py) writes
    `resume-after-compact.flag` (the resume directive) + a `.ts` sidecar
    immediately after a context compaction. A compaction returns the REPL to
    idle — Claude Code does not auto-continue the interrupted task (and for the
    watchdog's manual /compact it never did), and a hook cannot start a fresh
    turn. The heartbeat cron is the only thing that fires fresh turns, so this
    phase is the wake-up: it reads the flag, emits ONE [janitor-resume] cue
    carrying the directive, and clears the flag so the resume fires exactly once
    per compaction. Without it an unattended session stalls idle after every
    compact — fatal for the overnight task loop the context watchdog enables.

    Mirrors _phase_rate_limit_recovery: emit + clear + return True so main()
    skips the drift detectors this fire and the resume cue gets clean attention.
    """
    flag = state.state_dir() / "resume-after-compact.flag"
    if not flag.is_file():
        return False

    try:
        directive = flag.read_text(encoding="utf-8")
    except OSError:
        directive = ""
    # Defang against marker-mimicry (a TRDD title / directive file embedding a
    # fake `[janitor-…]` marker), collapse to a single bounded line.
    directive = state.sanitize_for_drift_line(directive)
    directive = " ".join(directive.split())
    if len(directive) > 280:
        directive = directive[:277] + "..."

    since_file = state.state_dir() / "resume-after-compact.ts"
    now = int(time.time())
    age = max(0, now - state.read_int_state(since_file, now))

    if directive:
        print(f"[janitor-resume] Context was compacted {age}s ago — auto-resume. {directive}")
    else:
        # Flag present but empty/unreadable: still cue a generic resume so the
        # session doesn't stall idle after a compaction.
        print(
            f"[janitor-resume] Context was compacted {age}s ago — auto-resume. "
            "Resume your previous in-flight task (check the TRDD board / your handoff)."
        )

    for p in (flag, since_file):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    state.log_line("dispatch", f"post-compact resume cue emitted (age {age}s)")
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


def _phase_guard_branch_protection() -> None:
    """Tier 2 guarded auto-apply for the branch-protection baseline.

    Runs scripts/guard/branch_protection_apply.py at the configured
    cadence (default 21600 = 6 h). The applier itself enforces every
    safety gate (guard_mode_enabled, admin viewer, default branch,
    idempotency). When any gate fails the applier exits 0 silently —
    so this phase is near-free on every fire that doesn't actually
    need to act.

    The whole phase is wrapped defensively so a guard-side fault never
    crashes the heartbeat — RULE-0 baseline.
    """
    interval = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_GUARD_BRANCH_PROTECTION_INTERVAL"),
        21600,
    )
    last_file = state.state_dir() / "last-run-guard-branch-protection.ts"
    last = state.read_int_state(last_file, 0)
    if (int(time.time()) - last) < interval:
        return
    script = _HERE / "guard" / "branch_protection_apply.py"
    if not script.is_file() or not os.access(script, os.X_OK):
        return
    try:
        subprocess.run(  # noqa: S603 - explicit args, no shell
            [str(script)],
            capture_output=False,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        state.log_line("dispatch", "guard branch-protection apply timed out")
    except OSError as exc:
        state.log_line("dispatch", f"guard branch-protection apply spawn failed: {exc}")
    state.atomic_write(last_file, str(int(time.time())))


def _phase_autofix_mode_reminder() -> None:
    """One drift line per day when /janitor-autofix-off is in effect.

    The user can opt out of the "act, don't ask" policy by running
    `/janitor-autofix-off`. When that sentinel is set the janitor still
    reports findings but no longer applies fixes — easy to forget. This
    phase emits a once-per-day reminder so the project author doesn't
    silently lose the autofix safety net for weeks.

    Dedup key is the local-date bucket; the reminder fires at most once
    every 24 h regardless of cron cadence. When autofix is back ON (the
    default), this phase is a near-free no-op (one file stat).
    """
    if not state.autofix_disabled():
        return
    today = datetime.now().astimezone().strftime("%Y%m%d")
    line = dedupe.emit_once(
        state.state_dir() / "autofix-off-seen.txt",
        f"autofix-off@{today}",
        "[autofix-off] Janitor autofix is OFF in this project — findings will surface but no fixes will be applied without confirmation. Run /janitor-autofix-on to re-enable.",
    )
    if line is not None:
        print(line)


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

    # Phase 1.1: post-compact resume. A context compaction leaves the REPL idle;
    # without this nudge an unattended session stalls forever after the watchdog
    # (or a native auto-compact) compacts. The PostCompact hook drops
    # resume-after-compact.flag; we surface it as a single [janitor-resume] cue
    # exactly once and return early — like rate-limit recovery — so the resume
    # gets clean attention with no detector noise this fire.
    if _phase_compact_resume():
        return 0

    # Phase 1.5: heartbeat auto-renew (silent on v0.5.2+ crons).
    _phase_heartbeat_renew()

    # Phase 1.55: autofix-OFF daily reminder. Free no-op when ON (default).
    _phase_autofix_mode_reminder()

    # Phase 1.56: Tier 2 guarded action — branch-protection baseline applier.
    # No-op unless guard_mode_enabled AND autofix_enabled AND every safety
    # gate inside the applier passes. Cadence-throttled (default 6 h).
    _phase_guard_branch_protection()

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
