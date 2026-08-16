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

import hashlib
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable
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
import findings_ledger  # noqa: E402  -- the quiet heartbeat's pull-model sink
import global_state as gs  # noqa: E402
import session_liveness  # noqa: E402  -- SSOT for the `FIRED rearm → iterm` evidence parse
import state  # noqa: E402
import token_meter as tm  # noqa: E402  # F1 reload-churn guard shared predicate (TRDD-Z582IKIR)
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
    # trdd-cross-card-blindspot: the sibling of trdd-state-reconciliation that
    # judges cards AGAINST EACH OTHER instead of against the tree — flags OPEN
    # cards that cite the same `external-refs:` issue without citing each other
    # (TRDD-XFPOAF2I). Board-hygiene, slow-moving; daily cadence.
    ("trdd-cross-card-blindspot", 86400, "CLAUDE_PLUGIN_OPTION_TRDD_CROSS_CARD_BLINDSPOT_INTERVAL"),
    # global-chore-blackout: alarm when a live ai-maestro server suppresses the janitor
    # daemon but has not absorbed the chores it displaced (ai-maestro#111). HOURLY — the
    # condition changes on the scale of days and the check is a few file stats, so a
    # tighter cadence buys nothing; the detector itself dedupes to one line per day.
    ("global-chore-blackout", 3600, "CLAUDE_PLUGIN_OPTION_GLOBAL_CHORE_BLACKOUT_INTERVAL"),
    # claimed-chore-stale: the MIRROR of the line above (TRDD-6CRC9SQQ item 1). Blackout
    # watches the chores the server did NOT claim; this watches the ones it DID and then
    # stopped running — the case `daemon_watchdog` is silent on by design, and the shape of
    # janitor#221's 3.7-day rotator wedge. Same hourly cadence and same reasoning: a few
    # file stats, a condition that moves on the scale of hours-to-days, one line per day.
    ("claimed-chore-stale", 3600, "CLAUDE_PLUGIN_OPTION_CLAIMED_CHORE_STALE_INTERVAL"),
    ("task-pr-mismatch", 1800, "CLAUDE_PLUGIN_OPTION_TASK_PR_MISMATCH_INTERVAL"),
    ("stale-task", 1800, "CLAUDE_PLUGIN_OPTION_STALE_TASK_INTERVAL"),
    ("dirty-tree", 300, "CLAUDE_PLUGIN_OPTION_DIRTY_TREE_INTERVAL"),
    # stale-index-lock: self-clear an orphaned .git/index.lock left behind by a
    # SIGKILLed/OOM-killed writer (janitor#245 follow-up) — the only production
    # caller of git_utils.clear_stale_index_lock. 5-minute cadence matches the
    # default min-age threshold so a genuinely stale lock clears on its first
    # eligible beat.
    ("stale-index-lock", 300, "CLAUDE_PLUGIN_OPTION_STALE_INDEX_LOCK_INTERVAL"),
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
    # runaway-file-growth runs hourly (TRDD-XM3FPJC0): a balloon takes hours or days to
    # matter, and the detector walks a filesystem tree — a tighter cadence would make it
    # the FS churn it exists to report. Silent no-op when the scan roots are absent.
    ("runaway-file-growth", 3600, "CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_GROWTH_INTERVAL"),
    # v0.4.0 additions:
    ("remote-credentials", 3600, "CLAUDE_PLUGIN_OPTION_REMOTE_CREDENTIALS_INTERVAL"),
    ("stale-stash", 86400, "CLAUDE_PLUGIN_OPTION_STALE_STASH_INTERVAL"),
    # The two GitHub notification chores. ALWAYS ON since the 2026-08-02 owner directive
    # ("must be a chore executed always by the janitor. no need to enable it") — the
    # opt-in sentinel and the session Monitor that used to gate them are both retired.
    # Each one's FIRST fire on a project is silent (it adopts the current state as its
    # baseline), so going always-on cannot dump a backlog into context.
    #
    # github-issues-watch (TRDD-2KQQAEPP): NEW issues / NEW comments on THIS project's own
    # tracker. 30-min cadence: issues do not churn every 5 min, and each due fire costs a
    # `gh` call.
    ("github-issues-watch", 1800, "CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_INTERVAL"),
    # gh-reply-watch: REPLIES to threads THIS project opened, on ANY repo — a different
    # question from the line above, and a different mechanism (it drives the one-shot
    # gh_notify_poll.py). It replaces a session-scoped `Monitor` loop that died on every
    # restart and compaction and had to be re-armed by hand; the heartbeat cannot forget.
    # 15 min sits far above GitHub's `X-Poll-Interval: 60` floor, and the heartbeat tier
    # bounds it further.
    ("gh-reply-watch", 900, "CLAUDE_PLUGIN_OPTION_GH_REPLY_WATCH_INTERVAL"),
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
    # fleet-github-config (TRDD-157OH2D7): the NEAR-FREE surface half of the fleet
    # GitHub-config audit. Reads ONLY the daemon's github-config-findings.json (one file
    # read + hash-dedupe, ZERO gh calls — all API cost lives in the daemon's 6h task), so
    # it can run on a tight cadence to surface a finding-set change promptly. Emits one
    # compact line + the /janitor-github-config-fix pointer; content-hash deduped so an
    # unchanged finding set never re-nags.
    ("fleet-github-config", 1800, "CLAUDE_PLUGIN_OPTION_FLEET_GITHUB_CONFIG_INTERVAL"),
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
    # agent-context-integrity is the OTHER half of the same threat (janitor#167):
    # ai-context-poisoning above catches a dependency that WRITES a context file;
    # this one catches a context file that arrived ALREADY POISONED via clone /
    # pull / a merged PR. That vector needs no execution at all, and CLAUDE.md is
    # auto-loaded into every session — so it was simultaneously the cheapest attack
    # and, until now, the only one with no automatic check. Cadence 1800s: the
    # trigger is a git operation, which is far more frequent than an install, and
    # the content-hash short-circuit makes an unchanged tree free.
    ("agent-context-integrity", 1800, "CLAUDE_PLUGIN_OPTION_AGENT_CONTEXT_INTEGRITY_INTERVAL"),
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
    # run /janitor-refresh-cc-logins BEFORE a per-account claude.ai session cookie
    # expires AND while OAuth is still healthy, so the two expiries never coincide
    # (TRDD-32acd15f). 6h cadence; machine-scoped daily dedupe keeps it gentle.
    ("oauth-cookie-reminder", 21600, "CLAUDE_PLUGIN_OPTION_OAUTH_COOKIE_REMINDER_INTERVAL"),
    # oauth-beacon-refresh keeps the live-identity beacon fresh (TRDD-6AABK2BG). The beacon
    # can ONLY be stamped from a context that can read the primary credential, and the daemon
    # is headless by design (FIX B2) — so the per-session heartbeat is the one component able
    # to do it. Without it the beacon is stamped once per SessionStart, a manual /login goes
    # unnoticed for up to 24h, and rotation evaluates the WRONG account's usage (always "within
    # limits") while the real one burns to its cap — the user then rotates by hand. Same
    # opt-in-by-presence gate as the other rotator detectors. 300s (every fire) is affordable
    # because a NON-prompting `mdat` attribute read gates the stamp: steady state is one cheap
    # metadata call and ZERO `-w` secret reads. Silent — a re-stamp is maintenance, not drift.
    ("oauth-beacon-refresh", 300, "CLAUDE_PLUGIN_OPTION_OAUTH_BEACON_REFRESH_INTERVAL"),
    # oauth-login-needed is the reactive sibling of oauth-cookie-reminder, same
    # opt-in-by-presence gate (a rotator home with a state.json). It surfaces the
    # accounts that need a ONE-TIME human login because they can neither self-renew
    # (no refreshToken) nor auto-bootstrap (no live claude.ai Chrome session), so
    # only a fresh sign-in via open-login.sh can revive them (the detector resolves that
    # script's real path per host — it is NOT at a fixed location; see janitor#258).
    # Distinct from cookie-reminder (the cookie/OAuth expiry RACE). 6h cadence;
    # machine-scoped daily dedupe keeps it gentle.
    ("oauth-login-needed", 21600, "CLAUDE_PLUGIN_OPTION_OAUTH_LOGIN_NEEDED_INTERVAL"),
    # keychain-health is the FLEET GUARDIAN's keychain probe (TRDD-KCHEALTH, the 2026-07-12
    # outage): a long-lived tmux/terminal server that survives a securityd recycle hands every
    # pane it forks a DEAD security session, in which the Keychain Services API fails outright
    # — so Claude Code there cannot read its OAuth item and every agent reports "Not logged
    # in" while the credential is perfectly fine (/login does NOT help). The per-session
    # heartbeat runs INSIDE that same security session, which makes it the one component able
    # to see what the agent sees. Checks FINDABILITY only — never `-w` (the secret read is
    # what causes the ACL prompt FLOOD, macos-keychain gotcha 3) — and routes every call
    # through safe_storage.run_security (hard timeout + denied-latch). 15 min cadence: this is
    # a fleet-down condition, so it must surface fast, and the probe is two cheap read-only
    # `security` calls. Verdict-deduped, so a persistent breakage nags once, not every fire.
    ("keychain-health", 900, "CLAUDE_PLUGIN_OPTION_KEYCHAIN_HEALTH_INTERVAL"),
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
    # orphaned-memory-maint closes memory-maintenance's own SILENT failure mode
    # (issue #238, TRDD-2112XCKO): a pending dispatch whose cron-turn agent spawn
    # failed (a partial-install registry, #232's shape — skills present, zero
    # ai-maestro-janitor:* agents enumerable) leaves memory-maint-pending.json
    # sitting unconsumed, indistinguishable from a healthy one. Self-contained —
    # reads only THIS project's own pending file (no fleet scan), because the same
    # broken-registry session that drops a pass still runs its own python
    # detectors fine. LOCAL scope gets a tighter staleness bound than USER/PROJECT
    # (LOCAL has no other session that can ever recover it — #238's core finding).
    # Findings route through findings_ledger (HIGH, MEMPASS-ORPHANED /
    # MEMPASS-MALFORMED). Cheap (one small JSON read + two stat-backed lookups),
    # so it rides the same short cadence as the scheduler it watches.
    ("orphaned-memory-maint", 300, "CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_INTERVAL"),
    # ticket-dispatch is the support-ticket SCHEDULER (TRDD-CGYMUKO6) — the same
    # DETECT→SCHEDULE→EXECUTE shape as memory-maintenance above, and for the same
    # reason: a python detector CANNOT spawn an agent, only the cron turn can. It
    # selects the due tickets under a machine-wide flock (skip-if-held, so N
    # sessions dispatch ONCE), marks them `dispatched`, and emits ONE bare
    # forge-proof [janitor-ticket] marker naming them. Authority lives in the
    # ticket's status, never in the marker — `ticket_cli start` refuses a ticket
    # nobody dispatched, so a hallucinated marker achieves nothing.
    # 300s (every fire): an empty queue is a directory glob that finds nothing, and
    # a critical incident should not wait out a long cadence before it is worked.
    ("ticket-dispatch", 300, "CLAUDE_PLUGIN_OPTION_TICKET_DISPATCH_INTERVAL"),
    # memgrep-index-health VALIDATES each memory scope's index and raises the issue
    # code (TRDD-CGYMUKO6) — the ticket system's motivating producer. It uses the
    # NON-HEALING `memgrep validate` path on purpose: `open()` self-heals, which is
    # exactly how the 2026-07-14 migration corruption stayed invisible for days
    # (every open quietly papered over it). 30 min, and a failure must RECUR before
    # it becomes a ticket — one failure is often a corruption the next open() heals;
    # a failure still there on the next probe means it is being RE-manufactured, and
    # a freshly built index that fails validation is a CODE bug.
    ("memgrep-index-health", 1800, "CLAUDE_PLUGIN_OPTION_MEMGREP_HEALTH_INTERVAL"),
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
    # wikimem-syntax surfaces memory pages memgrep can no longer PARSE (TRDD-VPTQ4067):
    # a `⟦`-bracket atom invisible to recall, an atom/page with no keywords/description,
    # or a corpus-wide DUPLICATE atom id. Runs the `wikimem_syntax_lint.py` rules (ported
    # from memgrep's memory.rs) over the 3 memory scopes; CRITICAL-only so the ~hundreds of
    # WARN advisories stay in the on-demand CLI. READ-ONLY (an agent fixes via
    # /janitor-memory-update). 1h cadence, per-SET content-hash dedupe (converges to silence
    # once fixed), fail-open.
    ("wikimem-syntax", 3600, "CLAUDE_PLUGIN_OPTION_WIKIMEM_SYNTAX_INTERVAL"),
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
    # reports-gitignore is project-memory-tracked's exact mirror image: that one keeps a
    # directory IN git, this one keeps two OUT. Same daily cadence, same fix-don't-nag posture,
    # and the same reason for a long interval — the answer only changes when someone edits
    # `.gitignore`, which is rare, and the cost of noticing an hour later is nil. Not on the
    # advisory list: when it speaks, it is either reporting that it edited a tracked file or
    # naming a leak that is already in git, and neither is something to read tomorrow.
    ("reports-gitignore", 86400, "CLAUDE_PLUGIN_OPTION_REPORTS_GITIGNORE_INTERVAL"),
    # memorize-nudge keeps the wiki POPULATED (TRDD-87935f21, priority #6): when
    # substantive (non-bookkeeping) commits have landed since the last memory note,
    # it reminds the agent to /janitor-memory-write what changed + WHY. Reads git +
    # LOCAL/PROJECT memory mtimes only; NEVER mutates. Never nags — silent unless the
    # wiki is already in use (adoption gate), needs ≥3 substantive commits, dedupes
    # to one nudge per interval, and auto-silences the instant a note is written.
    # 4h cadence; an idle fire is one bounded `git log`.
    ("memorize-nudge", 14400, "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_INTERVAL"),
    # peer-freeze-recovery (TRDD-KQ9WM4TZ): while an ai-maestro server owns the host the
    # daemon EXITS (§7.2) and takes session-liveness — the fleet freeze guardian — with it.
    # This runs the daemon's OWN beat over PEER sessions (never its own) from whichever
    # armed session wins a machine-wide flock, ONLY in that dark window (daemon dead AND
    # server alive). 300s detector cadence; the real pacing is its machine-wide 600s stamp.
    ("peer-freeze-recovery", 300, "CLAUDE_PLUGIN_OPTION_PEER_RECOVERY_INTERVAL"),
    # orphaned-resume-flag closes the janitor's own SILENT failure mode (issue #125): an
    # unconsumed `resume-after-compact.flag` means a compaction recorded a resume target
    # that no heartbeat ever delivered, i.e. that session's cron is dead/expired/unarmed.
    # Nothing noticed until now — the only detector was the human seeing their sessions
    # stop moving. Runs PER-SESSION as well as (eventually) in the daemon, because on a
    # host where a live ai-maestro server owns the machine the daemon is deliberately not
    # running (§7.2) — exactly when nothing is watching. Findings are recorded into the
    # AFFECTED project's ledger (per-project channeling, TRDD-X92VBFNF), so this prints
    # only for our own project. Hourly; a fire is one `stat` per known project.
    ("orphaned-resume-flag", 3600, "CLAUDE_PLUGIN_OPTION_ORPHANED_RESUME_INTERVAL"),
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
    # DEFAULT OFF — opt-IN via CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED=true (owner directive
    # 2026-08-07: the daemon owns rotation, so pushing account-window telemetry at an agent only
    # distracts it; /janitor-token-report and /janitor-token-attribution serve it on demand).
    # fail-open (silent on any rotator/
    # network failure); the detector self-cadences on the same interval too (TRDD-OY0W6LX5).
    ("window-burn-rate", 900, "CLAUDE_PLUGIN_OPTION_WINDOW_BURN_INTERVAL"),
    # token-usage-anomaly (TRDD-EDSFEQ5C): the SLOW per-5-min baseline complement of the
    # fast pre-tool-token-budget guard. It shipped with its own gate/dedupe but was never
    # added to this roster, so it NEVER RAN (found by the whole-codebase review,
    # TRDD-E9LMBNPE). Reads token-meter.jsonl locally — cheap; self-gates on
    # CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_ENABLED.
    ("token-usage-anomaly", 300, "CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_INTERVAL"),
    # model-fallback (TRDD-QE390SJA, janitor#222): the CONSUMER window-burn-rate never had.
    # A MODEL-scoped window can be spent while the account is fine — measured 2026-08-06,
    # 5h=42% / 7d=60% with Fable at ~98% — and the remedy is `/model opus`, not a rotation.
    # 60s cadence to match the planner's own interval; the planner ALSO enforces it, because
    # this roster's cadence is dynamic and a faster beat would fire a burst of switches.
    # SHIPS DARK (CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED defaults off).
    ("model-fallback", 60, "CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_INTERVAL"),
    # system-daemon-runaway (TRDD-HK7IZ21Z, EHT of TRDD-ZNN0UK5K): the fseventsd-class
    # safety NET — `memory-guard` only kills JANITOR-OWNED runaways, so a SYSTEM daemon
    # (fseventsd/mds*) or any OTHER process ballooning in RAM/CPU is otherwise invisible
    # until it crashes the host. Snapshot-then-parse `ps` (never pgrep/ps|grep — see the
    # detector's own docstring for the self-match trap), read-only, alert-only — it never
    # kills anything. 10-min cadence: catching a runaway within minutes at ~4GB (vs the
    # 39GB the parent incident reached) needs no tighter interval; the check itself is a
    # few `ps`/`statvfs` reads. Default ON — a host-crashing runaway is a safety concern,
    # not a hygiene nag; opt-out CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED=false.
    ("system-daemon-runaway", 600, "CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_INTERVAL"),
]

