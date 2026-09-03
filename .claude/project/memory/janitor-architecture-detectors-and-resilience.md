---
name: janitor-architecture-detectors-and-resilience
description: "which detector finds X / where are the pattern libs / full detector roster by function / what skills does the janitor ship / what are the resilience pillars / how does the janitor survive a freeze or crash / what makes it immortal (the L0-L3 keepalive + watchdog layers) / why did the fleet sit idle overnight with keep-going off / why did the self-trigger refuse while the user was judged present in another pane / does a machine-global presence signal wrongly gate a per-session action"
ocd: 2026-06-13
lmd: 2026-09-03
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "skills/**"
publish-globally: false
split-lineage: 959060b8fb99469c8afe79d502cf3dac
---

# ai-maestro-janitor — detectors, pattern libraries, skills & resilience

## Detector roster (project-scoped — never touch user scope)

Each detector is a standalone `--one-shot` script driven by `dispatch.py`, with
its own cadence and seen-file dedupe. Slow ones use a PID-tracked detached
worker that skips if the prior worker is still alive. By function:

- **git / workflow hygiene** — pr-reconciler, worktree-janitor, dirty-tree,
  tracked-ignored, nested-git-safety, branch-protection, stale-stash,
  task-pr-mismatch, stale-task.
- **TRDD / task** — trdd-drift, trdd-reminder, report-to-trdd-drift,
  project-map-drift.
- **cleanup** — screenshot-purge, trashcan-purge.
- **scope drift** — settings-scope-drift, claude-md-scope-drift,
  cross-scope-reference-drift, subagent-scope-drift, mcp-config-drift.
- **supply-chain / security** — mcp-rugpull, remote-credentials,
  supply-chain-fingerprints, typosquat-watcher, provenance-audit,
  repo-trust-score, package-manager-policy, workflow-security,
  historical-cache-scan, binary-magic-scanner, ai-context-poisoning,
  subagent-report, janitor-self-integrity.
- **memory** — memory-librarian (SURFACES aggregation/conflict candidates,
  never mutates), memory-scope-leak (keeps the PUSHED memory scope free of
  machine/user-private data).
- **observability** — token-usage-anomaly (token-cost drift vs a learned baseline),
  window-burn-rate (early-rate-limit alarm); both ENRICH/CROSS-CHECK with the optional
  agentlensPro CLI — see [[agentlens-diagnostics-integration]].
- **updates (daemon-delegating shims)** — marketplace-refresh, plugin-updates,
  local-plugins-update, project-plugins-update,
  version-update (shim). (user-plugins-update retired 2026-08-20, TRDD-E39YT9G6.)
- **OAuth (opt-in)** — oauth-cookie-reminder, oauth-login-needed.

**Fail-soft contract (PRRD S6.1):** every detector that raises, or whose
optional dependency is missing, degrades to zero findings and logs once. A
single broken detector MUST NOT crash the heartbeat or block the others.

## The pattern libraries (`scripts/lib/*_patterns.py`, ~200+)

The security knowledge base lives as one module per attack class
(`<domain>_patterns.py` — e.g. `cloud_credential_patterns`,
`prompt_injection_patterns`, `npm_lifecycle_patterns`, `k8s_admission_patterns`).
Uniform shape: each exposes regex/rule definitions plus metadata consumed by the
scanner detectors. There are too many to enumerate — grep by domain when you
need one. The shared primitives the scanners build on are in
`security_helpers.py` (entropy, base64-sniff, Levenshtein/typosquat, invisible-
Unicode, authority-impersonation, advisory-armor) and `ioc_taxonomy.py`.

## Skills (`skills/`)

Contributor-facing, user-invocable entry points: `janitor-arm` /
`janitor-disarm` (install the stub + arm/tear-down the cron),
`janitor-supply-chain-watcher`, `janitor-dependabot-doctor`,
`janitor-credential-window-audit`, `janitor-github-workflow-doctor`,
`janitor-github-workflow-create`, `janitor-fork-pr-cache-audit`,
`janitor-compact-context` (agent-invocable self-compact + auto-resume),
and the memory trio `janitor-memory-write` / `janitor-memory-update` /
`janitor-memory-recall`. The OAuth and repomap toggles
(`/janitor-auto-manage-oauth-on|off`, `/janitor-auto-repomap-on|off`) and the
autofix toggles (`/janitor-autofix-on|off`) gate the opt-in subsystems.

