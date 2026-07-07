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
  $PROJECT_ROOT/.janitor/state/keep-going              # written by /janitor-keep-going (never-stop nudge opt-in)

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

# The cache-version PARENT — the dir that holds every cached `<version>/` of the
# janitor (the same dir the dispatcher-stub's PLUGIN_CACHE_ROOT points at). This
# dispatch.py lives at `<cache-parent>/<version>/scripts/dispatch.py`, so two
# parents up from `scripts/` is the version-list root the C4 rollback decision
# (`_phase_crash_loop_rollback`) reasons over. Overridable for tests via
# JANITOR_CACHE_PARENT so no test touches the real ~/.claude cache tree.
_PLUGIN_CACHE_PARENT = Path(os.environ.get("JANITOR_CACHE_PARENT") or str(_HERE.parent.parent))

import dedupe  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402
import version_update_lib as vu  # noqa: E402  # C4 auto-rollback decision (TRDD-T198DT1W)

# Detector roster: (name, default cadence in seconds, env-var override).
# Order matches dispatch.sh — detectors with shorter cadences run first
# only because that order is human-readable (cadence is enforced
# per-detector via last-run files, not by ordering).
_DETECTORS: list[tuple[str, int, str]] = [
    ("pr-reconciler", 900, "CLAUDE_PLUGIN_OPTION_PR_RECONCILER_INTERVAL"),
    # ci-status: after a push, watch the pushed commit's CI and emit a drift line (notify
    # the main Claude) if it failed. Short cadence so a failure surfaces within ~1 heartbeat
    # of CI completing; cheap no-op (one `git rev-parse`) when the pushed SHA is already
    # resolved. FULL mode only. Opt-out CLAUDE_PLUGIN_OPTION_CI_STATUS_ENABLED (TRDD-AKH7JRAA).
    ("ci-status", 60, "CLAUDE_PLUGIN_OPTION_CI_STATUS_INTERVAL"),
    ("worktree-janitor", 900, "CLAUDE_PLUGIN_OPTION_WORKTREE_JANITOR_INTERVAL"),
    ("trdd-drift", 3600, "CLAUDE_PLUGIN_OPTION_TRDD_DRIFT_INTERVAL"),
    ("trdd-reminder", 14400, "CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL"),
    ("report-to-trdd-drift", 21600, "CLAUDE_PLUGIN_OPTION_REPORT_TO_TRDD_INTERVAL"),
    # trdd-state-reconciliation cross-checks a TRDD's CLAIMED column against the
    # GROUND TRUTH of whether its code is in a released tag (TRDD-15ECPBSA).
    # Board drift is SLOW (a TRDD ships, the column lags) and the check runs
    # `git log` + `git tag --contains`, so a DAILY cadence is right — frequent
    # enough to surface a shipped-but-open TRDD within a day, rare enough that
    # the git work is negligible. SURFACE-ONLY (report + drift line; mutates no
    # TRDD); per-(TRDD,verdict) seen-file dedupe avoids re-nagging.
    ("trdd-state-reconciliation", 86400, "CLAUDE_PLUGIN_OPTION_TRDD_RECONCILIATION_INTERVAL"),
    ("task-pr-mismatch", 1800, "CLAUDE_PLUGIN_OPTION_TASK_PR_MISMATCH_INTERVAL"),
    ("stale-task", 1800, "CLAUDE_PLUGIN_OPTION_STALE_TASK_INTERVAL"),
    ("dirty-tree", 300, "CLAUDE_PLUGIN_OPTION_DIRTY_TREE_INTERVAL"),
    ("subagent-report", 3600, "CLAUDE_PLUGIN_OPTION_SUBAGENT_REPORT_INTERVAL"),
    ("version-update", 300, "CLAUDE_PLUGIN_OPTION_VERSION_CHECK_INTERVAL"),
    ("trashcan-purge", 86400, "CLAUDE_PLUGIN_OPTION_TRASHCAN_PURGE_INTERVAL"),
    # reports-purge runs daily (S8, TRDD-LCO8229M): a 30d retention window
    # doesn't need a tighter cadence, and the seen-file caps only matter at
    # hundreds of lines. Silent no-op when reports/ is absent.
    ("reports-purge", 86400, "CLAUDE_PLUGIN_OPTION_REPORTS_PURGE_INTERVAL"),
    # screenshot-purge runs hourly: 72h is the default age threshold so a
    # 1h cadence catches expiries promptly AND re-probes free disk while
    # the user is mid-task. Skipped silently when reports/screenshots/ is
    # absent, which is the common case on non-UI projects.
    ("screenshot-purge", 3600, "CLAUDE_PLUGIN_OPTION_SCREENSHOT_PURGE_INTERVAL"),
    # v0.4.0 additions:
    ("remote-credentials", 3600, "CLAUDE_PLUGIN_OPTION_REMOTE_CREDENTIALS_INTERVAL"),
    ("stale-stash", 86400, "CLAUDE_PLUGIN_OPTION_STALE_STASH_INTERVAL"),
    ("nested-git-safety", 3600, "CLAUDE_PLUGIN_OPTION_NESTED_GIT_SAFETY_INTERVAL"),
    ("tracked-ignored", 3600, "CLAUDE_PLUGIN_OPTION_TRACKED_IGNORED_INTERVAL"),
    # marketplace-refresh: per-session, scoped to local+project marketplaces.
    # Global bulk refresh is the daemon's job (every 20 min). Runs BEFORE the
    # plugin-* detectors so the manifest is fresh by the time they consult it.
    ("marketplace-refresh", 300, "CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_INTERVAL"),
    # user-plugins-update is Track 1 of the auto-update directive — cron-
    # global, project-agnostic, no enabled filter (all user-scope plugins).
    ("user-plugins-update", 300, "CLAUDE_PLUGIN_OPTION_USER_PLUGINS_UPDATE_INTERVAL"),
    # local-plugins-update is Track 2a — per-project, reads
    # .claude/settings.local.json, filters to enabled, no git mutation
    # (settings.local.json is gitignored by convention).
    ("local-plugins-update", 300, "CLAUDE_PLUGIN_OPTION_LOCAL_PLUGINS_UPDATE_INTERVAL"),
    # project-plugins-update is Track 2b — per-project, reads
    # .claude/settings.json (git-tracked), filters to enabled. On
    # settings.json drift, emits a [project-plugins-commit-needed]
    # drift line for Claude to commit via porcelain `git commit`.
    ("project-plugins-update", 300, "CLAUDE_PLUGIN_OPTION_PROJECT_PLUGINS_UPDATE_INTERVAL"),
    ("plugin-updates", 300, "CLAUDE_PLUGIN_OPTION_PLUGIN_UPDATES_INTERVAL"),
    ("mcp-config-drift", 3600, "CLAUDE_PLUGIN_OPTION_MCP_CONFIG_DRIFT_INTERVAL"),
    ("settings-scope-drift", 3600, "CLAUDE_PLUGIN_OPTION_SETTINGS_SCOPE_DRIFT_INTERVAL"),
    ("subagent-scope-drift", 3600, "CLAUDE_PLUGIN_OPTION_SUBAGENT_SCOPE_DRIFT_INTERVAL"),
    ("claude-md-scope-drift", 3600, "CLAUDE_PLUGIN_OPTION_CLAUDE_MD_SCOPE_DRIFT_INTERVAL"),
    ("cross-scope-reference-drift", 3600, "CLAUDE_PLUGIN_OPTION_CROSS_SCOPE_REFERENCE_DRIFT_INTERVAL"),
    # v0.5.1 additions — security monitoring (CI/CD + repo hardening). Both
    # are READ-ONLY: they surface findings, they never mutate the repo.
    #   workflow-security runs every heartbeat — the detector content-hashes
    #   the workflow files and short-circuits when nothing changed, so an
    #   unchanged-workflows fire is ~free, while a newly-introduced injection
    #   or secret-leak surfaces within one cadence.
    ("workflow-security", 300, "CLAUDE_PLUGIN_OPTION_WORKFLOW_SECURITY_INTERVAL"),
    #   branch-protection polls the GitHub API (gh), so it runs on a slow 6h
    #   cadence — branch rulesets change rarely; its seen-file nags once until
    #   fixed and re-arms (emit_forget) if protection is later removed.
    ("branch-protection", 21600, "CLAUDE_PLUGIN_OPTION_BRANCH_PROTECTION_INTERVAL"),
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
    # run /janitor-refresh-claude-logins BEFORE a per-account claude.ai session cookie
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
    # memory-librarian SURFACES (never mutates) memory aggregation/conflict
    # candidates in the per-project agent-memory corpus (~/.claude/projects/
    # <slug>/memory/) — the librarian half of the memory system (TRDD-c77dae09).
    # It drives off memgrep index/links to cheaply (no-LLM) cluster same-topic
    # notes (aggregation candidates) and flag unlinked same-topic pairs (conflict
    # candidates), writes a memory-reorg-proposed.md, and emits one line. It NEVER
    # moves/merges/edits/deletes a note — an AGENT does the conscious reorg. Silent
    # no-op when the memory dir / memgrep binary is absent or the candidate set is
    # unchanged. 6h cadence — the corpus changes slowly and the scan is bounded +
    # content-fingerprint deduped, so unchanged fires are near-free.
    ("memory-librarian", 21600, "CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL"),
    # memory-maintenance is the wikimem-editor SCHEDULER (TRDD-b4b9e27c, the
    # SCHEDULE layer) — the DETECT→SCHEDULE pair with memory-librarian above.
    # NEAR-FREE per fire: a stat + int-compare on the global last-run stamp via
    # memory_settings.is_due — NO memgrep, no corpus read. When an editorial pass
    # is due it takes a machine-wide flock (skip-if-held so N sessions fire ONCE),
    # round-robins ONE scope/heartbeat, stamps mark_ran, and emits a single BARE
    # forge-proof marker ([janitor-memory-*] — split/repair/harvest/consolidate/conflict) the cron
    # turn silent-executes. Honors editor_enabled() + the edit_project_scope gate
    # (PROJECT skipped unless opted in — it's in-repo + unpushable). The detector's
    # OWN per-intervention is_due is the real cadence, so this dispatch cadence is
    # short (300s = every heartbeat) to give the due-check a chance each fire; an
    # idle fire is essentially free.
    ("memory-maintenance", 300, "CLAUDE_PLUGIN_OPTION_MEMORY_MAINTENANCE_INTERVAL"),
    # project-map-drift nudges when the fenced CLAUDE.md project map is stale
    # (TRDD-e247a349). DETECTION ONLY — digest-compare against the fence
    # header, zero extraction — and it NEVER writes CLAUDE.md: the write busts
    # the prompt-prefix cache (§5) and would race human/Claude edits; the
    # refresh is agent-run via repomap_generate.py, which carries the gen-lock
    # + lost-update guard + byte-preservation invariant. Opt-in flag
    # (`repomap-opt-in.flag`, default OFF) → total no-op until
    # /janitor-auto-repomap-on. 6h cadence — a stale map is advisory.
    ("project-map-drift", 21600, "CLAUDE_PLUGIN_OPTION_PROJECT_MAP_DRIFT_INTERVAL"),
    # memory-scope-leak keeps the PUSHED memory scope clean (TRDD-c77dae09, the
    # THREE-SCOPE addendum). The PROJECT scope (<git-root>/memory/) is git-tracked
    # and pushed, so it must NEVER carry machine/user-private data; this detector
    # scans those pages with the private-path lib + privacy PII shapes + the
    # credential libs + an entropy pass, and guards the gitignore invariants
    # (PROJECT memory/ must be TRACKED; a LOCAL-shaped store must not be committed).
    # Each leak surfaces a "demote to LOCAL scope before push" finding into
    # memory-scope-leak-proposed.md. ZERO page mutation (RULE 0) — an agent demotes.
    # Silent no-op when not a git repo / no PROJECT memory dir / unchanged finding
    # set. 1h cadence — leaks should be caught quickly before a push, and the scan
    # is bounded + content-fingerprint deduped so unchanged fires are near-free.
    ("memory-scope-leak", 3600, "CLAUDE_PLUGIN_OPTION_MEMORY_SCOPE_LEAK_INTERVAL"),
    # project-memory-tracked guarantees the PROJECT memory scope
    # (<repo>/.claude/project/memory/) is git-TRACKED via a .gitignore EXCEPTION
    # (TRDD-3f7b6807, Phase 2) — that scope is shared with every contributor and
    # MUST live in the repo. When the scope is ignored it APPENDS the canonical
    # exception triplet idempotently + atomically; it NEVER `git add`/`git add -f`
    # and NEVER rewrites an existing ignore line. Surfaces ONE drift line only
    # when it added the exception or a directory-pruning ignore (bare `.claude/`)
    # blocks it (needs-manual); silent for absent / already-tracked / probe-error.
    # Daily cadence — .gitignore changes rarely and the probe is one cheap
    # `git check-ignore`, so unchanged fires are near-free.
    ("project-memory-tracked", 86400, "CLAUDE_PLUGIN_OPTION_PROJECT_MEMORY_TRACKED_INTERVAL"),
    # memorize-nudge keeps the wiki POPULATED (TRDD-87935f21, priority #6): when
    # substantive (non-bookkeeping) commits have landed since the last memory note,
    # it reminds the agent to /janitor-memory-write what changed + WHY. Reads git +
    # LOCAL/PROJECT memory mtimes only; NEVER mutates. Never nags — silent unless the
    # wiki is already in use (adoption gate), needs ≥3 substantive commits, dedupes
    # to one nudge per interval, and auto-silences the instant a note is written.
    # 4h cadence; an idle fire is one bounded `git log`.
    ("memorize-nudge", 14400, "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_INTERVAL"),
    # why-in-commits enforces the commit-discipline rule (TRDD-87935f21, priority #6):
    # when recent feat/fix/refactor/perf commits are subject-only (no body → no WHY),
    # it reminds the agent to record the WHY (rules/commit-discipline.md). ai-maestro
    # -gated (the fleet that mandates it + uses conventional commits); read-only git
    # log; never nags — only the substantive types, ≥3 deficient, 3-day window, and
    # set-based dedupe (one nudge per distinct deficient set, not per interval).
    ("why-in-commits", 14400, "CLAUDE_PLUGIN_OPTION_WHY_IN_COMMITS_INTERVAL"),
    # janitor-install-scope warns if ai-maestro-janitor is enabled at PROJECT/LOCAL
    # scope — it MUST be a USER-only install (it guards OAuth + the global daemon for
    # the whole machine; TRDD-db169d9e R5). Runs in EVERY project (the invariant is
    # universal, not ai-maestro-specific); silent in the normal case (user-scope
    # install). 6h cadence — install config changes rarely; dedupe keeps it to one
    # nag until the config changes.
    ("janitor-install-scope", 21600, "CLAUDE_PLUGIN_OPTION_JANITOR_INSTALL_SCOPE_INTERVAL"),
    # window-burn-rate reads each account's live 5h/7d utilization% READ-ONLY via the OAuth
    # rotator and alarms when a window burns >= RATIO× its even-pace budget (heading for an
    # early rate-limit), naming the top-consuming project when it trips. 15-min cadence;
    # opt-out CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED; fail-open (silent on any rotator/
    # network failure); the detector self-cadences on the same interval too (TRDD-OY0W6LX5).
    ("window-burn-rate", 900, "CLAUDE_PLUGIN_OPTION_WINDOW_BURN_INTERVAL"),
    # token-usage-anomaly (TRDD-EDSFEQ5C): the SLOW per-5-min baseline complement of the
    # fast pre-tool-token-budget guard. It shipped with its own gate/dedupe but was never
    # added to this roster, so it NEVER RAN (found by the whole-codebase review,
    # TRDD-E9LMBNPE). Reads token-meter.jsonl locally — cheap; self-gates on
    # CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_ENABLED.
    ("token-usage-anomaly", 300, "CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_INTERVAL"),
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
    timeout = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT"), 120)
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


def _phase_globally_disarmed() -> bool:
    """Return True if the MACHINE-WIDE kill-switch is set (/janitor-global-disarm).

    The kill-switch is the TRUE STOP — it makes the global daemon EXIT and per-session
    heartbeats stop re-spawning it (TRDD-a3fa4d5d). When set, main() emits a bare
    [janitor-self-disarm] marker so THIS session DELETES its own heartbeat cron.

    WHY self-disarm and not the old silent short-circuit (TRDD-NJ22HNC3): a cron FIRE is a
    full Claude turn that re-reads the whole session context (~618k cached tokens, billed at
    the 0.1x cache-read rate — NOT free) BEFORE any detector runs. Silencing the detectors
    saved nothing — the expensive fire still happened every 5 min in every armed session, the
    user-reported "many janitors still running / token bleed". The only way a fire costs zero
    is to STOP FIRING, i.e. delete the cron (TRDD-RQ9FIFX6). `/janitor-global-arm` clears it.

    WHY a separate phase from `_phase_global_paused`: the two flags are distinct daemon STATES
    (pause IDLES a live daemon, disarm EXITS it) but drive the SAME heartbeat action — emit
    [janitor-self-disarm], run nothing. Keeping them separate keeps the daemon-side semantics
    honest while sharing the heartbeat-side self-disarm."""
    if gs.kill_switch_present():
        state.log_line("dispatch", "global-disarm (kill-switch) set -> emit [janitor-self-disarm]")
        return True
    return False


def _phase_global_paused() -> bool:
    """Return True if the MACHINE-WIDE global pause is set (TRDD-a3fa4d5d). When set, main()
    emits a bare [janitor-self-disarm] marker so the session DELETES its own heartbeat cron
    (truly free; a fired turn can't be made cheap -- TRDD-RQ9FIFX6). The DAEMON stays alive
    (pause IDLES it, it does not EXIT), so global-pause is the "stop the project heartbeats but
    keep the daemon" control. `/janitor-global-unpause` lifts it; sessions re-arm on next start."""
    if gs.global_pause_present():
        state.log_line("dispatch", "global-pause set -> emit [janitor-self-disarm]")
        return True
    return False


def _maintenance_mode_active() -> bool:
    """Return True iff maintenance-mode is active for THIS session — either the
    per-session flag (`.janitor/state/maintenance-mode`) or the machine-wide flag
    (`/janitor-global-maintenance`).

    Maintenance-mode (TRDD-FPL60EKV) keeps the heartbeat ARMED but makes each fire do
    the MINIMUM: the fired turn re-reads the session context at the 0.1x prompt-cache
    READ rate, which RESETS the 5-minute cache TTL, and dispatch then returns
    immediately — no detectors, no daemon spawn, no agent work, no output. WHY it
    matters: letting the cache DIE (disarm → no fires) forces the next real turn to
    REWRITE the whole context at the 1.0x rate (~10x a cache read). So a maintenance
    fire costs ~1/10 of a cache-death rewrite — the cheapest way to keep a session
    (and thus its whole project's cache) warm. It is the middle ground between FULL
    (fire + all due chores) and DISARM (stop firing, cache dies)."""
    if (state.state_dir() / "maintenance-mode").is_file():
        return True
    return gs.maintenance_mode_present()


def _resolve_heartbeat_mode() -> str:
    """Resolve what THIS fire does: 'full' | 'maintenance' | 'stop'.

    - 'maintenance' (highest priority — an explicit keep-warm intent, local OR
      global): refresh the cache and do nothing else. Chosen EVEN under a global
      stop, so a session can stay cache-warm while the fleet's expensive daemon +
      fleet-recovery stay DOWN — closing the "keep one session alive => clear the
      global switch => wake the whole fleet" gap (the July-budget burn).
    - 'stop' (a machine-wide /janitor-global-disarm or -pause, and NO maintenance
      opt-in): self-disarm — delete this cron so a fire costs zero (TRDD-RQ9FIFX6);
      the right choice for LONG idle, where one 1.0x rewrite on return beats many
      cache-read fires.
    - 'full': the normal heartbeat — cache refresh + DUE detectors + daemon."""
    if _maintenance_mode_active():
        return "maintenance"
    if _phase_globally_disarmed() or _phase_global_paused():
        return "stop"
    return "full"


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
        print(f"[janitor-resume] rate-limit cleared after {age}s — API is reachable again. Resume the previous pending task.")
    else:
        # since-file was missing or in the future (clock skew); still cue resume.
        print("[janitor-resume] rate-limit cleared (duration unknown) — API is reachable again. Resume the previous pending task.")

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
        print(f"[janitor-resume] Context was compacted {age}s ago — auto-resume. Resume your previous in-flight task (check the TRDD board / your handoff).")

    for p in (flag, since_file):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    state.log_line("dispatch", f"post-compact resume cue emitted (age {age}s)")
    return True


def _phase_plugin_reload() -> None:
    """Emit a bare `[janitor-reload]` marker once-per-session when the daemon's
    reload GENERATION advances past what THIS project's heartbeat has acked.

    The daemon stamps ONE machine-global reload generation (epoch) after a
    `claude plugin update` actually changes a plugin's version. We compare it to
    a per-PROJECT `reload-acked.ts` and advance only that stamp — we NEVER clear
    the global generation.

    WHY per-project ack and not a cleared global flag: the old design read a
    single global boolean and CLEARED it here, so whichever session fired first
    consumed the one-shot nudge and every OTHER live session (notably an
    autonomous fleet agent in a different project) never saw `[janitor-reload]`
    and stayed on stale plugin code until restart — the exact "CPV agents not
    registered" failure a MANAGER-fleet session hit. A never-cleared generation
    plus a per-project ack lets every project's heartbeat reload exactly once per
    update, with no session starving another.
    """
    gen = gs.reload_generation()
    if gen <= 0:
        return
    acked_path = state.state_dir() / "reload-acked.ts"
    # Per-project ack: reload once when the global generation exceeds what this
    # project last acked. The SessionStart hook SEEDS this stamp to the at-start
    # generation, so a fresh session (already on current plugins) has acked == gen
    # and stays silent, while a session that was live across an update has
    # acked < gen and reloads. Default 0 when the stamp is absent (a pre-feature
    # or un-seeded session) is the SELF-HEAL path: emit once, write the stamp, then
    # track normally — defaulting to `gen` instead would DEADLOCK an un-seeded
    # session (it would never emit, so never write the stamp, so never reload).
    acked = state.read_int_state(acked_path, 0)
    if acked >= gen:
        return
    state.atomic_write(acked_path, str(gen))
    print("[janitor-reload]")
    state.log_line(
        "dispatch",
        f"reload generation {gen} > project ack → [janitor-reload] emitted (per-project ack advanced; global generation left intact)",
    )


def _phase_skills_reload() -> None:
    """Emit a bare `[janitor-reload-skills]` marker once-per-session when the
    STANDALONE-skills reload generation advances past what THIS project's heartbeat
    has acked (TRDD-LQU7OXXV follow-up).

    The SEPARATE sibling of `_phase_plugin_reload`: `/janitor-global-reload-skills`
    stamps `skills-reload-needed.flag` (a never-cleared epoch generation), and each
    session's heartbeat reloads exactly once per bump via a per-project
    `skills-reload-acked.ts` — the same generation+ack design that stops one session
    starving another. The cron prompt maps `[janitor-reload-skills]` → silently run
    `/janitor-reload-skills` (which types `/reload-skills` into this pane), so newly
    installed STANDALONE (non-plugin) skills/commands load fleet-wide. Distinct from
    `/reload-plugins`, which only reloads plugin-bundled skills.
    """
    gen = gs.skills_reload_generation()
    if gen <= 0:
        return
    acked_path = state.state_dir() / "skills-reload-acked.ts"
    # Per-project ack, seeded at SessionStart to the at-start generation so a FRESH
    # session (already carrying the current standalone skills) stays silent, while a
    # session live across a `/janitor-global-reload-skills` sees acked < gen and
    # reloads once. Default 0 when absent is the SELF-HEAL path (emit once, write the
    # stamp, track normally); defaulting to `gen` would DEADLOCK an un-seeded session.
    acked = state.read_int_state(acked_path, 0)
    if acked >= gen:
        return
    state.atomic_write(acked_path, str(gen))
    print("[janitor-reload-skills]")
    state.log_line(
        "dispatch",
        f"skills-reload generation {gen} > project ack → [janitor-reload-skills] emitted (per-project ack advanced; global generation left intact)",
    )


def _phase_crash_loop_rollback() -> None:
    """C4 (TRDD-T198DT1W) — auto-rollback a self-update that won't STAY alive.

    Symptom this defends against: a janitor self-update lands a new cache version
    whose daemon/heartbeat crashes or loops on start (a bad release). The
    dispatcher-stub auto-rolls into the newest version on every fire, so a bad
    newest version would keep killing the heartbeat. The global-state spawn
    breaker already DETECTS the dying daemon (it refuses to keep re-spawning it);
    this phase is the PRODUCER half of the rollback: when the breaker is tripped
    AND a strictly-older runnable version exists to fall back to, it QUARANTINES
    the newest version (``version_update_lib.add_quarantine``). The stub's C3
    quarantine-skip (already shipped) then walks down to the known-good older
    version on the next fire — auto-rollback, no new stub change — and a human is
    alerted once via ``[janitor-rollback]``.

    CARDINAL RULE — FAIL-OPEN / ZERO-FALSE-ROLLBACK: the decision
    (``vu.plan_crash_loop_rollback``) returns a target ONLY when the daemon is
    PROVABLY crash-looping (a healthy update spawns once and stays alive, so the
    breaker never trips → a good version is NEVER rolled back), a fallback exists,
    and the newest is not already quarantined (idempotent → alert once). With no
    fallback the phase does nothing and the stub's own fail-open backstop still
    runs the newest — a bad heartbeat beats a dead one. The whole phase is wrapped
    defensively so a global-state / cache fault can never crash the heartbeat;
    worst case the rollback simply doesn't happen this fire.

    Phase order: this precedes ``_phase_daemon_restart_if_stale`` so the
    quarantine lands BEFORE we consider restarting the daemon — though the stub
    (not this phase) is what actually picks the version on the next fire.
    """
    try:
        if not gs.crash_loop_active():
            return  # not crash-looping → nothing to roll back (the common case)
        plan = vu.plan_crash_loop_rollback(
            _PLUGIN_CACHE_PARENT,
            crash_loop=True,
        )
        if plan is None:
            return  # crash-looping but no safe fallback / already quarantined
        bad, fallback = plan
        if not vu.add_quarantine(bad, "crash-loop"):
            state.log_line(
                "dispatch",
                f"crash-loop rollback: add_quarantine({bad}) failed (DATA-dir I/O) — stub fail-open backstop still runs the newest",
            )
            return
        respawns = gs.recent_spawn_count()
        state.log_line(
            "dispatch",
            f"crash-loop rollback: quarantined newest={bad} (daemon respawned ~{respawns}x) → stub falls back to {fallback}",
        )
        # Alert the human ONCE per distinct bad version (dedupe key = the version),
        # so a still-crash-looping cache doesn't re-emit every fire.
        line = dedupe.emit_once(
            state.state_dir() / "crash-loop-rollback-seen.txt",
            f"rollback@{bad}",
            f"[janitor-rollback] janitor self-update {bad} crash-looped — quarantined and rolled back to {fallback}. Investigate {bad} before re-updating.",
        )
        if line is not None:
            print(line)
    except Exception as exc:  # noqa: BLE001 — a rollback fault must never crash the heartbeat
        state.log_line("dispatch", f"crash-loop rollback phase failed: {exc}")


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
    threshold_days = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_HEARTBEAT_RENEWAL_THRESHOLD_DAYS"), 6)
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


def _phase_keep_going_nudge(mode: str) -> None:
    """Emit a never-stop continue-nudge when the session explicitly opted into it.

    WHY (TRDD-TKNSTP82 Part B, user 2026-07-02): maintenance-mode was over-optimized
    into full silence — an unattended agent that finishes a turn while maintenance is
    active (or with the standalone `/janitor-keep-going` flag set) had nothing telling
    it to keep working, so it silently stalled forever. This phase EMITS a
    resume-shaped nudge but does NOT early-return — callers downstream (the
    maintenance early-return that follows it in main(), or the full detector roster)
    run exactly as they did before this phase existed.

    RUNAWAY GUARD: fires ONLY under an explicit, deliberate opt-in — the per-session
    `.janitor/state/keep-going` flag (see /janitor-keep-going) OR `mode ==
    "maintenance"`. A plain full-mode session with neither set stays silent here and
    idles normally, so this can never cause a fleet-wide token runaway on default /
    interactive sessions.

    No dedupe: unlike the day-bucketed renew nudge above, this is meant to re-fire on
    EVERY due heartbeat while the opt-in holds — that repetition is the whole
    "never stop" point (a one-time nudge would miss a session that stays idle across
    several heartbeats in a row).
    """
    keep_going_flag = state.state_dir() / "keep-going"
    if not keep_going_flag.is_file() and mode != "maintenance":
        return
    print("[janitor-resume]")
    print("continue your pending task (keep-going mode) — if nothing remains, say so briefly and run /janitor-keep-going off")


def _phase_user_presence_breadcrumb() -> None:
    """Refresh the cross-plugin user-presence breadcrumb's liveness stamp.

    Writes ~/.aimaestro/state/user-presence.json's `written_at_epoch` on every
    non-paused fire (the heartbeat firing IS the liveness proof the MANAGER's
    presence tracker reads as a server-down fallback — TRDD-fb4850b5). It does
    NOT touch `last_user_input_epoch` — that field is owned by the
    UserPromptSubmit hook and reflects genuine user input, not cron ticks.

    Cheap (one read + one atomic write) and best-effort: `refresh_user_presence_
    written_at` swallows OSError internally, and this wrapper catches anything
    else so a breadcrumb problem can never break the heartbeat.
    """
    try:
        state.refresh_user_presence_written_at()
    except Exception as exc:  # noqa: BLE001
        state.log_line("dispatch", f"user-presence refresh failed: {exc}")


def main() -> int:
    state.init_state()

    # Phase 0: resolve this fire's MODE — full | maintenance | stop (TRDD-FPL60EKV).
    # A fired turn re-reads the whole session context (~618k cached tokens at the 0.1x
    # cache-READ rate — NOT free, but 1/10 of the 1.0x REWRITE the next real turn pays
    # if the cache DIES). So there are THREE intents, not two:
    #   * stop        — a machine-wide /janitor-global-disarm (kill-switch, TRDD-NJ22HNC3)
    #                   or -pause (TRDD-a3fa4d5d) with NO maintenance opt-in → self-disarm:
    #                   delete this cron so a fire costs zero (TRDD-RQ9FIFX6). Best for LONG
    #                   idle. dispatch can't call CronDelete (a session tool), so it signals
    #                   the session to run /janitor-disarm; self-limiting once the cron is gone.
    #   * maintenance — keep firing but do ONLY the cache refresh (no detectors, no daemon, no
    #                   output). Best for keeping a session/project cache warm at 1/10 the cost
    #                   of letting it die and rewriting.
    #   * full        — the normal heartbeat (cache refresh + due detectors + daemon).
    mode = _resolve_heartbeat_mode()
    if mode == "stop":
        # Bare marker on its own line — the cron prompt maps an exact [janitor-self-disarm]
        # line to "silently run /janitor-disarm". Crons armed before that clause shipped
        # surface it verbatim (harmless) and need a one-time manual /janitor-disarm (the
        # prompt is baked at arm-time — re-arm rollout lag).
        print("[janitor-self-disarm]")
        return 0
    # Phase 0.05: per-project TEMPORARY pause (.janitor/state/paused) — auto-expires and resumes
    # the SAME cron in place, so it stays a silent skip and must NOT self-disarm (deleting the
    # cron would break its in-place auto-resume).
    if _phase_paused():
        return 0

    # Phase 0.4: refresh the user-presence breadcrumb liveness stamp. Runs on
    # every non-paused fire, BEFORE the early-returning resume phases, so the
    # MANAGER's presence fallback sees a fresh written_at_epoch even on a fire
    # that exits early for a rate-limit/compact resume.
    _phase_user_presence_breadcrumb()

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

    # Phase 1.5a: never-stop keep-going nudge (TRDD-TKNSTP82 Part B). Placed AFTER the
    # renew phase and BEFORE the maintenance early-return below so BOTH modes get it:
    # maintenance fires the nudge then takes its cheap return (no detectors/daemon);
    # full fires the nudge then proceeds into the detector roster. It only emits under
    # an explicit opt-in (mode == "maintenance" OR the .janitor/state/keep-going flag),
    # so a plain full-mode session with neither set stays silent — see the phase's own
    # docstring for the runaway guard. A prior rate-limit/compact resume already
    # returned earlier in this function, so this phase is naturally skipped whenever
    # one of those already fired this turn.
    _phase_keep_going_nudge(mode)

    # Phase 1.5b: MAINTENANCE early-return (TRDD-FPL60EKV). The fire already refreshed the
    # prompt cache (the turn re-read the context at the 0.1x cache-READ rate, resetting the
    # 5-min TTL). Return HERE — after the cheap survival phases above (user-presence
    # breadcrumb, rate-limit resume, post-compact resume, the 7-day cron auto-renew, and the
    # never-stop keep-going nudge) so a cache-warm fire still keeps the cron alive and surfaces
    # a pending resume — but BEFORE the expensive phases below (guard, daemon spawn, detectors,
    # reloads) that maintenance exists to skip. This return used to sit at Phase 0, which
    # starved the renew (the cron silently expired after 7 days, defeating maintenance's
    # long-idle purpose) and the resume nudges (an unattended maintenance session stalled after
    # a compact/rate-limit) — /code-review B1/B2/B4.
    if mode == "maintenance":
        # TRDD-8PH8YOIJ: the daemon's EXISTENCE is survival, not a chore. A running daemon
        # keeps the 60s oauth-rotator-tick beating under maintenance (v0.28.1 B3), but when
        # the daemon DIED during maintenance nothing respawned it — sessions skipped the
        # spawn here, so the 5h window exhausted with no rotation and the user had to
        # /login by hand (incident 2026-07-02). ensure_daemon_running() is cheap+idempotent
        # (pid/heartbeat check; spawn only when dead) and honors the kill-switch +
        # crash-loop breaker by construction, so a deliberate global STOP still wins.
        # Maintenance idles the EXPENSIVE chores, never survival.
        try:
            gs.ensure_daemon_running()
        except Exception:  # noqa: BLE001 — survival is best-effort; never break the fire
            pass
        state.log_line("dispatch", "maintenance-mode: cache-refresh fire, survival phases only")
        return 0

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

    # Phase 1.62: standalone-skills reload signal — emit [janitor-reload-skills]
    # once when /janitor-global-reload-skills bumped the skills-reload generation.
    # The cron prompt's silent-execute clause runs /janitor-reload-skills, which
    # types /reload-skills into this pane (reloads NON-plugin skills/commands).
    _phase_skills_reload()

    # Phase 1.64: C4 bad-self-update auto-rollback. When the global-state spawn
    # breaker shows the daemon is crash-looping (a bad new version that won't stay
    # alive) AND a strictly-older runnable version exists, quarantine the newest so
    # the dispatcher-stub's C3 quarantine-skip rolls back to the known-good one on
    # the next fire. FAIL-OPEN: never fires for a healthy update (the breaker never
    # trips), never quarantines without a fallback; defensively wrapped. Precedes
    # the daemon-restart phase so the quarantine is in place first.
    _phase_crash_loop_rollback()

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