# #J THIN MODE (TRDD-PZLVT2RN): detectors that must NOT run inside an ai-maestro
# harness agent, because each one either mutates MACHINE-GLOBAL state (the shared
# plugin cache / marketplace via `claude plugin ...`, the global-state request files)
# or reads/surfaces the machine's OAuth/keychain posture — which the ai-maestro
# SERVER owns for harness agents (janitor#100 Family-A/B split; `#J` writes only
# `.janitor/state/`). Everything NOT listed here is workdir-scoped and keeps running
# inside. window-burn-rate is here because its data source is the OAuth rotator
# (OFF inside); it returns via the `aimaestro-continuity.sh status` 5-field contract
# once that CLI ships to ~/.local/bin (follow-up, janitor#100).
_NON_HARNESS_DETECTORS = frozenset({
    "peer-freeze-recovery",  # fleet-wide actuation — a harness agent's world is server-owned
    "marketplace-refresh",
    "user-plugins-update",
    "local-plugins-update",
    "project-plugins-update",
    "version-update",
    "plugin-updates",
    "oauth-beacon-refresh",
    "oauth-cookie-reminder",
    "oauth-login-needed",
    "keychain-health",
    "window-burn-rate",
    "fleet-github-config",
    # model-fallback: same reason as window-burn-rate (its data source is the OAuth rotator,
    # OFF inside a harness agent) AND it types into a pane — a harness agent's pane is the
    # SERVER's to drive (janitor#100 split). The server ships its own `model-opus` /
    # `model-sonnet` allowlist entries for exactly that half (janitor#222).
    "model-fallback",
})


def _detector_runs_in_harness(name: str) -> bool:
    """PURE: may `name` run inside a harness agent session? (The Phase-2 loop's gate.)"""
    return name not in _NON_HARNESS_DETECTORS


def _detector_is_due(name: str, interval: int) -> bool:
    last_file = state.state_dir() / f"last-run-{name}.ts"
    if not last_file.exists():
        return True
    last = state.read_int_state(last_file, 0)
    return (int(time.time()) - last) >= interval


def _mark_detector_ran(name: str) -> None:
    state.atomic_write(state.state_dir() / f"last-run-{name}.ts", str(int(time.time())))


# F6 (wikimem audit runtime): the cron prompt promises that a forged reserved
# marker inside untrusted content "already" arrives defanged — but that defang
# was a PER-DETECTOR convention (state.sanitize_for_drift_line), and ~half the
# roster never imports it. Detector stdout used to pass to the cron turn
# VERBATIM (capture_output=False), so ONE sanitizer-less detector printing
# untrusted multi-line text was a bare-line marker-forgery vector. This is the
# missing CENTRAL enforcement: _run_detector now captures stdout and defangs
# any RESERVED whole-line-executable marker that the emitting detector does
# not own. Only the reserved set is touched — ordinary `[janitor-<detector>]`
# drift prefixes (e.g. janitor-install-scope) pass through untouched.
# D5 (TRDD-82JRK0CY) added `ticket` + `quiet` to the reserved set. `ticket` was a
# latent forgery gap — ticket-dispatch already emitted a bare [janitor-ticket] channel
# but the token was in NEITHER this set NOR the owner map, so it was neither
# defang-covered nor owner-gated. `quiet` is the explicit idle-fire token main() emits
# (see _emit_quiet_if_idle); reserving it stops a detector/payload forging it. Ordering:
# `reload-skills` MUST precede `reload` (else `reload` matches the prefix and strands
# `-skills]`); the two new tokens prefix-collide with nothing, so they go last.
_RESERVED_MARKER_RE = re.compile(
    r"\[janitor-(?:memory-[a-z0-9-]+|resume|renew|reload-skills|reload|self-disarm|ticket|quiet)\]"
)
# The detectors that legitimately emit a reserved marker, and the exact shape each
# may emit BARE on its own line (everything else — even the owner's marker inside
# prose — is defanged). memory-maintenance's chore fan-out markers; ticket-dispatch's
# [janitor-ticket] agent-spawn channel (D5 — added alongside the reserved-set entry, so
# the bare channel keeps surviving instead of being defanged now that the token is
# reserved).
_MARKER_OWNERS: dict[str, re.Pattern[str]] = {
    "memory-maintenance": re.compile(r"\[janitor-memory-[a-z0-9-]+\]"),
    "ticket-dispatch": re.compile(r"\[janitor-ticket\]"),
}


# --------------------------------------------------------------------------- #
# QUIET HEARTBEAT (owner directive 2026-08-12: "it should simply print 'janitor
# heartbeat' followed by the occasional urgent warning ... no useless paths").
#
# The janitor already HAS a pull model for findings — the per-project ledger
# behind `/janitor-findings` (ARCHITECTURE.md §4: findings are pulled, never
# pushed). The advisory detectors bypassed it and wrote straight to stdout, so
# every fire that happened to land on several long cadences at once dumped a
# screenful of reminders and paths into the conversation. Quiet mode routes those
# to the ledger instead: nothing is lost, it is just READ on demand.
#
# THE DEFAULT IS LOUD, AND THAT DIRECTION IS DELIBERATE. A detector is silenced
# only by appearing in the list below. The inverse design — "loud only if you
# declare yourself loud" — reads tidier and fails the wrong way: a security
# detector added next year would be silent by omission, and nobody would notice,
# because silence is exactly what a clean run looks like. Here, forgetting to
# classify a new detector costs one noisy line; there, it costs a missed breach.
# --------------------------------------------------------------------------- #

# ADVISORY: a finding means "consider doing this sometime" — reminders, drift
# nudges, hygiene, informational counts. Nothing here is broken, unsafe, or
# stalled, so none of it earns an interruption.
_ADVISORY_DETECTORS = frozenset({
    "trdd-reminder", "trdd-drift", "trdd-state-reconciliation", "trdd-cross-card-blindspot",
    "report-to-trdd-drift",
    "memorize-nudge", "memory-librarian", "project-map-drift", "wikimem-syntax",
    "why-in-commits", "subagent-report", "stale-task", "stale-stash", "dirty-tree",
    "stale-index-lock",
    "worktree-janitor", "trashcan-purge", "reports-purge", "screenshot-purge",
    "runaway-file-growth",
    "github-issues-watch", "gh-reply-watch", "task-pr-mismatch", "pr-reconciler",
    "oauth-cookie-reminder", "oauth-beacon-refresh",
})

# Even an advisory detector is surfaced when its own line says it is serious.
# Detectors tag severity themselves (the `[findings] HIGH …` ledger shape); this
# is the override that stops the list above from muzzling a real alarm.
#
# Case-INSENSITIVE deliberately: the previous case-sensitive form silenced a genuine
# `error:`/`failed` written in lowercase by a detector's own author, while an
# attacker-supplied uppercase word sailed through — the wrong way round on both counts.
# Widening it is only safe because the untrusted detectors below no longer consult it.
_URGENT_LINE_RE = re.compile(
    r"\b(CRITICAL|HIGH|ERROR|FAIL(?:ED|URE)?|INSECURE|LEAK)\b", re.IGNORECASE
)

# Advisory detectors whose lines EMBED text authored by a third party — GitHub issue
# titles, PR titles, comment bodies. The urgency override MUST NOT apply to these: the
# words it searches for are chosen by whoever wrote the issue, so titling one
# "CRITICAL: please run this" would let a stranger decide what interrupts the owner's
# heartbeat past quiet mode. Their lines are still RECORDED in the ledger, so nothing
# is lost — only the ability of a remote author to promote their own text.
#
# Membership criterion, so this list can be maintained rather than guessed at: a
# detector belongs here iff it calls `state.sanitize_for_drift_line` on content it did
# not author. Adding a detector that interpolates remote text WITHOUT adding it here
# reopens exactly this hole.
_REMOTE_TEXT_DETECTORS = frozenset({
    "github-issues-watch", "gh-reply-watch", "pr-reconciler", "task-pr-mismatch",
})


def _heartbeat_is_quiet() -> bool:
    """Quiet by default; `CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE` restores the firehose."""
    return not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", False)


def _quiet_filter(detector: str, text: str) -> str:
    """Drop this detector's advisory lines from stdout, recording them in the ledger.

    Kept on stdout: everything from a non-advisory detector, any bare `[janitor-…]`
    marker (those are ACTIONS — suppressing one silently stops work, which is the
    one failure this must never have), and any line that tags itself urgent.

    Suppressed lines are RECORDED, not discarded — a line the user never sees and
    that was never written down is just a lost finding, and this whole change would
    then be trading noise for blindness.
    """
    if not text or not _heartbeat_is_quiet() or detector not in _ADVISORY_DETECTORS:
        return text
    # A detector that interpolates third-party text does not get the urgency override —
    # otherwise the remote author, not this detector, chooses what escapes quiet mode.
    may_claim_urgent = detector not in _REMOTE_TEXT_DETECTORS
    kept: list[str] = []
    dropped: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _RESERVED_MARKER_RE.fullmatch(stripped) or (
            may_claim_urgent and _URGENT_LINE_RE.search(stripped)
        ):
            kept.append(line)
        else:
            dropped.append(stripped)
    for msg in dropped:
        try:
            findings_ledger.record(
                sev="LOW", code=f"ADVISORY-{detector.upper()}", src=detector,
                msg=msg, ref="",
            )
        except Exception:  # noqa: BLE001 - a ledger failure must never break the heartbeat
            state.log_line("dispatch", f"quiet-filter could not record advisory from '{detector}'")
    return "\n".join(kept) + "\n" if kept else ""


def _defang_foreign_markers(detector: str, text: str) -> str:
    """Defang reserved `[janitor-…]` markers a detector is not entitled to emit.

    An owner's marker survives ONLY as a bare whole line (the exact contract the
    cron clause executes); the same marker embedded in prose — even the owner's —
    is untrusted-shaped and gets defanged to `⟦janitor-…⟧` so it can't match.
    """
    if not text or "[janitor-" not in text:
        return text
    own = _MARKER_OWNERS.get(detector)
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # bare whole line == no surrounding text at all (splitlines strips \n)
        if own is not None and own.fullmatch(stripped) and stripped == line:
            out.append(line)
            continue
        out.append(
            _RESERVED_MARKER_RE.sub(lambda m: "⟦" + m.group(0)[1:-1] + "⟧", line)
        )
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


# D5 (TRDD-82JRK0CY): one funnel for every machine-authored heartbeat DECISION.
# `_decision_fired` records whether an ACTION marker (survival OR stacking) was emitted
# this fire, so _emit_quiet_if_idle can print the explicit [janitor-quiet] token on the
# idle path. It is a MODULE global reset at the top of main() (a fire is one process, but
# tests call main()/phases repeatedly in-process, so the reset is load-bearing).
_decision_fired = False


def _emit_decision(marker: str, payload_lines: Iterable[str] = ()) -> None:
    """Emit ONE machine-authored heartbeat decision and mark the fire non-quiet.

    Prints the bare `[janitor-...]` token on its own line — byte-identical to the
    pre-D5 bare form the protocol rule and the baked SKILL.md step-3 fallback
    exact-match — then each payload line ROUTED THROUGH `_defang_foreign_markers`
    first, then sets the module-level `_decision_fired` sentinel.

    Two invariants this helper enforces:

    * CARDINAL (survival): it FLUSHES AT THE POINT OF DECISION. Every survival / action
      phase calls it at its existing print site, IMMEDIATELY, before its own `return`.
      It must NEVER be relocated to a single batched emit at end-of-main() — an
      early-returning survival fire (resume / self-disarm) would then strand an
      unflushed marker = a silent overnight stall. The bare bracket token stays the
      SOLE authorization carrier; there is no forgeable `ACTION:` keyword field.
    * DEFANG (forgery): the bare `marker` is trusted (machine-authored) and printed
      raw, but every PAYLOAD line is untrusted-shaped (an agent description from
      `_pending_agent_directive_lines`, a resume-directive) — so each is defanged with
      a NON-owner detector name, neutralizing any reserved marker forged into a
      main()-assembled envelope (closing the gap where defang only wrapped
      `_run_detector` output, never main()'s payload).
    """
    global _decision_fired
    print(marker)
    for line in payload_lines:
        # "dispatch" owns no reserved marker → every reserved token in the payload is
        # defanged to ⟦janitor-…⟧. Non-marker prose is returned unchanged (fidelity).
        print(_defang_foreign_markers("dispatch", line))
    _decision_fired = True


def _emit_quiet_if_idle() -> None:
    """Print the explicit `[janitor-quiet]` token iff no action decision fired this fire.

    Called immediately before the terminal NO-ACTION `return 0`. It makes the most-common
    (quiet) path an unmistakable token instead of ambiguous empty stdout — a quiet fire is
    now distinguishable from a stub that never ran or a swallowed line. `[janitor-quiet]`
    MAY coexist with detector drift lines: it means "no ACTION this fire", not "nothing to
    surface". The genuinely-silent skips (the informational-notice early returns) are left
    byte-silent on purpose and never reach here.
    """
    if not _decision_fired:
        print("[janitor-quiet]")