## Resilience pillars (TRDD-7100178d)

The daemon is engineered to survive corruption and resource exhaustion:

- **Pillar 2 — file integrity** (`janitor_integrity.py`): critical writes use a
  redundant mirror (`backup_and_write`) and corruption-recovering reads
  (`read_or_restore`); the rotator's `state.json` and slot index are persisted
  through this path so a torn write self-heals instead of bricking the daemon.
- **Pillar 4 / Phase 5 — Tier-1 OOM memory guard** (`memory_guard.py`,
  user-signed): a daemon task samples system free memory and the process table,
  and when memory is critically low kills the single largest-RSS *Tier-1-
  killable* process (never a protected PID, never a too-young process) — SIGTERM
  → grace → SIGKILL. This is what keeps an unattended host from locking up under
  memory pressure.
- **Self-integrity** (`janitor_self_integrity.py` + the
  `janitor-self-integrity` detector): HMAC-signed drift lines, an append-only
  HMAC-chained audit log, and a manifest of the plugin's own files so tampering
  with the janitor surfaces as a finding.

## Immortality — layered self-resurrection (TRDD-324223a6)

The pillars above keep the daemon from corrupting itself; this layer keeps the
whole system *recovering from a frozen or dead session by any means*. The freeze
it fixes was structural — the recovery trigger used to live INSIDE the session it
had to rescue (a session-only heartbeat), so once that session wedged, nothing
outside could re-fire it. Four layers, each resurrecting the one below:

- **L0 — OS keepalive** (GROUP B, shipped v0.18.0): a launchd agent (macOS) /
  systemd unit (Linux) with `KeepAlive` + `RunAtLoad`, installed at a FIXED
  `${CLAUDE_PLUGIN_DATA}` entry, respawns the daemon on crash, logout, or boot —
  even with zero Claude sessions alive. All persistence tokens live in a shell
  installer (a resolving heredoc the CPV persistence-target discriminator can
  downgrade to inert); the Python orchestrator stays token-free, so REAL
  persistence ships past `--strict` without suppressing a finding (PRRD S5.1).
- **L1 — daemon watchdog** (GROUP A): the singleton daemon detects a frozen
  session (stale transcript + rate-limit flag) and drives a 7-rung recovery
  ladder — gentle first (ESC-nudge → `/janitor-arm` → `/reload-plugins` →
  update), then nuclear (relaunch → external-kill+relaunch → background-`claude`
  resurrect). Injection is terminal-env-aware (iTerm-UUID osascript / tmux
  send-keys / ai-maestro CLI), NEVER kills the user's interactive session (honors
  the OOM guard's protected PIDs), and is crash-loop-guarded (after N nuclear
  attempts it pauses and alerts a human — the one place recovery yields).
- **L2 — session hooks**: SessionStart re-arms the cron, publishes the session
  registry, and captures the terminal identity; PostCompact records a resume
  directive, and pushes the nudge that consumes it whenever THIS pane is
  unattended (see ^ATOM-DUXK-QD2D — recording alone did not stop a compaction
  from stranding a session; the push is the half that matters, and it must read
  per-pane presence). [^6]
- **L3 — in-session cron**: the ~5-min heartbeat self-trigger. Session-only is
  acceptable here precisely because L2 re-arms it every new session.

The self-integrity pillar above became FUNCTIONAL in this initiative's GROUP C
C1 (shipped v0.18.0): `publish.py` regenerates `.integrity/manifest-sha256.json`
on every release, giving the `janitor-self-integrity` detector a fresh
per-release baseline. The exec-path hardening (verify-before-exec gate,
pin-last-good, auto-rollback) is deliberately DEFERRED to reviewed design — a bug
in the heartbeat's own exec path bricks the very lifeline it guards.

## Historical detail (atoms, verbatim)

^ATOM-DUXK-QD2D [desc:"why unattended sessions were stranded after a compaction — the resume push read machine-global presence", keywords: dead_claude_sessions_I_have_to_wake_by_hand session_stranded_after_compaction resume-after-compact_flag_never_consumed post-compact_resume_did_not_fire per-pane_user_presence why_did_one_typing_pane_mark_every_pane_attended what_is_terminal_pane_key what_is_per_pane_presence_path five_projects_holding_stale_flags_for_days machine-global_presence_vs_per-pane_presence, type: project, ocd: 2026-07-28, lmd: 2026-07-28]