def _run_detector(name: str, interval: int) -> None:
    script = _HERE / "detectors" / f"{name}.py"
    if not script.is_file():
        state.log_line("dispatch", f"detector '{name}' missing at {script}")
        return
    if not os.access(script, os.X_OK):
        # FIX IT, do not report it (TRDD-WP7TCRME Rule 3). A detector that exists but lost its
        # executable bit is the quietest failure this system has: it is skipped on every fire
        # forever, and the old message called it "missing" — so anyone reading the log went
        # looking for a deleted file that was sitting right there. Whatever it was meant to
        # detect simply stops being detected, and nothing says so.
        #
        # Single defensible answer, so the janitor takes it: a file in `detectors/` that
        # dispatch is iterating IS meant to be run. There is no second reading of a detector
        # that should exist but must not execute — that would be a deletion, not a mode.
        #
        # This happens for real: `orphaned-memory-maint.py` landed at 100644 in 9e75a7d9 and
        # was dark until a TEST caught it (2026-08-12) — a test that only runs in CI, on a repo
        # checkout, and so says nothing about an INSTALLED plugin whose cache lost the bit.
        try:
            script.chmod(script.stat().st_mode | 0o111)
            state.log_line("dispatch", f"detector '{name}' was not executable — fixed (chmod +x)")
        except OSError as exc:
            state.log_line("dispatch", f"detector '{name}' not executable and chmod failed: {exc}")
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
        # stdout is CAPTURED (not inherited) so the F6 central defang above can
        # neutralize forged reserved markers before they reach the cron turn.
        # stderr stays inherited — it never carries drift lines.
        proc = subprocess.run(
            [str(script), "--one-shot"],
            stdout=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        state.log_line("dispatch", f"detector '{name}' timed out after {timeout}s — killed")
        # With a PIPE the partial output is on the exception — print it (defanged)
        # so a slow detector's already-produced findings aren't silently dropped
        # (they used to stream live under capture_output=False).
        partial_raw = exc.stdout
        partial: str | None
        if isinstance(partial_raw, bytes):
            partial = partial_raw.decode("utf-8", "replace")
        else:
            partial = partial_raw
        if partial:
            sys.stdout.write(_quiet_filter(name, _defang_foreign_markers(name, partial)))
            sys.stdout.flush()
        # Stamp last-run even on timeout so a chronically-slow detector backs
        # off to its cadence instead of re-firing (and re-hanging) every fire.
        _mark_detector_ran(name)
        return
    except OSError as exc:
        state.log_line("dispatch", f"detector '{name}' spawn failed: {exc}")
        return
    if proc.stdout:
        sys.stdout.write(_quiet_filter(name, _defang_foreign_markers(name, proc.stdout)))
        sys.stdout.flush()
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

    This is now the ONLY machine-wide stop. The softer global PAUSE that used to sit beside it
    (daemon alive but idle, heartbeats no-op) is gone with the rest of the off-switches — a stop
    that leaves everything running while doing nothing is indistinguishable from a healthy fleet
    from the outside, which is the exact shape of the incident. A disarm is loud and total: the
    cron is deleted, so a disarmed session cannot be mistaken for a working one."""
    if gs.kill_switch_present():
        state.log_line("dispatch", "global-disarm (kill-switch) set -> emit [janitor-self-disarm]")
        return True
    return False


def _resolve_heartbeat_mode() -> str:
    """Resolve what THIS fire does: 'full' | 'stop'.

    - 'stop' (a machine-wide /janitor-global-disarm): self-disarm — delete this cron so a
      fire costs zero (TRDD-RQ9FIFX6); the right choice for LONG idle, where one 1.0x
      context rewrite on return beats many 0.1x cache-read fires.
    - 'full': the normal heartbeat — cache refresh + DUE detectors + daemon.

    MAINTENANCE used to be a third mode and is GONE (owner directive 2026-07-31, the same
    ruling that removed pause and `keep-going-off`). It kept the cron firing and the daemon
    resident while doing none of the work, so from every outside vantage point — a process
    list, a cron list, a daemon heartbeat — a quiesced fleet was indistinguishable from a
    healthy one. That is the exact shape that let a project sit silently disabled for two
    weeks. Cost pressure is answered by the dynamic cadence tier (which slows fires without
    stopping work) and by a drift line naming the spend, never by a mode that switches the
    detectors off. DISARM survives as the only stop because it is the opposite of silent:
    the cron is deleted, so a disarmed session cannot be mistaken for a working one."""
    if _phase_globally_disarmed():
        return "stop"
    return "full"


def _sweep_retired_sentinels() -> None:
    """Delete the RETIRED per-project control sentinels if any are still on disk.

    Pause, maintenance mode, and the self-budget's maintenance flag are all gone (owner
    directive 2026-07-31). Nothing reads these files any more, so this is not a behaviour
    gate — it is the MIGRATION half, and it is load-bearing: real hosts carry these flags
    right now and the levers that used to lift them went away with the switches. Left
    behind, `maintenance-mode` makes the next person to inspect the state dir believe the
    project is still quiesced; `paused` was worse still, because it supported an INDEFINITE
    hold (`paused_until == 0` meant "until someone unpauses") — a project skipping every
    fire, forever, with only a log line nobody reads to say so. Best-effort; never raises."""
    sd = state.state_dir()
    for name in state.RETIRED_SENTINELS:
        try:
            (sd / name).unlink(missing_ok=True)
        except OSError:
            pass


def _sweep_old_files(root, suffixes: tuple[str, ...], cutoff: float) -> None:
    """Unlink files directly under `root` whose name ends with one of `suffixes`
    and whose mtime predates `cutoff`. Never recurses, never raises."""
    if not root.is_dir():
        return
    for f in root.iterdir():
        if not f.is_file() or not f.name.endswith(suffixes):
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except (FileNotFoundError, OSError):
            pass


def _phase_log_retention() -> None:
    """Bound .janitor/logs/ + .janitor/state/ growth. Fires at most once per LOCAL day.

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

    _sweep_old_files(state.log_dir(), (".log", ".log.1"), time.time() - (days * 86400))

    # F21 (wikimem audit): sweep dead per-session STATE files on the same daily
    # gate. .janitor/state/ accumulates per-session seen-files (e.g. the
    # memorize-nudge `memorize-nudge-session-<key>.txt` dedupe files),
    # fingerprint keys, and cadence stamps for sessions/detectors that no longer
    # exist — nothing ever pruned them (this phase cleaned only logs/). An
    # mtime-age sweep is safe BECAUSE every in-use file is rewritten on use
    # (fresh mtime): only files nothing touched for the whole window are dead.
    # Deliberately limited to *.txt / *.ts — control FLAGS (*.flag and the
    # retired sentinels) are NEVER swept here: deleting a flag changes
    # behavior, while deleting a stale stamp/seen-file only makes a detector due
    # again or re-emits an old finding once (fail-toward-run).
    state_days = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_STATE_RETENTION_DAYS"), 45)
    if state_days > 0:
        _sweep_old_files(state.state_dir(), (".txt", ".ts"), time.time() - (state_days * 86400))
        # F2 residue: the pre-fix MACHINE-WIDE round-robin cursor is dead state
        # now that the cursor is per-project — remove the orphan, best-effort.
        try:
            (gs.global_state_dir() / "memory-maint-rr-cursor.ts").unlink(missing_ok=True)
        except OSError:
            pass
    state.atomic_write(stamp, today)


def _pending_agent_directive_lines() -> list[str]:
    """W1 (TRDD-82OP4EN9): SendMessage-resume lines for in-flight background agents.

    Lazy import + blanket except: the resume phases are the load-bearing
    night-survival path — a manifest bug must degrade to "no agent lines",
    never kill the [janitor-resume] emission itself.
    """
    try:
        import pending_agents  # noqa: PLC0415 - lazy: fail-open when lib is absent

        return pending_agents.directive_lines()
    except Exception:  # noqa: BLE001
        return []


def _pending_agent_count() -> int:
    """W4 (TRDD-82OP4EN9): how many background agents the manifest lists. Fail-open 0.

    Counts ALL agents — used by the resume nudge (an agent that died must still be
    named for a SendMessage-resume, janitor-spawned or not — and a WEEK-old corpse is
    still worth naming, which is exactly why this count must not drive the cadence).
    The CADENCE probe uses `_fresh_external_agent_count` instead (TRDD-CI6ZTNB9)."""
    try:
        import pending_agents  # noqa: PLC0415 - lazy: fail-open when lib is absent

        return len(pending_agents.pending())
    except Exception:  # noqa: BLE001
        return 0


def _fresh_external_agent_count(now: int, state_dir: Path | None = None) -> int:
    """Background agents that are EXTERNAL and RECENT — the count the cadence FAST
    probe must use.

    EXTERNAL (TRDD-CI6ZTNB9 / issue #89): a janitor-spawned memory/security agent is
    housekeeping the janitor queued, not a time-sensitive wait. Counting it makes the
    controller react to a signal it produces — two wasted re-arm turns per memory
    chore. A USER-spawned background agent still counts.

    RECENT (2026-08-04): reported within `_RESUME_RECENCY_WINDOW_S`. Without the age
    bound a DEAD agent is indistinguishable from a working one for a full week,
    because nothing clears a manifest entry except the 7-day sweep — see
    `_cadence_active_waiting` for the measurement that forced this.

    Fail-open 0 — a controller that cannot read the manifest must fall back to the
    CHEAP tier, never pin the expensive one.

    `state_dir` pins WHOSE manifest is counted. None = the ambient session (the
    in-session cadence controller counting its own agents — the original consumer).
    A caller judging a DIFFERENT project (the external-clear watcher, the future
    daemon fleet walk) must pass that project's state dir: the ambient default here
    let THIS session's in-flight review-workflow agents flip an unrelated fixture
    project's clear verdict to active-waiting and block a release at the test gate
    (2026-08-08). The resume/directive branches of `_cadence_active_waiting` always
    took `sd` — this count was the one branch that ignored it."""
    try:
        import pending_agents  # noqa: PLC0415 - lazy: fail-open when lib is absent

        return sum(
            1
            for e in pending_agents.pending_external(now, state_dir=state_dir)
            if 0 <= now - int(e.get("ts", 0)) < _RESUME_RECENCY_WINDOW_S
        )
    except Exception:  # noqa: BLE001
        return 0


def _phase_rate_limit_recovery() -> bool:
    """Return True if a [janitor-resume] line was emitted (caller should exit)."""
    flag = state.state_dir() / "rate-limited.flag"
    if not flag.is_file():
        return False

    since_file = state.state_dir() / "rate-limited-since.ts"
    now = int(time.time())
    since = state.read_int_state(since_file, now)
    age = now - since

    # F7 (wikimem audit): the marker is emitted BARE on its own line — same
    # whole-line-only contract as renew/reload/memory markers — with the prose
    # as PAYLOAD (the keep-going two-line idiom). A prose-carrying marker line
    # would legitimize prefix-mimicry: any detector line starting with
    # "[janitor-resume] …" would be honored by the cron prompt. D5 (TRDD-82JRK0CY)
    # routes this through _emit_decision so the marker auto-flushes at the decision
    # AND every payload line is defanged.
    if age > 0:
        note = f"rate-limit cleared after {age}s — API is reachable again. Resume the previous pending task."
    else:
        # since-file was missing or in the future (clock skew); still cue resume.
        note = "rate-limit cleared (duration unknown) — API is reachable again. Resume the previous pending task."
    # W1 (TRDD-82OP4EN9): a rate-limit window kills BACKGROUND agents too, and
    # nothing else resumes them — list each one for a deterministic SendMessage
    # resume instead of hoping the model re-reads its transcript (2026-07-08:
    # four forks died at the 5h cap and needed a manual "resume"). These lines are
    # untrusted-shaped (an agent description), so _emit_decision defangs each.
    _emit_decision("[janitor-resume]", [note, *_pending_agent_directive_lines()])

    # Also clear any pending post-COMPACT resume flag: a rate-limit resume cue already
    # says "resume the pending task", which subsumes it — both describe the SAME
    # already-happened event, so no cue is lost. `resume-after-clear.*` is deliberately
    # NOT in this list: it is a PRE-marker for a /clear that has not run yet, and a rate
    # limit landing in that gap is exactly the case that used to strand the fresh session
    # with no cue at all. Only `_phase_clear_resume` may consume it.
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
    # The flags are gone, but the cadence phase (which runs only on a LATER fire, since
    # this one returns early) still needs to know a resume just happened — otherwise a
    # rate-limited session would keep retrying at its idle SLOW cadence. TRDD-0QQX9H0G.
    _stamp_resume(sd, now)
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

    # F7 (wikimem audit): bare marker line + prose payload — see
    # _phase_rate_limit_recovery for the WHY (whole-line-only marker contract). D5
    # (TRDD-82JRK0CY) funnels it through _emit_decision (auto-flush + payload defang).
    if directive:
        note = f"Context was compacted {age}s ago — auto-resume. {directive}"
    else:
        # Flag present but empty/unreadable: still cue a generic resume so the
        # session doesn't stall idle after a compaction.
        note = f"Context was compacted {age}s ago — auto-resume. Resume your previous in-flight task (check the TRDD board / your handoff)."
    # W1 (TRDD-82OP4EN9): a compaction wipes the working memory of in-flight
    # background agents from the fresh context — list them explicitly so the
    # resumed turn re-attaches to each via SendMessage.
    _emit_decision("[janitor-resume]", [note, *_pending_agent_directive_lines()])

    sd = state.state_dir()
    # This used to ALSO delete `resume-after-clear.*` as "subsumed". That was wrong and
    # is the bug this comment now guards: subsumption is only sound between two markers
    # describing the SAME already-happened event. The clear flag is a PRE-marker for a
    # /clear that has NOT run yet, so deleting it here silently disarmed the post-clear
    # resume and left the fresh session idle forever. The double-cue it was avoiding is
    # now prevented from the other side: `_phase_clear_resume` runs FIRST and clears the
    # stale post-compact / rate-limit markers, which the /clear genuinely does obsolete.
    for p in (
        flag,
        since_file,
    ):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    # Same reason as in _phase_rate_limit_recovery: this fire returns early, so the
    # cadence phase can only learn about the resume from this stamp. TRDD-0QQX9H0G.
    _stamp_resume(sd, now)
    state.log_line("dispatch", f"post-compact resume cue emitted (age {age}s)")
    return True


def _phase_clear_resume() -> bool:
    """Return True if a [janitor-resume] line was emitted for a post-CLEAR resume.

    The `/janitor-handoff-and-clear` primitive (TRDD-Z582IKIR P1) writes
    `resume-after-clear.flag` (the link-only handoff directive) + a `.ts` sidecar
    BEFORE firing `/clear`, then bootstraps the fresh session to re-arm the cron
    `/clear` destroyed. The re-armed cron's FIRST fire is this phase: it reads the
    flag, emits ONE `[janitor-resume]` cue carrying the directive (which points at
    `.janitor/state/agent-handoff.md`), and clears the flag so the resume fires
    exactly once.

    This is the `/clear` analogue of `_phase_compact_resume`. The two differ only in
    WHO wrote the flag — a PostCompact hook for compact, this script itself for clear
    (there is no PostClear hook, and `/clear` is unrecoverable, so the marker must be
    persisted before it runs). Everything downstream is identical: emit + clear +
    return True so main() skips the drift detectors this fire and the resume cue gets
    clean attention.

    ARMING (the load-bearing difference from the other two phases). The flag is a
    PRE-marker — it is written BEFORE the /clear it describes — so its mere PRESENCE
    proves nothing. Between the write and the clear there is a real window (widest when
    the injector is deferring to a user who keeps typing — every keystroke pushes the
    send another 8 s out, and it never gives up), and a heartbeat landing in it must
    leave the flag alone. `/clear` has no hook of its own, but it re-enters
    SessionStart with `source=clear`, which stamps `clear-observed.ts` — the ONE
    unambiguous observation that the clear happened. So this phase consumes the flag
    only when a clear was observed AT OR AFTER the flag was written.

    Rejected alternatives, both of which fire on the wrong event: `heartbeat-armed-at.ts`
    and `heartbeat-cron-id.txt` do change across a /clear (it destroys the cron), but a
    routine `[janitor-renew]` re-arm changes them too, so a renew in the pre-clear window
    would arm the flag early — the same bug via a different path. The session id does NOT
    change at all: /clear keeps the SAME process and session (see the SessionStart hook's
    own dedupe comment), so it cannot discriminate.

    Runs FIRST among the resume phases in main(): it can no longer fire prematurely, and
    a /clear genuinely obsoletes any pending post-compact / rate-limit marker (they
    describe the context that /clear destroyed), so it consumes those — keeping the
    exactly-one-cue property, in the direction that is actually sound.
    """
    sd = state.state_dir()
    flag = sd / "resume-after-clear.flag"
    if not flag.is_file():
        return False

    since_file = sd / "resume-after-clear.ts"
    # `>=`, not `>`: the tie means the clear landed in the same second the flag was
    # written, i.e. it DID happen. `>` would strand that flag forever, because nothing
    # re-stamps `clear-observed.ts` until the NEXT clear — an unarmable flag is the very
    # stall this phase exists to prevent, so the tie must break toward resuming.
    now = int(time.time())
    written_at = state.read_int_state(since_file, 0)
    observed_at = state.read_int_state(sd / "clear-observed.ts", 0)
    if observed_at <= 0 or observed_at < written_at:
        # NOT armed. Before leaving it, bound it: making the flag unconsumable by any other
        # phase (the fix above) also means a /clear the user never ran leaves it on disk
        # FOREVER, and the next real /clear would then resume against a directive from an
        # abandoned handoff. Nothing else sweeps it — the orphaned-resume detector only
        # knows `resume-after-compact.flag`. A deferral measured in hours is legitimate
        # (USER_PRESENT waits on a human); a day is an abandoned clear.
        #
        # Age from the sidecar, falling back to the flag's own mtime: a missing/garbage
        # sidecar reads as 0, and gating the sweep on `written_at > 0` would make exactly
        # that case the one thing nothing can ever clean up.
        max_age = state.coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_CLEAR_RESUME_MAX_AGE_S"), 86400
        )
        age = now - (written_at or state.file_mtime(flag))
        if max_age > 0 and age > max_age:
            for stale in (flag, since_file):
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass
            state.log_line("dispatch", f"swept an abandoned pre-/clear resume flag ({age}s old)")
        return False

    try:
        directive = flag.read_text(encoding="utf-8")
    except OSError:
        directive = ""
    # Defang against marker-mimicry (a handoff/directive embedding a fake
    # `[janitor-…]` marker), collapse to a single bounded line.
    directive = state.sanitize_for_drift_line(directive)
    directive = " ".join(directive.split())
    if len(directive) > 280:
        directive = directive[:277] + "..."

    age = max(0, now - (written_at or now))

    # F7 (wikimem audit): bare marker line + prose payload — see
    # _phase_rate_limit_recovery for the WHY (whole-line-only marker contract). D5
    # (TRDD-82JRK0CY) funnels it through _emit_decision (auto-flush + payload defang).
    if directive:
        note = f"Session was cleared {age}s ago — auto-resume. {directive}"
    else:
        # Flag present but empty/unreadable: still cue a generic resume so the fresh
        # session doesn't stall idle after a /clear.
        note = (
            f"Session was cleared {age}s ago — auto-resume. Read "
            ".janitor/state/agent-handoff.md (link-only handoff) and resume your prior task."
        )
    # A /clear wipes the working memory of in-flight background agents from the fresh
    # context — list them so the resumed turn re-attaches to each via SendMessage.
    _emit_decision("[janitor-resume]", [note, *_pending_agent_directive_lines()])

    # The /clear destroyed the context those OTHER markers described, so this cue truly
    # does subsume them — this is the sound direction of the subsumption that used to run
    # backwards. Clearing them here keeps "exactly one [janitor-resume] per event" without
    # any phase ever consuming a PRE-marker.
    for p in (
        flag,
        since_file,
        sd / "resume-after-compact.flag",
        sd / "resume-after-compact.ts",
        sd / "rate-limited.flag",
        sd / "rate-limited-since.ts",
        # janitor#224 defect 1. The list above already declares the pending post-compact
        # resume OBSOLETE — a /clear destroyed the context it describes. But it deleted only
        # the FLAG and left `resume-directive.txt`, the CONTENT that flag pointed at, on
        # disk. Its single consumer is `post-compact-resume.py`, which now never runs for
        # that event, so the directive outlived the resume it belonged to and was re-served
        # later as "the current target" (dispatch.py:2096) — state older than the handoff
        # that had just been saved. Deleting the pointer while keeping what it points at was
        # never a coherent half; either both survive a /clear or neither does, and the
        # settled answer for the flag is "neither".
        #
        # SUCCESS PATH ONLY, and that distinction is load-bearing. clear_trigger's failure
        # path deliberately deletes NOTHING (a directive another flow owns, and the cleared
        # session's only lifeline). Here the cue has already been composed and is about to be
        # emitted, so the directive is spent — the same one-shot property the flags have.
        sd / "resume-directive.txt",
    ):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    # janitor#224 defect 2. Evidence that SURVIVES the clear. The verify harness used to
    # infer "the flag was consumed" by diffing a before-snapshot against an after-snapshot,
    # but on the common CLEAR_CHAIN_SPAWNED path the flag is written by a detached child
    # immediately before the /clear keystroke — reliably AFTER the before-snapshot (measured:
    # snapshot 23:29:10, flag 23:29:12). So the check was structurally unreachable, and its
    # SKIP text asserted as fact that no flag had been set, on a run where one had been set
    # AND consumed. A verdict that cannot observe its subject must not narrate it; this stamp
    # is the observation, written by the only code that knows the consumption happened.
    state.atomic_write(sd / "resume-consumed.ts", str(now))
    # Same reason as in _phase_rate_limit_recovery: this fire returns early, so the
    # cadence phase can only learn about the resume from this stamp. TRDD-0QQX9H0G.
    _stamp_resume(sd, now)
    state.log_line("dispatch", f"post-clear resume cue emitted (age {age}s)")
    return True


def _phase_proactive_idle_compact() -> bool:
    """PREVENTIVE cold-compact (TRDD-D3PROACT). Returns True iff it fired a /compact (caller
    then returns early, like the reactive cold paths). NEVER raises — a fault degrades to no
    compact, never a broken heartbeat.

    WHY (user 2026-07-17, "make this fail-proof"): the reactive paths cannot beat the burn — a
    cron fire re-reads the whole transcript BEFORE dispatch runs, so a cold fire has already paid
    the 2× cache-creation write by the time _phase_rate_limit_recovery/_phase_compact_resume can
    queue a /compact. That write is only large when the CONTEXT is large. This phase removes the
    root cause: when the session is genuinely idle and the context is large, it shrinks NOW during
    a cheap WARM fire, so whatever cold event comes next (a >1h working turn — crons cannot fire
    mid-query, so the fire after it is always cold; a rate limit; a restart) reads ~50k, not ~600k.
    It is the only path that PREVENTS the burn rather than mitigating it after the fact.

    Gates (all injected into the pure `should_compact_proactively_idle`): enabled + off-cooldown,
    the user is ABSENT from this pane (never compact out from under active work — lossy), the
    session is NOT active-waiting (no resume/keep-going/directive/pending agents to interrupt),
    the context is large, AND a compaction could actually reclaim `min_gain` tokens above this
    session's learned post-compaction floor.

    That LAST gate is what makes this phase terminate, and it is not optional. The original design
    claimed to be "self-limiting: after the compact the context is small, so the size gate fails
    next fire." That claim is FALSE and was measured false in this repo on 2026-07-17: a real
    compaction went 343,007 -> 308,644, and 308,644 is ABOVE the 270,000 threshold — so the size
    gate NEVER closed and this phase would have re-fired every cooldown, forever, destroying
    context each time. The cooldown only defers a loop; it cannot end one. See
    cold_cache_compact.refresh_floor. The floor MEASUREMENT runs BEFORE this phase's action
    gates (cold_cache_compact.floor_needs_learning): the compaction stamps those gates itself
    (cooldown + resume recency + keep-going), so a measurement behind them never runs and the
    floor gate stays inert — the v0.49.0 bug, TRDD-28XF77X6.

    A long unattended session is the PRIME target — it is exactly the one that sits idle for
    hours and then eats a cold write. It runs AFTER the rate-limit/compact-resume early-returns (those own
    the reactive cold case and would already have returned) and BEFORE the keep-going nudge, so a
    fire that compacts does not also emit a now-pointless [janitor-resume] (the compact's own
    directive re-anchors the resume on the next fire)."""
    try:
        import cold_cache_compact  # noqa: PLC0415 -- lazy: fail-open when the lib is absent
        import user_intent  # noqa: PLC0415 -- lazy: only the idle path needs presence

        sd = state.state_dir()
        now = int(time.time())
        if not cold_cache_compact.proactive_idle_enabled():
            return False
        # LEARN THE FLOOR FIRST — observation BEFORE the action gates (TRDD-28XF77X6). The
        # compaction that makes the floor observable stamps every gate below itself
        # (mark_fired starts the cooldown, its auto-resume stamps last-resume.ts, keep-going
        # sessions never idle), so in v0.49.0 — where refresh_floor sat behind them — the
        # floor was never learned in exactly the unattended sessions this phase targets, and
        # the loop-killing gain gate never engaged. The transcript is read here only while a
        # compaction is actually unmeasured (once per compaction).
        ctx = None
        if cold_cache_compact.floor_needs_learning(sd):
            ctx = cold_cache_compact.context_tokens_for(
                cold_cache_compact.newest_transcript(state.project_root())
            )
            cold_cache_compact.refresh_floor(sd, ctx)
        # ACTION gates — they veto the lossy compact, never the measurement above. Cheap
        # gates (no transcript I/O) first: presence + active-waiting are stat-only.
        if cold_cache_compact.in_cooldown(sd, now=now):
            return False
        present = user_intent.user_is_present(now=now)
        active = _cadence_active_waiting(sd, now)
        if present or active:
            return False
        if ctx is None:
            ctx = cold_cache_compact.context_tokens_for(
                cold_cache_compact.newest_transcript(state.project_root())
            )
        floor = cold_cache_compact.read_floor(sd)[0]
        if not cold_cache_compact.should_compact_proactively_idle(
            ctx,
            user_present=present,
            active_waiting=active,
            min_context_tokens=cold_cache_compact.min_context_tokens(),
            floor_tokens=floor,
            min_gain=cold_cache_compact.min_gain_tokens(),
        ):
            return False

        compact_py = _HERE / "compact_trigger.py"
        if not compact_py.is_file():
            return False
        directive = (
            "proactive idle compaction: the session was idle with a large context, compacted "
            "PRE-EMPTIVELY so the next cold resume is cheap — after this, continue your prior "
            "pending task (read the newest in-flight TRDD's STATE block first)."
        )
        proc = state.run_subprocess(
            [sys.executable, str(compact_py), "--directive", directive],
            timeout=20,
            capture=True,
            detector_name="dispatch",
        )
        if not (proc and proc.returncode == 0 and "COMPACT_FIRED" in (proc.stdout or "")):
            # Headless / NO_ITERM / trigger failed — no compaction happens, so DON'T stamp the
            # cooldown (a stamp with no compact would suppress the SessionStart/rate-limit paths
            # too — the three trigger points must agree on "fired", per the hook's own note).
            return False
        cold_cache_compact.mark_fired(sd, now=now)
        # Informational NOTICE, NOT a [janitor-resume] marker: this turn must not begin resuming
        # into a context that is about to be compacted (the real resume arrives post-compaction).
        print(
            f"[janitor] session idle with a large context (~{ctx} tokens) — a /compact was queued "
            "and runs when this turn ends, PRE-EMPTIVELY shrinking it so the next cold resume "
            "(long turn / rate limit / restart) is cheap. The session auto-resumes after it."
        )
        state.log_line("dispatch", f"proactive idle compact fired (context={ctx})")
        return True
    except Exception as exc:  # noqa: BLE001 -- degrade to no compact; never break the heartbeat
        state.log_line("dispatch", f"proactive idle compact skipped: {exc}")
        return False


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

    F1 reload-churn guard (TRDD-Z582IKIR): `/reload-plugins` breaks the prompt-cache
    prefix, forcing a full cache-CREATE of the WHOLE context on the next turn instead
    of a cheap cache-read — on a large session a single reload is a ~500k+ weighted-
    token tax (the incident that motivated this TRDD burned 3 accounts in 2 days).
    Below the configured token threshold this phase is UNCHANGED. At/above it, DEFER:
    do NOT print the marker and do NOT advance the ack, so the deferred generation is
    re-checked (and, once the context shrinks — a compaction, `/clear`, a rate-limit
    resume — reloaded) on a LATER fire rather than forced now. Deferring the janitor's
    OWN auto-emitted `[janitor-reload]` here is the ONLY place the churn can be
    prevented: a built-in `/reload-plugins` fires NO hook of any kind (MEASURED — see
    the `claude-code-hook-types` memory, `^no-plugin-reload-hook`: an explicit
    `/reload-plugins` emitted zero hook events of any kind), so NO hook can intercept a
    human-typed reload. The earlier UserPromptSubmit "reload-guard" hook was therefore a
    no-op (it could never fire on `/reload-plugins`) and was removed on that finding
    (TRDD-Z582IKIR follow-up). This deferral intentionally never force-throughs: the
    context shrinks on its own and the reload lands cheaply then.
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

    threshold = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD"),
        tm.RELOAD_GUARD_DEFAULT_THRESHOLD,
        detector_name="dispatch",
        var_name="CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD",
    )
    ctx: int | None = None
    try:
        import cold_cache_compact  # noqa: PLC0415 -- lazy: fail-open when the lib is absent

        ctx = cold_cache_compact.context_tokens_for(
            cold_cache_compact.newest_transcript(state.project_root())
        )
    except Exception as exc:  # noqa: BLE001 -- an unreadable context must never block the reload
        state.log_line("dispatch", f"[reload-guard] context read failed, failing open: {exc}")
        ctx = None
    if tm.reload_guard_should_block(ctx, threshold):
        # NO LONGER A DEFERRAL (owner directive 2026-08-14). This used to `return` here and
        # wait for a cheaper moment, on the stated assumption that "the context shrinks on
        # its own and the reload lands cheaply then". That assumption is FALSE for exactly
        # the sessions this plugin exists to serve: an unattended session above the threshold
        # never shrinks by itself, so the reload deferred FOREVER and the session kept running
        # stale plugin code — silently, because the ack is deliberately left unadvanced and
        # nothing else reports it. A cost guard that never terminates is an availability bug.
        #
        # `reload_trigger.py` now defaults to `--shrink auto`: at/above this same threshold it
        # runs the verified `/clear` chain and reloads into the near-empty context, so the
        # expensive case the guard was protecting against no longer exists. We therefore EMIT
        # and let the trigger — which is the only thing that can see the pane, the handoff and
        # the urgency — make the call. The threshold read above is kept because it is what
        # decides whether to warn here; the trigger reads the SAME env var so the two agree.
        state.log_line(
            "dispatch",
            f"[reload-guard] context={ctx} >= threshold={threshold}: emitting [janitor-reload] "
            "anyway — reload_trigger --shrink will /clear first so the cache break lands on a "
            "near-floor context (was: deferred forever, which left sessions on stale code)",
        )

    state.atomic_write(acked_path, str(gen))
    _emit_decision("[janitor-reload]")  # D5: bare token, marks the fire non-quiet
    state.log_line(
        "dispatch",
        f"reload generation {gen} > project ack → [janitor-reload] emitted (per-project ack advanced; global generation left intact)",
    )


# Imported, not restated: `session_liveness` owns the `FIRED rearm → iterm` line (its
# recovery path writes it), so the window, the log names and the parser all live there and
# this alarm consults the one copy. They used to be duplicated verbatim here and in
# fleet_scan.py, "kept in sync by comment, not by import" — meaning a change to the line's
# wording or its `%Y-%m-%dT%H:%M:%S%z` stamp would be applied to one copy and leave the
# other silently returning None forever, with neither looking broken.
_ITERM_REARM_EVIDENCE_WINDOW_S = session_liveness.ITERM_REARM_EVIDENCE_WINDOW_S
_latest_iterm_rearm_epoch = session_liveness.latest_iterm_rearm_epoch

# TRDD-KU3ERYFX (janitor#234) — this alarm's remedy is a macOS System Settings toggle: an
# agent session structurally cannot perform it. The code names the (code, content) pair
# `findings_ledger.clear_surfaced_to_human` forgets once the condition itself resolves.
_ITERM_AUTOMATION_CODE = "ITERM-AUTOMATION-TCC"