The post-compact resume PUSH is gated on PER-PANE user presence, never on a machine-global one. A
resume directive is recorded on every compaction, but the nudge that makes an UNATTENDED session
actually continue is suppressed while the user is judged present — and that presence breadcrumb used
to be a single machine-wide file. So one pane the user happened to be typing in marked EVERY pane on
the host "attended", and every other session sat on an unconsumed `resume-after-compact.flag` until a
human woke it by hand. Measured at the fix: five projects holding flags, two of them 4.3 days old.
`state.terminal_pane_key()` + `state.per_pane_presence_path()` are the per-pane breadcrumb;
`user_intent.user_is_present()` is its reader; the global file is the fallback only when the pane key
cannot be resolved. Fixed in eb52843 (v0.63.2). [^12]


^ATOM-TTA0-7I0C [desc: "the external-clear lane never evaluated an ARMED session because a heartbeat fire is a substantive turn and ACTIVE_FRESH_S equals the heartbeat cadence — since 3.4.6 the lane's idle is fleet_scan.huma", keywords: cold-cache-clear_never_evaluates no_evaluating_line_in_cold-cache-clear.log external_clear_never_fires every_session_active_at_every_beat armed_session_never_idle ACTIVE_FRESH_S_heartbeat_cadence transcript_activity_counts_heartbeat_turns human_activity_age scheduledFireId_cron_prompt_marker clear_lane_idle_floor_unreachable shadow_mode_found_nothing daemon_clear_lane_silent_for_weeks no_candidate_active=_self=_no-state-dir=_cooldown=, type: project, trdd: TRDD-O7UCNNN2, ocd: 2026-09-02, lmd: 2026-09-02]

Measured 2026-09-02 (TRDD-O7UCNNN2): with the lever on and the daemon restaged on 3.4.4, `cold-cache-clear` ran every 5 min and logged NO `evaluating` line — every fleet instance was `active=True` at every beat. Cause: `fleet_scan.ACTIVE_FRESH_S = 300` equals the `*/5` heartbeat cadence, and `transcript_activity`'s "substantive" age excludes ONLY `queue-operation` bookkeeping; a cron fire appends a user prompt + assistant + tool records, all substantive, so an armed session's age cycles 0→~285 s forever and the watcher's `DEFAULT_CLEAR_MIN_IDLE_SECONDS = 3600` is unreachable by construction. The lane could only ever clear sessions the janitor does NOT run in. Since 3.4.6: `fleet_scan.human_activity_age_from_tail`/`human_activity_age` walk the same tail but skip whole turns whose prompt record carries the top-level `scheduledFireId` key (a cron-fired prompt; tool-result echoes are `type: user` too but never prompts), `Instance.human_active`/`human_age_s` feed `cold_cache_clear_task` (which now logs `no candidate — active=… self=… no-state-dir=… cooldown=… of N` and stamps `declined:no-candidate` instead of a silent return) and the watcher gate's idle. `transcript_activity` is deliberately UNCHANGED — it is the fleet guardian's liveness signal, and hiding heartbeat turns there would re-open the 8DR0X08A re-inject loop. Live check the same night: three idle sessions read 764–1538 s human-idle vs 100–158 s substantive. When the lane looks dead again, read the `no candidate` summary line first — it names the skip reason per beat.


^ATOM-1FPQ-1HNK [desc: "since 3.4.7 the clear beat stamps clear-evaluated.ts per root and skips roots evaluated < 900 s ago (recent= in the summary) so the one-watcher-per-beat rule rotates through the fleet — a HOLD writes ", keywords: clear_beat_evaluates_the_same_root_every_time cold-cache-clear_same_root_repeated one_per_beat_starves_other_sessions clear-evaluated.ts IDLE_CLEAR_EVAL_SPACING_SECONDS recent=_skip_count HOLD_writes_no_cooldown sessions_above_300k_never_evaluated lane_rotation why_is_only_one_root_ever_evaluated, type: project, trdd: TRDD-0TM5NDYN, ocd: 2026-09-02, lmd: 2026-09-02]