def _phase_iterm_automation_alarm() -> None:
    """Surface the daemon's TCC-denial finding ONCE per session (TRDD-VQ4LX7ND part 2).

    The fleet guardian resolved an injection channel 0 times in 254 launchd-spawned beats
    while a session-spawned daemon resolved 56. The cause is a denied macOS Automation
    grant, and the symptom the TRDD indicts is not the denial itself — it is that the dead
    channel degraded into a MUTE skip loop for hours. The daemon cannot fix the grant (only
    the human can, in System Settings) and nobody reads the daemon log, so the ONLY useful
    thing it can do is say so where a human will see it: here.

    Emitted once per session (the flag persists until sessions enumerate again and the next
    fleet scan clears it, so without the ack this would repeat every fire). Fail-open.

    **Reports the OBSERVATION, not a conclusion (janitor#229).** This used to assert
    "macOS is denying it Automation access" — an inference stated as a measurement, from a
    signal that cannot support it. `iterm_automation_blocked` measures one thing: iTerm up,
    zero sessions enumerated. A denial produces that; so does a hung or timed-out osascript,
    and neither writes a distinguishable error. Measured live 2026-08-07 on this host, hours
    after two independent reports that the grant WAS working: zero denial signatures in
    either daemon log and an unchanged interpreter path — consistent with both stories. An
    alarm that picks one anyway sends the human to System Settings to re-grant a permission
    they may already have, and the toggle looking correct then "disproves" a real fault.
    """
    try:
        flag = gs.global_state_dir() / "iterm-automation-blocked.flag"
        acked = state.state_dir() / "iterm-automation-alarm-acked.ts"
        if not flag.is_file():
            # The condition ENDED (a healthy scan cleared the flag) — reset the seen-set
            # so a future re-occurrence, even with identical content, speaks again. This
            # keeps the refire property while the hash-ack below bounds mid-condition
            # writer ping-pong.
            acked.unlink(missing_ok=True)
            # The `surfaced-to-human` stamp must not outlive the condition it was
            # surfaced for (TRDD-KU3ERYFX LIVE INSTANCE #2) — clear it here too, in
            # lockstep with the local ack above, so a future recurrence reports
            # "never-reported" rather than a stale "reported-pending".
            findings_ledger.clear_surfaced_to_human(_ITERM_AUTOMATION_CODE)
            return
        try:
            raw_flag = flag.read_text(encoding="utf-8")
        except OSError:
            raw_flag = ""
        # Ack by CONTENT HASH, not mtime (review 2026-08-08): both the daemon and
        # session-side fleet scans write this flag, each stamping its OWN interpreter.
        # When they alternate, every rewrite bumps the mtime, and an mtime-keyed ack
        # re-alarmed on every flip — alarm fatigue on the exact alarm designed against
        # it. A seen-hash set alarms once per DISTINCT observation per condition
        # episode: each distinct payload really is new information, a repeat is not.
        payload_hash = hashlib.sha256(raw_flag.encode("utf-8")).hexdigest()
        try:
            seen = set(acked.read_text(encoding="utf-8").split())
        except OSError:
            seen = set()
        if payload_hash in seen:
            return  # already told this session about THIS exact observation
        state.atomic_write(acked, "\n".join(sorted(seen | {payload_hash})))
        # THE THIRD EVIDENCE SOURCE (peer finding 2026-08-08): before asserting "rescue is
        # unavailable", look for the positive evidence the alarm itself names. A recent
        # `FIRED rearm → iterm` proves the channel WORKED inside the window, refuting the
        # standing-outage reading — the honest finding is then a transient probe hang, and
        # the System-Settings remedy would be actively misleading (a working toggle that
        # "will not persist" makes a healthy system look broken). Honest tense: the grant
        # worked RECENTLY; a grant orphaned since would produce the same log.
        try:
            import fleet_scan  # noqa: PLC0415 -- local, as everywhere else in this file

            interpreter = fleet_scan.iterm_automation_interpreter(raw_flag)
            second_view = fleet_scan.iterm_automation_second_view(raw_flag)
            # TRDD-9PDH8G0W (janitor#92 peer self-correction 2026-08-08): a recent
            # `FIRED rearm → iterm` is a CONDITIONAL positive — it says nothing when a
            # scan needed no rescue, so its ABSENCE proves nothing either ("quiet fleet"
            # and "channel dead" are byte-identical). `rescue_warranted` is the stronger,
            # UNCONDITIONAL negative: THIS scan diagnosed cron_dead on an instance whose
            # only channel was iTerm (a rescue was WARRANTED) and osascript still came
            # back with zero sessions (the channel was EXERCISED). That has no innocent
            # explanation, so it outranks the downgrade below even when a rearm fired
            # hours ago — a hard failure now beats a success earlier.
            rescue_warranted = fleet_scan.iterm_automation_rescue_warranted(raw_flag)
            # TRDD-EZ3PMQYX: the call site's OWN classification of why the enumeration
            # came back empty — "error" / "timeout" / "empty" — consumed here so the
            # alarm can say WHICH failure this scan had instead of hedging between two
            # causes it cannot actually distinguish (the primary fix landed in
            # a0dfb901; this is the "nobody reads them yet" gap that card's STATE block
            # names as the remaining NEXT ACTION).
            probe_outcome = fleet_scan.iterm_automation_probe_outcome(raw_flag)
            # TRDD-EZ3PMQYX: read here, with the other flag fields, so it shares this
            # block's single import — a later read would be outside `fleet_scan`'s binding.
            exposure_pair = fleet_scan.iterm_automation_host_exposure(raw_flag)
        except ImportError:
            interpreter = ""
            second_view = ""
            rescue_warranted = None
            probe_outcome = ""
            exposure_pair = None
        rearm_epoch: int | None = None
        try:
            for log_name in ("daemon.log", "daemon.log.1"):
                log_path = gs.global_state_dir() / log_name
                if log_path.is_file():
                    found = _latest_iterm_rearm_epoch(log_path.read_text(encoding="utf-8"))
                    if found is not None and (rearm_epoch is None or found > rearm_epoch):
                        rearm_epoch = found
        except OSError:
            rearm_epoch = None
        now_epoch = int(time.time())
        if (
            not rescue_warranted
            and rearm_epoch is not None
            and 0 <= now_epoch - rearm_epoch <= _ITERM_REARM_EVIDENCE_WINDOW_S
        ):
            age_min = (now_epoch - rearm_epoch) // 60
            print(
                "[janitor] OBSERVED: the global daemon's osascript enumerated ZERO iTerm "
                "sessions this scan — BUT the guardian successfully resolved an iTerm "
                f"channel {age_min} minutes ago (`FIRED rearm → iterm` in the daemon log), "
                "which is the positive evidence a denial cannot produce. So this reads as "
                "a TRANSIENT osascript hang/timeout, not an unavailable rescue path. No "
                "remedy needed; honest tense: the channel worked RECENTLY — a grant "
                "orphaned since would look identical, so only a re-fire with NO recent "
                "rearm evidence should send anyone to System Settings. See janitor#92."
            )
            return
        # The grant-free second view (TRDD-DFKEXO79): `claude agents --json` needs no
        # Automation grant, so its answer can discriminate what osascript's zero cannot.
        # Sanitized like every other flag-derived string — this print is trusted stdout.
        if second_view == "channel-blocked-not-empty":
            discriminated = (
                " THIS TIME THE AMBIGUITY IS RESOLVED: an independent grant-free "
                "enumeration (`claude agents --json`) DID find live sessions on this "
                "host in the same scan — the channel is BLOCKED (denied grant or hung "
                "osascript), NOT an empty host."
            )
        elif second_view == "consistent-empty":
            discriminated = (
                " An independent grant-free enumeration ALSO found zero sessions — "
                "consistent with a genuinely session-less host, not a blocked channel."
            )
        elif second_view:
            discriminated = (
                " The independent second view could not run "
                f"({state.sanitize_for_drift_line(second_view)}) — the ambiguity stands."
            )
        else:
            discriminated = ""
        # SANITIZE before printing (review 2026-08-08): the flag is file-derived text
        # any local process can write, and this print IS the heartbeat's trusted
        # stdout — an embedded newline + bare `[janitor-...]` line would otherwise
        # become an actionable marker. Same defang every other drift line gets.
        # The grantee is ALWAYS a Python RUNTIME, never `uv`. uv is a launcher: it execs an
        # interpreter and is gone, so it is never the process holding the Apple Event and
        # granting it would protect nothing. The daemon's launchd plist already names an
        # absolute python3.12 as ProgramArguments[0] for exactly this reason.
        #
        # The old fallback said "the janitor daemon's uv/python entry", which invited a reader
        # with no interpreter path to go looking for a uv binary to authorise — a grant that
        # can never work. Say the runtime, and say why the path matters: a UV-MANAGED
        # interpreter is a poor grantee twice over — it is adhoc-signed (no stable Team ID, so
        # on macOS 26+ the toggle may not persist) and its path moves on upgrade, silently
        # orphaning a grant that was correctly given. That is what TRDD-DB1P25S4 proposes to
        # end by running the daemon under a signed python.org build.
        # TRDD-EZ3PMQYX (janitor#235, #240 ask 2): say HOW MUCH is at stake, because the
        # remedy this alarm recommends — run agents under tmux — is work, and a human
        # deciding whether to do it needs the size of the exposure, not just its existence.
        # The pair is written by `record_iterm_host_exposure` from the same scan.
        #
        # `None` (a pre-upgrade flag, or a nonsensical pair the reader rejects) yields an
        # EMPTY clause rather than "0 exposed": absence of a measurement must never render
        # as a reassuring zero, which is the one misreading that would make the alarm worse
        # than silent on exactly the hosts whose flag predates this field.
        exposure = ""
        if exposure_pair is not None:
            n_exposed, n_total = exposure_pair
            if n_exposed:
                # WORDING IS DELIBERATE: "no channel the guardian can use", NOT "iTerm-hosted".
                # While the iTerm path is down, `iterm_by_tty` is empty, so an instance that is
                # genuinely iTerm-hosted and one whose terminal simply could not be resolved are
                # INDISTINGUISHABLE — both present an empty channel set. The operational claim
                # (the guardian cannot reach them) is true of both; the identity claim (they are
                # on iTerm) is true of only one, and is not ours to make from this evidence.
                exposure = (
                    f" SCOPE: {n_exposed} of {n_total} scanned instance(s) have NO channel the "
                    "guardian can use — no tmux pane, no ai-maestro session — so they are "
                    "unreachable for as long as this lasts. Those are the ones to move under "
                    "tmux first."
                )
            else:
                exposure = (
                    f" SCOPE: all {n_total} scanned instance(s) still have a tmux or "
                    "ai-maestro channel, so nothing is currently unreachable even though the "
                    "iTerm path is down."
                )
        binary = (
            f"the PYTHON RUNTIME that made the call ({state.sanitize_for_drift_line(interpreter)})"
            if interpreter
            else "the python3 runtime executing the janitor daemon — NOT `uv`, which is only a "
            "launcher and never holds the Apple Event (read the absolute interpreter from "
            "ProgramArguments[0] of the daemon's launchd plist; no path could be read from "
            "the flag here — a pre-JSON flag, a concurrent rewrite, or a read error)"
        )
        # TRDD-KU3ERYFX (janitor#234): the remedy below is a System Settings toggle — an
        # agent reading this line structurally cannot perform it. The directive prefix
        # makes the agent's correct move explicit (tell the human, don't investigate);
        # the CONTENT after it is unchanged — nothing about a correctly-written alarm's
        # wording is wrong, only its delivery needed the marker.
        if rescue_warranted:
            # TRDD-9PDH8G0W: the UNCONDITIONAL-NEGATIVE reading. Unlike the two-cause
            # hedge below, this scan does not need to guess between denial and hang —
            # it has direct evidence a rescue was NEEDED (cron_dead, no other channel)
            # and the channel PRODUCED NOTHING when exercised, so "CANNOT tell you why"
            # would be dishonest here: the ambiguity that clause names does not apply to
            # THIS scan's own diagnosis, only to a bare "0 sessions" reading in isolation.
            # The remedy stays — a hard failure is still consistent with a denied grant.
            print(
                findings_ledger.HUMAN_ONLY_DIRECTIVE +
                "[janitor] OBSERVED: this scan diagnosed `cron_dead` on an instance whose "
                "ONLY possible channel was iTerm — a rescue was WARRANTED — AND osascript's "
                "enumeration came back with ZERO iTerm sessions, the same scan the rescue "
                "was needed. This is an UNCONDITIONAL NEGATIVE, not the usual two-cause "
                "ambiguity: the channel was EXERCISED (something needed it right now) and "
                "returned nothing, so there is no 'quiet fleet, nothing to rescue' reading "
                "available — a hard failure, right now."
                f"{discriminated} "
                "A hard failure THIS scan outranks a `FIRED rearm → iterm` from earlier "
                "today: past success does not explain why the rescue THIS scan needed was "
                "denied. Consequence: the guardian could not reach the instance that needed "
                "it (tmux panes are unaffected). If it is a denied Automation grant: System "
                "Settings → Privacy & Security → Automation → "
                f"allow {binary} to control iTerm. Note the grant follows that exact binary, "
                "so a uv/python upgrade that moves the path silently orphans a grant you "
                "really did give. On some hosts (macOS 26+, an adhoc-signed uv/python with "
                "no stable Team ID) the toggle will not persist and reverts to off — if it "
                "does, iTerm rescue is not attainable here; run agents under tmux, which the "
                "guardian rescues with no Automation grant at all."
                f"{exposure} This alarm clears itself "
                "on the next fleet scan once sessions enumerate again. See TRDD-VQ4LX7ND, "
                "TRDD-9PDH8G0W, GH issues #92, #229."
            )
        elif probe_outcome == "timeout":
            # TRDD-EZ3PMQYX "What (revised)" item 2: a call site's OWN "timeout"
            # classification is stronger than the base branch's two-cause hedge — the
            # call did not error and did not simply return empty, it ran past its
            # deadline. High system load is the measured mechanism that fits (this
            # card's 2026-08-13 load datum: loadavg 34.63 against a 15s bound). A
            # timeout is not a denial, so no Automation-grant remedy is indicated here
            # (the "only probe_outcome: error ⇒ the grant advice" rule from the card).
            print(
                findings_ledger.HUMAN_ONLY_DIRECTIVE +
                "[janitor] OBSERVED: the global daemon sees iTerm running, but osascript "
                "EXCEEDED its timeout enumerating sessions this scan (probe_outcome: "
                "timeout, recorded by the call site itself) — not the usual two-cause "
                "ambiguity a bare zero would be: the call did not error and did not return "
                "empty, it simply ran too long. High system load is the measured mechanism "
                "that fits (a sub-second osascript call can exceed a 15s deadline once "
                "loadavg climbs into the tens; TRDD-EZ3PMQYX). No Automation-grant remedy "
                "is indicated — a timeout is not a denial, and sending a human to System "
                "Settings for a load-correlated hang would be a false lead."
                f"{discriminated} "
                "Consequence: the guardian could not use the iTerm channel THIS scan "
                "(tmux panes are unaffected). This alarm clears itself on the next fleet "
                "scan once sessions enumerate again. See TRDD-VQ4LX7ND, TRDD-EZ3PMQYX, "
                "GH issues #92, #233, #236."
            )
        else:
            print(
                findings_ledger.HUMAN_ONLY_DIRECTIVE +
                "[janitor] OBSERVED: the global daemon sees iTerm running but enumerated ZERO "
                "iTerm sessions via osascript. A running iTerm always has at least one, so the "
                "Apple Event did not come back — but this measurement alone CANNOT tell you why. "
                "Two causes fit it equally: (a) macOS is denying Automation (Apple Events) "
                "access, or (b) the osascript hung/timed out/failed for another reason. Absence "
                "of a denial message in the logs is NOT evidence of a working grant — a denied "
                "event that returns empty logs nothing either. POSITIVE evidence is the guardian "
                "reaching an iTerm pane at all — EITHER a `FIRED rearm → iterm` line (it injected) "
                "OR an `INPUT FIELD BUSY on iterm` line (it read the pane and declined to inject; "
                "reading it required the Apple Event to answer). The busy/skip outcome is the "
                "COMMON one on a healthy fleet, so judging by rearms alone ages a WORKING channel "
                "into looking dead (janitor#261)."
                f"{discriminated} "
                "Consequence: the guardian cannot rescue an iTerm pane while the channel is down "
                "(tmux panes are unaffected). Check the evidence age below before concluding it "
                "has been down for long — an intermittent hang and a revoked grant look identical "
                "in a single scan, and recent evidence means the grant itself is fine. If it is "
                "(a): System Settings → Privacy & Security → Automation → "
                f"allow {binary} to control iTerm. Note the grant follows that exact binary, so "
                "a uv/python upgrade that moves the path silently orphans a grant you really "
                "did give. On some hosts (macOS 26+, an adhoc-signed uv/python with no stable "
                "Team ID) the toggle will not persist and reverts to off — if it does, iTerm "
                "rescue is not attainable here; run agents under tmux, which the guardian "
                "rescues with no Automation grant at all. This alarm clears itself on the next "
                "fleet scan once sessions enumerate again. See TRDD-VQ4LX7ND, GH issues #92, #229."
            )
        # Stamp the `surfaced-to-human` marker for /janitor-findings-style queries (the
        # local `acked` hash above already gates the print itself — this call is purely
        # so `findings_ledger.surfaced_to_human_status` can answer "reported-pending" for
        # this alarm instead of only ever "never-reported").
        findings_ledger.mark_surfaced_to_human(_ITERM_AUTOMATION_CODE, payload_hash[:16])
        # RECORD THE FIRE ITSELF, not just the dedupe marker (peer finding on janitor#92,
        # verified here: 69 detectors keep a last-run stamp in .janitor/state; this alarm kept
        # NONE, and grep found its wording in zero files on disk). `mark_surfaced_to_human`
        # answers "has this been shown?" — it does not say WHEN, HOW OFTEN, or with what
        # evidence, so every fire vanished the moment the receiving session moved on.
        #
        # That is why the correlation nobody could compute stayed uncomputable: five agents
        # spent an afternoon on whether a channel was down for hours or hung for seconds, with
        # ~10 fires that day and no record of any of them. A detector whose output is the only
        # trace of its own findings cannot be debugged after the fact — and this one's whole
        # job is to report an intermittent condition, where the TIMELINE is the evidence.
        #
        # `notify` is OMITTED, not passed False: it is a CALLABLE (the push channel), so
        # `notify=False` is a type error — pyright caught it, mypy did not (the scripts/lib
        # sibling-import blind spot, TRDD-BMDZK4RA). Omitting it is also the behaviour we
        # want: the print above is already the human-facing surface, so this write is purely
        # the durable record and must not duplicate into a push.
        findings_ledger.record(
            sev="HIGH", code=_ITERM_AUTOMATION_CODE, src="iterm-automation-alarm",
            msg=f"iTerm channel unreachable; evidence={rearm_epoch or 'none'}", ref="",
        )
    except Exception as exc:  # noqa: BLE001 -- advisory; a heartbeat must never die here
        state.log_line("dispatch", f"iterm-automation alarm skipped: {exc}")


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
    _emit_decision("[janitor-reload-skills]")  # D5: bare token, marks the fire non-quiet
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

        # OPEN A TICKET (TRDD-CGYMUKO6). The rollback below restores SERVICE; it does not fix the
        # DEFECT, and if the crash has no bad-version cause (or no fallback to fall back to) the
        # rollback does nothing at all and the daemon stays dead. This is the janitor's own machinery,
        # so it repairs itself: a HARNESS ticket opens and dispatches with no human in the loop. The
        # agent's job is the daemon log and the exception in it — not another restart.
        try:
            import issue_catalog  # noqa: PLC0415 — cost only on the crash-loop path, which is rare

            r = issue_catalog.raise_issue(
                "DAEMON-001",
                where="global daemon",
                evidence=[str(gs.global_state_dir() / "daemon.log")],
                count=gs.recent_spawn_count(),
            )
            if r.first_seen and r.line:
                print(r.line)
        except Exception as exc:  # noqa: BLE001 — a ticket fault must never block the rollback
            state.log_line("dispatch", f"could not raise DAEMON-001: {exc}")

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
        if state.in_ai_maestro_agent_env():
            # #J thin mode (TRDD-PZLVT2RN): the outside world's daemon is not a harness
            # agent's to SIGTERM — its restart is managed by the outside sessions.
            return
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

    DELIBERATELY NOT recorded to the findings ledger — do not "fix" this by adding
    a `findings_ledger.record(...)` call. The ledger exists for conditions that
    CANNOT be re-observed later: an intermittent channel failure, a rolling-window
    cost overrun, a transient the receiving session forgets. This condition is a
    FILE ON DISK (`autofix-off.flag`) that the user themselves created and that any
    later turn can read directly via `state.autofix_disabled()` — a durable record
    of a durable fact adds no evidence, only one ledger line per day forever until
    the user re-enables. The discriminator, stated once for the whole file: does the
    evidence survive on its own for later inspection? Yes ⇒ nudge, print only.
    No ⇒ finding, record it (see `_phase_self_cost_alarm` and the iTerm alarm).
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
        _emit_decision(line)  # D5: bare token via the funnel, marks the fire non-quiet


# A keep-going nudge is SKIPPED when a [janitor-resume] cue fired within this window —
# i.e. on the single fire right after a rate-limit / post-compact resume (TRDD-QW6RVAKN).
# Sized just over the FAST 300s tier (+ the scheduler's ≤10% jitter) so it swallows EXACTLY
# ONE fire at */5 and NOTHING at */15 or */30, where the next fire is 900/1800s away and a
# nudge is genuinely wanted again. It must stay small: this is a de-duplicator, not a mute
# button — the never-stop pulse is the whole point of the phase.
_KEEP_GOING_RESUME_DEDUPE_S = 360


def _keep_going_muted_by_recent_resume(sd: Path, now: int) -> bool:
    """True iff a [janitor-resume] cue already fired moments ago, making this nudge a
    DUPLICATE of it. PURE-ish (one stamp read), fail-open (any error → nudge).

    WHY (user report 2026-07-17, "janitor resume is called twice after compacting"): both
    resume phases and this nudge print the SAME `[janitor-resume]` marker. The resume phases
    early-return, so they never collide on one fire — but the NEXT fire found the flag gone
    and emitted the nudge, so a compaction produced two back-to-back resume cues telling the
    agent to do the one thing it was already doing. _phase_rate_limit_recovery already guards
    this exact class ("prevents a second, redundant [janitor-resume] on the next fire") for
    the rate-limit × compact overlap; this extends the same rule to the nudge.

    NOT a never-stop regression: the cue we defer to IS a stronger nudge (it carries the
    resume DIRECTIVE), it fired one heartbeat ago, and only that single fire is skipped.
    Reuses `last-resume.ts` — the stamp both resume phases already write — so there is no new
    state to leak, and a stale stamp simply falls outside the window and mutes nothing."""
    try:
        last_resume = state.read_int_state(sd / _LAST_RESUME_FILE, 0)
    except OSError:
        return False
    return last_resume > 0 and 0 <= now - last_resume < _KEEP_GOING_RESUME_DEDUPE_S


def _phase_idle_clear_nudge() -> bool:
    """A session left alone firing for a long time with a big context should CLEAR, not just
    compact. Emits ONE nudge telling the model to run `/janitor-handoff-and-clear`.

    WHY CLEAR AND NOT COMPACT (owner directive 2026-08-02, stated twice): compaction has a
    FLOOR it provably cannot go below. `cold_cache_compact.refresh_floor`'s docstring records
    the measurement — a real compaction took 343,007 -> 308,644, only 10%, because the base
    install AND THE SUMMARY ITSELF reload every time; that floor is "a property of the install,
    not a number we get to choose". So an abandoned session costs >= floor x 0.1 per fire
    forever, and compacting again reclaims nothing. `/clear` drops the summary and gets under
    the floor. Owner: *"the repeated nudges emit will not cost much since they are only cache
    reads on a tiny context."*

    It COMPOSES with `d2a5204` rather than replacing it: that bounded a stale resume-directive
    so an idle session demotes to the SLOW tier (fewer fires); this shrinks what each fire
    re-reads (smaller fires). A small context at FAST beats a fat one at SLOW.

    WHY IT INJECTS (owner directive 2026-08-04, correcting this phase's original design) — it
    used to only PRINT "run /janitor-handoff-and-clear". The heartbeat protocol treats a prose
    line as PAYLOAD to surface, not an instruction to obey, so the lever depended on an
    attentive reader — on precisely the sessions that by definition have none. It never fired.

    Injecting is not "clearing from outside", which was the original objection: we type the
    COMMAND into the session's own pane, so the MODEL runs it and authors the handoff first;
    `clear_trigger.py` then validates that handoff and only then clears. The keystroke
    machinery already solves delivery — `terminal_trigger` waits for an 8s quiet window,
    re-reads the input field, and retries until the command is genuinely sent. Still a
    SELF-trigger: never route this through `fleet_inject`.

    WHY IT CANNOT HIT A BUSY SESSION — a session parked on `ExitPlanMode`/`AskUserQuestion` or
    mid-long-tool cannot end its turn, so its cron never fires and this phase never runs. That
    is structural, not a gate anyone must remember to write.

    Returns True iff it emitted (the caller does NOT early-return; the roster still runs).
    """
    try:
        # Lazy, mirroring the sibling compact phase: only the idle path pays these imports,
        # and the heartbeat's hot path stays import-light.
        import cold_cache_compact  # noqa: PLC0415
        import external_clear  # noqa: PLC0415 - terminal_from_record (the shape adapter)
        import fleet_scan  # noqa: PLC0415
        import session_liveness  # noqa: PLC0415 - capture_terminal_identity (env -> fleet shape)
        import terminal_trigger  # noqa: PLC0415
        import user_intent  # noqa: PLC0415

        if not cold_cache_compact.clear_enabled():
            return False
        sd = state.state_dir()
        now = int(time.time())
        # Cheap stat-only vetoes first; the transcript read below is the expensive part.
        if cold_cache_compact.clear_in_cooldown(sd, now=now):
            return False
        present = user_intent.user_is_present(now=now)
        active = _cadence_active_waiting(sd, now)
        if present or active:
            return False
        root = state.project_root()
        idle_s, _, _ = fleet_scan.transcript_activity(str(root), now)
        ctx = cold_cache_compact.context_tokens_for(
            cold_cache_compact.newest_transcript(root)
        )
        if not cold_cache_compact.should_clear_when_long_idle(
            idle_s,
            user_present=present,
            active_waiting=active,
            min_idle_s=cold_cache_compact.clear_min_idle_seconds(),
        ):
            return False
        hours = (idle_s or 0) // 3600
        # FIRE IT, don't ask for it (owner directive 2026-08-04: *"it MUST handoff and clear
        # automatically"*). This used to print a prose line asking the model to run the
        # command — which the heartbeat protocol correctly treats as PAYLOAD to surface, not
        # an instruction to obey, so on a genuinely abandoned session (the only kind that
        # reaches here) there was nobody to read it. A lever that needs an attentive reader
        # is not automatic.
        #
        # Injecting is SAFE and is not "clearing from outside": we type the COMMAND, so the
        # model itself runs it and authors the handoff before anything is dropped —
        # `clear_trigger.py` validates that handoff and only then clears. The retry
        # machinery is already solved in `terminal_trigger` (it waits for an 8s quiet
        # window, re-reads the field, and keeps trying until the command is really SENT),
        # so this is a call, not a mechanism to invent.
        # THE RATIFIED INJECTOR, not the retired one-shot (TRDD-5C42VCUX). This phase used to
        # call `send_self_command(respect_user_presence=True)` — the exact API
        # `terminal_trigger.send_verified`'s own docstring says to NEVER use. On iTerm that call
        # does not merely degrade, it CANNOT WORK: it returns the `USE_ITERM_PATH` sentinel,
        # which means "caller, run your own osascript". Every sibling trigger script
        # (compact_trigger, clear_trigger, reload_trigger, resume_trigger, reload_skills_trigger)
        # has that branch; THIS caller never did, so `sent.startswith("FIRED:")` was False on
        # EVERY fire and the lever was structurally dead on the owner's own terminal.
        #
        # MEASURED 2026-08-06 on this host: `send_self_command(...)` -> `'USE_ITERM_PATH'`,
        # `.startswith('FIRED:')` -> False. The 2026-08-04 fix that introduced this test cured
        # the FALSE-POSITIVE half (it used to stamp a 2h cooldown and claim success while typing
        # nothing) but not the blindness — so the phase went from lying about success to
        # correctly reporting that it does nothing, forever.
        #
        # `send_verified` has no sentinel to forget: it builds steps for whatever channel it is
        # given, types, RE-READS the pane, and only then submits. Verified on this iTerm session:
        # channel_is_readable / build_type_only_steps / build_submit_steps / read_pane_text all
        # succeed. Presence is already a HARD veto above (`present or active -> return False`),
        # so dropping the retired presence-cancel reintroduces nothing.
        terminal = external_clear.terminal_from_record(
            session_liveness.capture_terminal_identity(os.environ)
        )
        ok, why = terminal_trigger.send_verified(
            terminal,
            "/janitor-handoff-and-clear",
            esc_first=False,
            # BOUNDED, and deliberately LARGER than the 9s the retired call passed — those are
            # different knobs: 9s was how long to wait for PRESENCE to clear, this is the whole
            # send budget, and the verified path adds type -> read-back -> submit round-trips on
            # top of the ratified 8s quiet window (a budget under ~10s could never succeed).
            # Still short, for the reason the old comment gave and which still holds: this
            # caller's real retry is the NEXT heartbeat, so a long inner block buys nothing and
            # stalls every other phase behind it.
            giveup_s=30.0,
        )
        # STAMP ONLY ON A SEND — and "a send" means the keystrokes ACTUALLY WENT OUT. The
        # cooldown exists so a CLEARED session does not re-clear; stamping after a REFUSED send
        # would instead mean "the user happened to be typing at 03:00, so skip the clear for two
        # hours" — the veto silently becoming a mute. Not stamping makes the next heartbeat
        # retry, which is the coarse outer retry. `send_verified` returns a BOOLEAN, so there is
        # no longer a set of string statuses a future change could add one to and have it default
        # to "assume it worked" — the failure that made this phase dead is now unrepresentable.
        if not ok:
            # Logged (not printed) so an abandoned session does not emit a line every 5 minutes
            # that nobody is there to read.
            state.log_line(
                "dispatch", f"idle-clear: not injected ({why}) — not stamping, will retry"
            )
            return False
        cold_cache_compact.mark_clear_fired(sd, now=now)
        print(
            f"[janitor-idle-clear] nothing but heartbeats for ~{hours}h "
            f"(~{(ctx or 0) // 1000}k context) — firing /janitor-handoff-and-clear so the "
            "next fires cost almost nothing. Compacting instead would NOT help: it cannot go "
            "below its own floor."
        )
        return True
    except Exception as exc:  # never let a cost optimisation break the heartbeat
        state.log_line("dispatch", f"idle-clear nudge failed: {exc}")
        return False


_DIRECTIVE_MAX_AGE_ENV = "CLAUDE_PLUGIN_OPTION_RESUME_DIRECTIVE_MAX_AGE_S"
# 3 h. A resume directive is written at compact/clear time for the NEXT resume to consume, so
# in its intended lifecycle it is minutes old. Three hours is far past that and still well
# clear of a slow night: at the `*/5` cadence it is ~36 fires, so a directive genuinely being
# worked is re-cited plenty before it ages out. Chosen against the reporter's measurement —
# they observed ~40 fires over six hours, so the bound must sit comfortably under six.
_DIRECTIVE_MAX_AGE_DEFAULT_S = 10800