Measured 2026-09-02 03:53-04:13 (TRDD-0TM5NDYN): the first live beats evaluated the first root in fleet order, the watcher HOLD-ed, and because only a CLEAR writes the cooldown stamp the next beats re-picked the same root while three sessions above the 300k floor were never reached — "one per beat" had become "one root per machine". Since 3.4.7: `cold_cache_compact.mark_evaluated` stamps `<root>/.janitor/state/clear-evaluated.ts` at spawn (before the verdict, so a failed spawn also spaces the retry) and `evaluated_recently` skips roots younger than `CLAUDE_PLUGIN_OPTION_IDLE_CLEAR_EVAL_SPACING_SECONDS` (default 900), counted as `recent=` in the `no candidate` summary; verified live after the restage — 04:33 this repo, 04:39 AgentlensPro, 04:44 CLAUDE-PLUGIN-VALIDATION. Evaluated and cleared are two facts, two stamps (the COQN6KVA lesson). Any per-beat limiter needs a rotation rule or it degenerates to a fixed pick.


^ATOM-H4UD-PL0G [desc: "AICTX-003 dedupe keys are content-addressed; the legacy {rel}:{line} migration runs BEFORE the raise loop, re-keys only a unique+near live finding once, skips unscanned rels, and the content-hash stam", keywords: duplicate_proposals_for_the_same_finding two_proposal_files_share_one_ticket-dedupe-key refused_finding_re-minted_after_an_unrelated_edit AICTX-003_re-mints_on_every_edit legacy_rel_line_dedupe_key_migration migrate_legacy_where proposal_re-keyed_onto_the_wrong_finding stamp_written_before_processing_muted_the_crash detector_silent_after_an_exception_until_content_changes capped_scan_reconcile_retracts_an_unscanned_file absence_unprovable_under_a_file_cap agent-context-integrity_dedupe_key janitor#291, type: project, trdd: TRDD-QNMBH3ES, ocd: 2026-09-03, lmd: 2026-09-03]

AICTX-003 (agent-context-integrity) dedupe keys are CONTENT-ADDRESSED — `sha1(matched_text)[:12]:{rel}:{rule_id}` (hash first so the 200-char `where` cap never truncates it; the line number moves to `evidence=`) — because a `{rel}:{line}` key re-minted a byte-identical proposal on every edit above the match and defeated the `refused` disposition (janitor#291). The one-shot migration of legacy line-keyed proposals (`issue_catalog.migrate_legacy_where`) obeys four laws, each from a measured failure: (1) it runs BEFORE the raise loop — after it, `raise_issue` had already minted a fresh proposal under the new key and the re-key produced two files with one dedupe key, forever; (2) it re-keys only when the rel has exactly ONE live finding within `_LEGACY_LINE_SLACK` (25) lines of the legacy line — uniqueness is not identity, and a fixed defect A must never be rewritten into new defect B; several legacy entries (`:40`, `:43`, `:47` for one finding) map to one key only once (a `taken` set), the rest are dropped; (3) under a capped scan (`scanned = candidates[:_max_files()]`) an unscanned rel is left untouched and `reconcile` is SKIPPED that fire — absence is unprovable without a scan; (4) the content-hash dedupe stamp is written LAST, after reconcile: stamped right after `_scan`, a later exception (e.g. the empty-span guard) left the stamp in place and the next fire early-returned on the unchanged signature, muting the crash until the content changed.


^ATOM-WAO6-Y9P9 [desc: "trdd-drift auto-restores a blocked card only when every unblock-when predicate holds AND every blocked-by TRDD is DONE (complete/completed/published/live); ids resolve across all four design folders; ", keywords: blocked_card_never_auto-unblocks unblock-when_satisfied_but_still_blocked blocked-by_is_unresolvable_holding archived_blocker_looks_unresolvable_forever cancelled_blocker_released_the_card DONE_COLUMNS_vs_TERMINAL_COLUMNS trdd-drift__try_unblock log_predicate_false_match_at_the_tail_boundary anchored_pattern_matched_a_cut_line unblock-when_log_predicate_must_be_repo-relative decision_predicate_never_auto-clears descriptive_blocked-by_token_migrates_to_unblock-when_decision colon_inside_a_flow-list_predicate, type: project, trdd: TRDD-RTRS704K, ocd: 2026-09-03, lmd: 2026-09-03]

`trdd-drift` auto-restores a `column: blocked` card to `pre-block-column:` (default `todo`) only when EVERY `unblock-when:` predicate holds AND every TRDD id in `blocked-by:` is DONE — `trdd_common.DONE_COLUMNS` = {complete, completed, published, live}, NOT `TERMINAL_COLUMNS` (a `cancelled`/`refused`/`failed`/`superseded` blocker stays a hold, mirroring dispatch.py's decision-needed class); the `trdd:<id> terminal` PREDICATE keeps the wider TERMINAL semantics its rule text documents. Blocker ids resolve across all four `DESIGN_FOLDERS` (proposals, tasks, archived, refused; first seen wins) — resolving from `tasks/` alone made every archived-because-shipped blocker read as "unresolvable — holding" forever. Issue refs and descriptive tokens in `blocked-by:` are invisible to the hold by design; `unblock-when: [decision:<who>]` is their machine-checkable form and never auto-clears. The `log:<repo-relative> matches <regex>` predicate reads only the last 256 KiB of the file and DROPS the cut first line of the window (a sentinel byte is not enough: `^.*needle` swallows it) — a malformed predicate or an absent file keeps the card blocked (fail toward staying blocked). Verified end-to-end on UA4FAX67: `unblock-when: [log:.janitor/logs/pane-policy.log matches rotation unwedge: ok]` parses intact through `unblock_when_predicates` (the `: ` inside a flow-list item survives) and evaluates True on the seeded line.

## Governed by

- [[janitor-architecture]] — the architecture overview hub this page details.

## Notes and lessons learned

[^5]: [id:ATOM-KEEPGO-IDLE, status:valid, keywords:"fleet_idle_overnight agents_did_not_continue heartbeat_did_not_nudge keep_going_off never_stop", ocd:2026-07-16, lmd:2026-07-16, trdd:93TKV769, commits:7cd8ea0]
  DO NOT leave the never-stop keep-going nudge OPT-IN (the pre-2026-07-16 default: silent in full
  mode unless the per-session `keep-going` flag was set), BECAUSE the whole fleet sat idle overnight —
  a healthy heartbeat detected drift and even re-armed `cron_dead` sessions (guardian `rearm` rungs in
  the recovery-audit), but `rearm` restarts the HEARTBEAT, it never tells the agent to keep WORKING,
  so every unattended session that finished a turn with no rate-limit/compact/drift signal went
  silent. DO keep `_phase_keep_going_nudge` DEFAULT-ON in every mode (`keep_going_default=true`),
  silenced only by the explicit `keep-going-off` sentinel (full mode) or the knob — keeping the fleet
  working in the user's absence is the janitor's #1 job, not an opt-in.


[^6]: [id:ATOM-PRESENCE-PERPANE, status:valid, keywords:"USER_PRESENT_wrong_while_absent self_trigger_refused_reload_compact presence_machine_global 30_minute_window per_pane", ocd:2026-07-16, lmd:2026-07-16, trdd:T7N67AQP, commits:"001bb3e,e5888b2"]
  DO NOT gate the self-trigger (`/compact`, `/reload-plugins`) on a MACHINE-GLOBAL presence breadcrumb
  with a 30-min window, BECAUSE a human typing in ANY session then marked EVERY unattended pane on the
  machine "present" for half an hour and the self-trigger refused everywhere (the user kept seeing
  `USER_PRESENT` while absent and had to reload by hand). The gate exists to avoid clobbering a human's
  IN-PROGRESS keystrokes — a harm that lasts seconds and is scoped to the pane they type in. DO make
  presence PER-PANE (`state.terminal_pane_key`: tmux/iTerm/kitty/WezTerm, namespaced by source; ABSENT
  per-pane file = away) with a 5-MIN window; no pane id (Apple Terminal/xterm) falls back to global.
  Inside ai-maestro the signal must come from the SERVER (`aimaestro-session.sh state`/user-idle, or
  `queue`/`--require-idle`), NOT the local breadcrumb — tracked on ai-maestro#73, wired under
  TRDD-PZLVT2RN `#J`.


[^12]: [id:ATOM-VYSD-YCS4, status:valid, desc:"the scope mismatch that stranded every unattended session on the host", keywords:"machine_global_signal_gating_a_per_session_action one_busy_pane_marked_every_pane_attended gate_scope_must_match_action_scope feature_never_fires_no_error_anywhere", ocd:2026-07-28, lmd:2026-07-28] DO NOT gate a PER-SESSION action on a MACHINE-GLOBAL signal, BECAUSE one active session then speaks for every session on the host and the other N-1 are silently starved — and the symptom reads as "the feature never fires", not as "a gate said no", so nobody looks at the gate. DO give every gate a signal at the SAME scope as the thing it gates.