def _directive_is_stale_by_age(age_s: int) -> bool:
    """True iff a resume directive this old must no longer be cited as "the current target".

    PURE, so the bound is testable without a clock or a file. 0 disables the age check (a
    caller who genuinely wants the pre-janitor#264 behaviour), and a malformed knob falls back
    to the default rather than to "never stale" — a bad env value must not silently restore the
    forever-citation this fixes.
    """
    cap = state.coerce_int(
        os.environ.get(_DIRECTIVE_MAX_AGE_ENV, ""),
        _DIRECTIVE_MAX_AGE_DEFAULT_S,
        detector_name="keep-going-nudge",
        var_name=_DIRECTIVE_MAX_AGE_ENV,
    )
    return cap > 0 and age_s > cap


def _directive_task_is_terminal(directive_text: str) -> bool:
    """True iff EVERY `TRDD-<id8>` the directive names has already reached a terminal
    column (published/complete/live/failed/superseded/cancelled/refused) — i.e. the task
    the directive points at has SHIPPED. (janitor#185)

    WHY: `_phase_keep_going_nudge` used to gate solely on `resume-directive.txt` existing
    and being non-empty, never on whether the work it names is DONE. A directive most
    commonly reads "continue TRDD-<id8> (...)" — `post-compact-resume.py::_inflight_trdd_
    directive`'s own fallback shape — so once that TRDD ships the file becomes stale
    content the nudge kept re-citing as "the current target" on every single heartbeat,
    forever (nothing but `post-compact-resume.py`'s one-shot compact consumer ever unlinks
    it, and a compaction may never land — see the cadence-bounding comment two phases up).
    Measured report (a MANAGER agent, #185): the nudge fired in its generic form for hours
    with no directive file present at all, which isolates the defect to exactly this
    file-derived branch — the fix is to degrade to that same safe generic form once the
    named task is verifiably done, not to add an off-switch or stop the nudge firing.

    FAIL-OPEN to False (⇒ caller keeps pointing at the file) on: a directive naming no TRDD
    at all (most agent-authored handoffs point at a link-only handoff file instead — nothing
    here can verify those, so the existing "always mention it" behavior is the correct,
    unchanged default); a referenced id this board has no file for (could be a different
    scope this session can't see, or a typo — never silently drop the only pointer to a
    possibly-real, still-open task); any import/read fault. Only a directive whose every
    named TRDD resolves to a terminal column is safe to drop from the nudge.
    """
    try:
        import trdd_common  # noqa: PLC0415 - lazy, mirrors the other lib imports in this file

        ids = trdd_common.extract_trdd_refs(directive_text)
        if not ids:
            return False
        columns: dict[str, str] = {}
        project_root = str(state.project_root())
        for folder in trdd_common.DESIGN_FOLDERS:
            for _, path in trdd_common.trdd_files(folder, project_root):
                uid = trdd_common.extract_uid(path.name)
                if uid and uid not in columns:
                    _, column = trdd_common.parse_trdd_state(path)
                    columns[uid] = column
        for uid in ids:
            column = columns.get(uid)
            if not column or not trdd_common.is_terminal_column(column):
                return False
        return True
    except Exception:  # noqa: BLE001 -- an optimization must never break the always-on nudge
        return False


def _phase_keep_going_nudge() -> None:
    """Emit a never-stop continue-nudge to keep an unattended session working. UNCONDITIONAL.

    WHY (TRDD-TKNSTP82 Part B, user 2026-07-02; DEFAULT-ON user 2026-07-16): a healthy
    heartbeat detects drift and re-arms dead crons, but on its own it never tells an
    idle agent to keep working — so an unattended fleet went silent overnight even
    though the janitor was firing the whole time. This phase EMITS a resume-shaped nudge
    but does NOT early-return — the detector roster downstream runs exactly as before.

    THERE IS NO OFF SWITCH, and that is the point (owner directive 2026-07-31: *"we need
    to remove the very option of disabling the janitor features"*). It used to have two —
    a `keep-going-off` sentinel written by `/janitor-keep-going off`, and a
    `KEEP_GOING_DEFAULT=false` knob. Both were sticky, both were silent, and nothing ever
    reported that the anti-idle guard had been switched off. Measured on two hosts
    2026-07-31: `.janitor/state/keep-going-off` dated 2026-07-17 — **14 days** during which
    every heartbeat fired, correctly did nothing, and looked identical to a healthy one.
    A guard that can be silenced invisibly is not a guard; the failure mode it exists to
    prevent (a session going quiet unattended) is exactly the state it was left in.

    Firing is bounded, not a runaway: each fire is one already-scheduled heartbeat turn and
    the nudge adds a single line to it. Re-firing on EVERY due heartbeat is the whole
    "never stop" point — a one-time nudge would miss a session idle across several fires.
    Exactly ONE exception survives, and it is a de-duplicator rather than a mute: the
    single fire immediately after a rate-limit / post-compact resume cue, which already
    said "continue" and carried the directive too. See _keep_going_muted_by_recent_resume.
    """
    sd = state.state_dir()
    # DEDUPE (TRDD-QW6RVAKN) — the ONE case that skips a nudge. It does not
    # weaken "always nudges": we are deferring to a [janitor-resume] cue that fired ONE
    # heartbeat ago and carried a resume DIRECTIVE — a strictly stronger nudge than this
    # generic one. Repeating it is duplication, not survival; the nudge resumes next fire.
    # It is time-bounded (~1 fire) and self-clearing, which is what separates it from the
    # sticky sentinels this phase no longer has.
    if _keep_going_muted_by_recent_resume(sd, int(time.time())):
        return
    # D5 (TRDD-82JRK0CY): the bare [janitor-resume] token + its single prose note are
    # emitted together at the end via _emit_decision (auto-flush + payload defang). This
    # phase does NOT early-return — see the docstring — but funneling it keeps the marker
    # shape uniform and marks the fire non-quiet so _emit_quiet_if_idle stays silent.
    # W4 (TRDD-82OP4EN9): point the nudge at the ACTUAL pending work when we can
    # name it — a generic "continue" lets an idle session answer "nothing to do"
    # and stall; a pointer to the directive file / the pending-agents manifest
    # re-anchors it every fire. Both probes are fail-open (a broken pointer must
    # never silence the nudge — the nudge IS the night-survival pulse).
    bits: list[str] = []
    try:
        directive_file = state.state_dir() / "resume-directive.txt"
        if directive_file.is_file() and directive_file.stat().st_size > 0:
            # janitor#185: a directive naming an already-SHIPPED TRDD is stale content,
            # not a current target — degrade to the generic form below instead of
            # re-citing it forever. See _directive_task_is_terminal's docstring.
            try:
                directive_text = directive_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                directive_text = ""
            age_s = max(0, int(time.time()) - int(directive_file.stat().st_mtime))
            if _directive_is_stale_by_age(age_s):
                # janitor#264: the AGE bound, which is the case #185's TRDD check cannot
                # reach. That check FAILS OPEN when the directive names no TRDD at all —
                # deliberately, because most agent-authored handoffs point at a handoff FILE
                # instead and nothing can verify those. The reporter's directive was exactly
                # that shape: it claimed the work was "COMPLETE and shipped (v13.3.0 +
                # v13.3.1)" in prose, named no TRDD, and so was re-cited as "the current
                # target" on ~40 consecutive fires across six hours — by which time the
                # project had shipped through v13.3.8 and the directive would have talked a
                # resuming agent OUT OF the fixes it was making.
                #
                # Age is the one staleness signal that needs no understanding of the content,
                # which is precisely why it covers the gap. A directive is written at
                # compact/clear time to be consumed by the next resume; one that has sat
                # untouched for hours is describing a session state that has moved on,
                # whatever it says. Degrade to the SAME safe generic form #185 uses — the
                # nudge itself must keep firing (it is the night-survival pulse), it just
                # stops attaching a frozen payload to it.
                pass
            elif not _directive_task_is_terminal(directive_text):
                bits.append("read .janitor/state/resume-directive.txt for the current target")
    except OSError:
        pass
    n = _pending_agent_count()
    if n:
        bits.append(
            f"{n} background agent(s) pending — resume each via SendMessage"
            " (ids in .janitor/state/pending-agents.json)"
        )
    if bits:
        note = "continue your pending task (keep-going mode) — " + "; ".join(bits)
    else:
        # There is no lever to offer any more and none is named on purpose: the
        # old text ended in "run /janitor-keep-going off", which handed every idle session a
        # one-command way to silence the night-survival pulse permanently — and issue #74
        # had already shown sessions reaching for it while merely BLOCKED ON A HUMAN
        # DECISION, i.e. exactly when the guard matters most. Saying so briefly is now the
        # whole of the correct response; the nudge costs one line and repeating it is the
        # design, not a bug to be suppressed.
        note = (
            "continue your pending task (keep-going mode) — if the work is genuinely finished, "
            "or you are blocked on a human decision, say so briefly and stop; there is no "
            "off-switch to run and none is needed"
        )
    _emit_decision("[janitor-resume]", [note])


def _phase_heartbeat_cost() -> None:
    """Record the PREVIOUS fire's exact token+dollar cost via a user-configured CLI
    (janitor#78, opt-in via ``CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND``).

    The command (e.g. the AgentLens ``agentlens-heartbeat-cost.js --oneline`` client)
    reports the last fully-SETTLED fire — an OTEL body carries no request_id, so a
    call's tokens become knowable only once the NEXT call is written; the in-flight
    fire can never see its own final response. At a 5-minute cadence, fire N records
    exactly what fire N-1 cost. That also means WHERE in this fire the phase runs is
    immaterial to correctness, so it sits with the cheap survival phases — the measured
    series is what decides whether a cadence is worth keeping.

    The line goes to the ``heartbeat-cost`` LOG, never to stdout. This is the
    load-bearing choice: the heartbeat's zero-output contract means every byte a fire
    prints forces the model to spend output tokens surfacing it on EVERY fire —
    a per-fire stdout cost line would tax the exact thing it exists to measure. The
    user is studying the SERIES, and a greppable log file is the series. (log_line's
    structural rotation bounds it — the S3/S4 append invariant.)

    The command string is config, not code: the CLI lives in a machine-local checkout
    (not yet published), so hard-coding a path here would break every other machine.
    Fail-open per the issue's own contract: a non-zero exit, timeout, missing binary,
    or unparseable command string means "no cost line this fire" — never block, never
    print. Skipped-fire gaps (the rate-limit / compact early-returns) self-heal:
    the next invocation reports whatever fire settled last, so the series has holes,
    never wrong values.
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND", "").strip()
    if not raw:
        return  # DEFAULT-OFF — the dependency is opt-in, machine-local tooling
    try:
        import shlex  # stdlib -- local import keeps module scope lean

        argv = shlex.split(raw)
    except ValueError as exc:  # unbalanced quotes in the configured string
        state.log_line("dispatch", f"heartbeat-cost command unparseable: {exc}")
        return
    if not argv:
        return
    # detector_name="dispatch" ON PURPOSE: run_subprocess logs its failure line to
    # <detector_name>.log, and pointing that at "heartbeat-cost" would salt the cost
    # SERIES with error lines every fire the CLI is down. Diagnostics belong in
    # dispatch.log; heartbeat-cost.log stays a pure, greppable series.
    proc = state.run_subprocess(argv, timeout=20.0, detector_name="dispatch")
    if proc is None or proc.returncode != 0:
        return  # fail-fast CLI contract: non-zero == "no cost line this fire"
    line = (proc.stdout or "").strip().splitlines()
    if line and line[0].strip():
        state.log_line("heartbeat-cost", line[0].strip())


def _phase_self_cost_alarm() -> None:
    """SURFACE the janitor's own heartbeat spend once it crosses the user's weekly budget.

    The janitor is a token-forensics tool that bounds OTHER sessions' cost but never named
    its own. A cron fire re-reads the whole cached transcript, so an idle session pinned at
    FAST can spend for a week with nothing reporting the total. This phase reports it, from
    the meter that already exists (`token-meter.jsonl`, heartbeat records only — counting
    the USER's own interactive turns would blame them for their work).

    IT ACTUATES NOTHING, and that is the whole change (owner ruling 2026-07-31: *"never
    self-disable"*). The previous version (TRDD-ZCODD6YS) escalated a two-rung throttle —
    cap the cadence, then auto-enter LOCAL maintenance — which let cost pressure switch the
    guard off by itself: every fire still happened, so the fleet looked healthy while doing
    nothing, the exact shape janitor-has-no-off-switch-but-disarm forbids. Detectors and the
    daemon keep running; a HUMAN reads this line and decides (slow the cadence, or
    /janitor-disarm here, which is loud because it deletes the cron).

    Per-project channeling (TRDD-X92VBFNF): the line carries THIS project's spend and
    nothing about any other. At most one line per local day per whole multiple of the
    budget, so a flat overrun states itself daily while a spend that keeps GROWING re-alarms
    the same day. Silent when `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET` is unset or 0 —
    that knob is a REPORTING threshold, never an enable-switch for janitor work. FAIL-OPEN:
    any exception → say nothing (a metering bug must never break a fire)."""
    try:
        budget = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET"), 0)
        if budget <= 0:
            return
        sd = state.state_dir()
        cost = tm.heartbeat_cost_7d(tm.load_log(sd / "token-meter.jsonl"), now=int(time.time()))
        if cost < budget:
            return
        today = datetime.now().astimezone().strftime("%Y%m%d")
        line = dedupe.emit_once(
            sd / "self-cost-seen.txt",
            f"self-cost@{today}:{cost // budget}",
            f"[heartbeat-cost] This project's janitor heartbeat has spent {cost} weighted tokens "
            f"over the last 7d, past the {budget} budget. Nothing was switched off. To spend less, "
            f"slow the cadence (CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON_SLOW) or run /janitor-disarm in "
            f"this project.",
        )
        if line is not None:
            print(line)
            state.log_line("dispatch", f"self-cost: 7d heartbeat cost {cost} >= budget {budget}")
            # RECORD each crossing, not just the dedupe marker — the same defect the iTerm
            # alarm had (299f775c). `cost` is a ROLLING 7d window: it is recomputed from a
            # log the meter trims, so an overrun that has aged out is unreconstructable
            # later. Without this, "the cadence was too expensive last Tuesday" is a claim
            # nobody can check — and the whole point of the line is that a human decides,
            # possibly days after the fire that saw it.
            #
            # `actor="human"` is load-bearing, not decoration: it prefixes the entry with
            # HUMAN_ONLY_DIRECTIVE so a later agent reading "heartbeat cost over budget"
            # surfaces it and STOPS. The two remedies in the message are slow-the-cadence
            # and /janitor-disarm — an agent that "helpfully" applied the second would be
            # cost pressure switching the guard off by itself, exactly what the owner
            # ruling in this docstring forbids. The ledger ENTRY is still always appended;
            # only record()'s RETURN is suppressed on a repeat, and we ignore the return
            # (the print above already happened, gated by this phase's own emit_once).
            #
            # LOW, so it can never escalate into a push: this is a budget report the user
            # opted into by setting the knob, not a defect. `notify` is omitted (it is a
            # CALLABLE — see 299f775c; the print is already the human surface).
            findings_ledger.record(
                sev="LOW", code="HEARTBEAT-COST", src="self-cost-alarm",
                msg=f"7d heartbeat cost {cost} weighted tokens >= budget {budget}",
                ref="", actor=findings_ledger.HUMAN_ONLY_ACTOR,
            )
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN normative: a metering bug must never break a fire
        state.log_line("dispatch", f"self-cost phase failed: {exc}")


def _phase_user_presence_breadcrumb() -> None:
    """Refresh the cross-plugin user-presence breadcrumb's liveness stamp.

    Writes ~/.aimaestro/state/user-presence.json's `written_at_epoch` on every
    fire (the heartbeat firing IS the liveness proof the MANAGER's
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


_LAST_RESUME_FILE = "last-resume.ts"
# A session that emitted a [janitor-resume] cue within this window counts as
# ACTIVELY WAITING (used by the idle-compact/idle-clear phases below). This is the
# ONLY way those phases can see a rate-limit or post-compact resume at all: both
# resume phases UNLINK their flag and early-return from main() before either phase
# runs, so reading the flags there is dead code.
# Without this stamp a rate-limited unattended session would be treated as idle and
# retried too slowly — and a post-resume session doing unattended work writes no
# user-presence breadcrumb, so it would read as idle while it works.
_RESUME_RECENCY_WINDOW_S = 1800  # 30 min


def _daemon_wake_coverage_window_s() -> int:
    """How fresh `daemon-wake-covered.ts` must be to authorize a rate-limit demotion (MF4).

    The daemon re-stamps it EVERY liveness beat while it is covering an injectable, rate-limited
    pane's resume, so freshness must track that beat period: 3× tolerates two missed daemon
    beats before a covered session falls back to FAST. Reads the SAME knob the daemon's beat
    period uses, so the reader (this cadence phase) and the writer (the daemon) can never
    disagree about how long a stamp stays 'fresh'."""
    interval = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_SESSION_LIVENESS_INTERVAL"), 120
    )
    return max(60, 3 * interval)


def _daemon_wake_covered_fresh(sd: Path, now: int) -> bool:
    """True iff the daemon recently PROVED it can wake THIS pane's rate-limit resume for free
    (MF4, TRDD-X07E7HTN, D1 v1). A fresh `daemon-wake-covered.ts` means the daemon injected
    `/janitor-resume` into this pane within the coverage window, so the paid FAST poll is
    redundant and the rate-limit window may demote. STALE/ABSENT ⇒ un-injectable / never-scanned
    / #J harness / feature-off ⇒ keep FAST (the cron stays the trigger — the safe default).

    Gated on the SAME DEFAULT-OFF opt-in the daemon writes the stamp under, so a leftover stamp
    can never demote a session while the feature is disabled: the default strictly preserves
    today's cron-owned FAST-poll behavior."""
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", False):
        return False
    covered = state.read_int_state(sd / state.DAEMON_WAKE_COVERED_FILE, 0)
    return covered > 0 and 0 <= now - covered < _daemon_wake_coverage_window_s()


def _cadence_active_waiting(sd: Path, now: int) -> bool:
    """True iff this session is waiting on something time-sensitive: a RECENT resume cue
    (rate-limit or post-compact), a pending directive resume, or in-flight background agents.
    Fail-open (any read error → the pending agents probe, itself fail-open).

    Formerly the FAST-tier signal for a since-removed dynamic-cadence controller
    (TRDD-0QQX9H0G, retired by TRDD-BRHJHWW0 — mid-session tier flips were re-arming the cron
    on every flip, several times an hour). What survives is the boolean itself: the idle-compact
    and idle-clear phases below still need "is this session waiting on something" to avoid
    shrinking/clearing a context a resume is about to need. The three signals below are all
    genuinely per-session.

    The resume signal is the `last-resume.ts` STAMP, not the `rate-limited.flag` /
    `resume-after-compact.flag` files: those are unlinked by their own phase, which
    then early-returns from main() before either idle phase runs, so testing them here
    would always read False. The stamp survives the flag, so the fire after a resume cue
    still reads as actively-waiting.

    MF4 handshake (TRDD-X07E7HTN, D1 v1): a fresh `daemon-wake-covered.ts` is the SOLE
    condition that lets a rate-limit resume stop counting as active-waiting — the daemon owns
    the wake for free, so there is nothing left to poll for. It suppresses ONLY the resume-stamp
    reason: the coverage stamp (not `active_waiting` itself) is what authorizes that, and the
    directive / pending-agents reasons below still hold True on their own. Absent the feature
    (or its stamp) this collapses to the exact pre-existing behavior.
    """
    try:
        last_resume = state.read_int_state(sd / _LAST_RESUME_FILE, 0)
        resume_recent = last_resume > 0 and 0 <= now - last_resume < _RESUME_RECENCY_WINDOW_S
        if resume_recent and not _daemon_wake_covered_fresh(sd, now):
            return True
        # AGE-BOUNDED, like the resume stamp above — and for the same reason, which this
        # signal did not originally have. `resume-directive.txt` is unlinked by exactly ONE
        # consumer, `post-compact-resume.py` ("one-shot per compact"). If that compaction
        # never lands — the soft `/compact` is only ENQUEUED, so a session that never ends
        # its turn, or is restarted first, never runs it — the pointer is never consumed and
        # this branch pins the session to the FAST `*/5` tier FOREVER.
        #
        # Measured 2026-08-02: an idle session held FAST for 2.9 h on a directive written
        # TWO DAYS earlier (Jul 31), which agentlensPro then reported as the fleet's #1
        # IDLE_FLEET_KEEPWARM culprit inside a ~$200 window. 6x the fires, indefinitely,
        # for a wait that ended two days ago.
        #
        # Bounding the CADENCE signal does NOT delete or ignore the file: the directive is
        # still read as CONTENT by the resume phases and the nudge (dispatch.py:1712). Only
        # its claim to mean "actively waiting RIGHT NOW" expires — which is precisely the
        # distinction the stamp already made and this branch conflated.
        directive = sd / "resume-directive.txt"
        if directive.is_file() and directive.stat().st_size > 0:
            age = now - int(directive.stat().st_mtime)
            if 0 <= age < _RESUME_RECENCY_WINDOW_S:
                return True
    except OSError:
        pass
    # EXTERNAL agents only (TRDD-CI6ZTNB9): a janitor-spawned memory/security agent
    # is housekeeping the janitor queued, not a time-sensitive wait — counting it
    # here would make this controller react to its own output and re-arm twice per
    # memory chore. The resume/directive signals above are legitimate and unchanged;
    # only this pending-agent term was self-perturbing.
    #
    # AGE-BOUNDED for exactly the reason the directive branch above is, which this
    # branch was missing. A manifest entry CANNOT be cleared by SubagentStop — the
    # documented payload carries no `agent_id` (pinned by
    # test_stop_hook_without_id_is_a_noop) — so the only cleanup is the 7-day
    # MAX_AGE_S sweep. An agent that died mid-run therefore keeps asserting "in
    # flight" for a WEEK, and this branch turned that stale assertion into a FAST
    # `*/5` pin for the same week.
    #
    # Measured 2026-08-04: 12 workflow-subagents spawned 2026-08-02 (none of whose
    # SubagentStop fired) held this session at FAST for 111 consecutive fires — ~12
    # no-op wake-ups per hour re-reading a 180k context — until the window-burn-rate
    # alarm surfaced this host as the fleet's top consumer at 2.6x linear pace on the
    # 7d window, projecting exhaustion 104h before reset.
    #
    # A genuinely in-flight agent still pins FAST: the bound is the SAME window the
    # resume and directive branches use, and no polling cadence helps an agent that
    # stopped reporting half a day ago. Like those branches this bounds only the
    # CADENCE claim — the entries are still listed by the nudge and still resumable.
    # `sd` MUST flow through here: this predicate is borrowed by the external-clear
    # watcher for OTHER projects, and an ambient manifest read leaks the calling
    # session's agents into their verdicts (see _fresh_external_agent_count).
    return _fresh_external_agent_count(now, sd) > 0


def _stamp_resume(sd: Path, now: int) -> None:
    """Record that a [janitor-resume] cue was emitted now — the idle phases' only
    view of a resume (see _cadence_active_waiting). Best-effort: a stamp failure must
    never break the resume cue itself, which is the survival-critical part."""
    try:
        state.atomic_write(sd / _LAST_RESUME_FILE, str(now))
    except OSError as exc:
        state.log_line("dispatch", f"last-resume stamp failed: {exc}")


def main() -> int:
    state.init_state()

    # Fire-time stamp (TRDD-LI7ENU2A prerequisite): record EVERY fire's wall-clock
    # time, BEFORE any early-returning phase, so the cadence's real recovery-latency
    # distribution (period + cron jitter) becomes measurable from FIRE times. Nothing
    # else records a fire: token-meter's `ts` is turn-END (its `ts mod 300` is uniform
    # — it measures turn duration, not jitter) and dispatch.log logs events, not
    # fires. Bounded by log_line's structural rotation (S4); best-effort because
    # telemetry must never kill a fire.
    try:
        state.log_line("heartbeat-fires", f"fire epoch={int(time.time())}")
    except Exception:  # noqa: BLE001 -- telemetry only; the fire must proceed
        pass

    # D5 (TRDD-82JRK0CY): reset the per-fire decision sentinel. A production fire is one
    # process so this is a no-op there, but tests call main()/phases repeatedly in-process,
    # and _emit_quiet_if_idle keys on it — so the reset is load-bearing for correctness.
    global _decision_fired
    _decision_fired = False

    # Phase 0: resolve this fire's MODE — full | stop. A fired turn re-reads the whole
    # session context (~618k cached tokens at the 0.1x cache-READ rate — NOT free, but 1/10
    # of the 1.0x REWRITE the next real turn pays if the cache DIES), so there are exactly
    # TWO intents:
    #   * stop        — a machine-wide /janitor-global-disarm (kill-switch, TRDD-NJ22HNC3) →
    #                   self-disarm: delete this cron so a fire costs zero (TRDD-RQ9FIFX6).
    #                   Best for LONG idle. dispatch can't call CronDelete (a session tool),
    #                   so it signals the session to run /janitor-disarm; self-limiting once
    #                   the cron is gone.
    #   * full        — the normal heartbeat (cache refresh + due detectors + daemon).
    # There is no third "keep firing but do nothing" mode any more — see
    # _resolve_heartbeat_mode for why a silent one was the bug, not the feature.
    mode = _resolve_heartbeat_mode()
    if mode == "stop":
        # Bare marker on its own line — the cron prompt maps an exact [janitor-self-disarm]
        # line to "silently run /janitor-disarm". Crons armed before that clause shipped
        # surface it verbatim (harmless) and need a one-time manual /janitor-disarm (the
        # prompt is baked at arm-time — re-arm rollout lag). D5: emitted via the funnel
        # (byte-identical bare token); no _emit_quiet_if_idle on this terminal action path.
        _emit_decision("[janitor-self-disarm]")
        return 0
    # Phase 0.05: sweep the RETIRED per-project sentinels (pause, maintenance mode, the
    # self-budget's maintenance flag). They used to gate this fire; now they are only litter
    # to remove, so the fire proceeds unconditionally.
    _sweep_retired_sentinels()

    # Phase 0.4: refresh the user-presence breadcrumb liveness stamp. Runs on
    # every fire, BEFORE the early-returning resume phases, so the
    # MANAGER's presence fallback sees a fresh written_at_epoch even on a fire
    # that exits early for a rate-limit/compact resume.
    _phase_user_presence_breadcrumb()

    # Phase 0.5: log retention.
    _phase_log_retention()

    # Phase 0.9: post-CLEAR resume (TRDD-Z582IKIR P1). Runs FIRST among the resume
    # phases because it is the only one gated on an event the others cannot observe:
    # `clear-observed.ts`, stamped by SessionStart(source=clear). Ordering it first is
    # what lets the two phases below stop deleting `resume-after-clear.*` as "subsumed"
    # — that deletion consumed a PRE-marker and silently stranded the fresh session. A
    # /clear genuinely obsoletes a pending compact / rate-limit marker, so this phase
    # clears those instead, and exactly one [janitor-resume] is still emitted.
    if _phase_clear_resume():
        return 0

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

    # Phase 1.2: PREVENTIVE cold-compact (TRDD-D3PROACT). The reactive paths above shrink a
    # large context only AFTER a cold fire already paid the 2× write; this one shrinks it
    # PROACTIVELY during a cheap warm idle fire, so the next cold event is cheap. Gated on a
    # genuinely-idle session (user absent, nothing pending) + a large context. Returns early
    # like the resume phases so the fire stays minimal before the queued /compact runs. It sits
    # AFTER the resume phases, which own the reactive cold case.
    if _phase_proactive_idle_compact():
        return 0

    # Phase 1.5: heartbeat auto-renew (silent on v0.5.2+ crons).
    _phase_heartbeat_renew()

    # Phase 1.5a: never-stop keep-going nudge (TRDD-TKNSTP82 Part B). Placed AFTER the
    # renew phase so the cron is already kept alive, and BEFORE the detector roster it
    # does not gate. It emits UNCONDITIONALLY — the opt-in flag and its off-switch are
    # gone (owner directive 2026-07-31); see the phase's own docstring for why, and for
    # the single time-bounded dedupe that remains. A prior rate-limit/compact resume
    # already returned earlier in this function, so this phase is naturally skipped
    # whenever one of those already fired this turn.
    # Phase 1.5a0: long-idle CLEAR nudge (owner directive 2026-08-02). Placed immediately
    # BEFORE the keep-going nudge so that on a fire where both would speak, the clear
    # instruction is read first — "shrink, then continue" is the right order, and the
    # keep-going nudge deliberately still fires so the session does not go silent. It does
    # NOT early-return: the detector roster runs exactly as before.
    _phase_idle_clear_nudge()

    _phase_keep_going_nudge()

    # Phase 1.5a2: previous-fire cost record (janitor#78, opt-in). Logs, never prints;
    # the phase's docstring carries the why.
    _phase_heartbeat_cost()

    # Phase 1.5a2b: name this project's own heartbeat spend when it passes the user's
    # weekly budget. Placed strictly AFTER all four resume/compact early-returns
    # (rate-limit / post-compact / post-clear / proactive-idle-compact) so a RECOVERY fire
    # never spends output on a cost line. It REPORTS ONLY — no cadence clamp, no mode
    # change, no [janitor-self-disarm]; the throttle it replaced is why (TRDD-ZCODD6YS,
    # reverted by the owner's "never self-disable" ruling — see the phase docstring). The
    # call site is a SECOND fail-open layer around the phase's own try/except: a metering
    # bug must never break a fire.
    try:
        _phase_self_cost_alarm()
    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders: survival is best-effort
        state.log_line("dispatch", f"self-cost call failed: {exc}")

    # Phase 1.5a3 (TRDD-0QQX9H0G's tier-driven cadence, TRDD-BRHJHWW0's [janitor-renew] on
    # every tier flip) is GONE — measured 2026-08-08: 5 re-arms in ~6.5h, each a full billed
    # turn, driven by the janitor's OWN memory-chore agents flipping the tier back and forth.
    # The ONLY remaining renew trigger is `_phase_heartbeat_renew`'s 7-day cron expiry, above.
    # Per-detector last-run stamps still throttle the actual work on a quiet fire; the cadence
    # itself is now a single fixed cron (`arm_prepare.DEFAULT_CRON`, user-overridable).

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

    # Phase 1.63: the iTerm Automation (TCC) alarm. The daemon stamped a flag because
    # it can see iTerm running but cannot enumerate its sessions — so it has been
    # skipping every frozen iTerm instance in silence. Say it ONCE, out loud, with the
    # exact remedy; the daemon's own log reaches nobody.
    _phase_iterm_automation_alarm()

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

    # Phase 2: drift detectors. Inside a harness agent (#J thin mode) the roster is
    # filtered to the workdir-scoped subset — see _NON_HARNESS_DETECTORS.
    in_harness = state.in_ai_maestro_agent_env()
    for name, default_interval, env_var in _DETECTORS:
        if in_harness and not _detector_runs_in_harness(name):
            continue
        interval = state.coerce_int(os.environ.get(env_var), default_interval)
        _run_detector(name, interval)

    # D5 (TRDD-82JRK0CY): the terminal full-mode no-action exit. Emit [janitor-quiet]
    # iff no action marker fired this fire (detector drift lines do NOT count as an
    # action — quiet means "no ACTION this fire", not "nothing to surface", so it may
    # coexist with drift). Placed AFTER the detector roster so a fire that only surfaced
    # drift still gets the explicit quiet token.
    _emit_quiet_if_idle()
    state.rotate_log_if_big("dispatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
