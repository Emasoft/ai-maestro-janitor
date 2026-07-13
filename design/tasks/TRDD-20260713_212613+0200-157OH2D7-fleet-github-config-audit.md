---
trdd-id: 157OH2D7
title: Fleet GitHub-config + security audit across all plugin repos with an on-demand fix skill
column: testing
created: 2026-07-13T21:26:13+0200
updated: 2026-07-13T22:05:00+0200
current-owner: janitor-session
task-type: security
severity: high
relevant-rules: [3]
implementation-commits: [8bd2949]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-13

**Problem (user, 3 parts):** (1) the janitor never detected a plugin repo missing its branch
ruleset (exposed to stranger PRs/pushes); (2) plugin repos still carry `required_linear_history`,
which BLOCKS Claude's merges; (3) the chores must ALWAYS scan security + GitHub-config incl. CI,
DETECT at minimal token cost, AND carry a FIX skill the notification proactively suggests (the
janitor only notifies the main Claude, so the notification must include the remedy).

**Root causes (verified):**
- `branch-protection.py` audits ONLY the current session's repo (`state.project_root()` →
  `gh repo view`) — no fleet sweep, so a *different* plugin's repo is never checked. It also
  self-skips the janitor repo (`is_self_scan_target`).
- It never suggests a fix — it says the OPPOSITE ("will not change repo settings"), and does NOT
  call `security_helpers.security_agent_hint()` even though `branch-protection` is a declared domain
  of that hint (TRDD-f12cae1a).
- Nothing detects `required_linear_history`. The ratified baseline deliberately EXCLUDES it
  (`branch_protection_lib.py:26-29`), but a repo hardened elsewhere keeps jamming merges, and the
  setup skill's DESCRIPTION still wrongly advertises "block force-push/deletion + linear history".

**Decisions (user):** scope = the 13 ai-maestro plugin repos (enumerable offline from the
marketplace catalog); remediation = detect + on-demand fix skill (mutation stays user-invoked, and
every finding carries the pointer to the fix skill).

**Design:**
- A: daemon `Task("github-config-audit", 21600)` runs the 13-repo READ-ONLY `gh` sweep ONCE
  machine-wide (issue #7 single-writer) → `<global-state>/github-config-findings.json`. Pure
  `classify_repo(facts)->[Finding]` in `scripts/lib/github_config_audit.py`.
- B: near-free per-session detector `fleet-github-config.py` reads only that JSON (one read +
  hash-dedupe), emits ONE compact line + the `/janitor-github-config-fix` pointer.
- C: `skills/janitor-github-config-fix/SKILL.md` + `scripts/github_config_fix.py` — plan-first,
  mutate-on-confirm; removes `required_linear_history` (preserving the rest) and applies the
  ratified baseline via the EXISTING `branch_protection_lib.apply_baseline_rulesets`.
- Also: wire the hint into `branch-protection.py`, flag linear-history there, drop its self-skip;
  fix the stale linear-history claim in the setup skill's description.

**STATUS: IMPLEMENTED + tests green (commit 8bd2949).** `column: testing`. Full suite 12834
passed; ruff clean; falsification verified for the classifier classes AND the branch-protection
linear-history emit. Remaining before `complete`: (1) ships on the next `publish.py` release;
(2) the actual `--apply` of the fix to the live fleet (10 repos carry linear-history, 1 is
UNPROTECTED) — a REMOTE-mutation Tier-2 action that awaits explicit USER go-ahead (do not run
`--apply` unprompted).

**NEXT ACTION:** await USER decision on running `/janitor-github-config-fix --all --apply`
against the live fleet, then the next release. Nothing else forceable.

**Load-bearing facts / gotchas:**
- Reuse, don't reinvent: `branch_protection_lib.apply_baseline_rulesets` /
  `detect_required_status_checks`, `security_helpers.security_agent_hint`,
  `state.ai_maestro_marketplace_members`, `lib/dedupe.emit_once`, `global_state` locking.
- Per-repo SILENT on non-admin / indeterminate probe (existing never-nag-on-unverifiable rule).
- The heartbeat detector must make ZERO `gh` calls (cost lives in the daemon).
- plugin.json userConfig knobs are REQUIRED or the env opt-outs are dead.

**REAL-RUN VALIDATION (2026-07-13, read-only, live `gh`):** `audit_fleet` over the 13 repos
reproduced BOTH reported facts — 10/13 carry `LINEAR_HISTORY` (incl. ai-maestro-janitor itself),
`ai-maestro-web-scenario-tester` is `UNPROTECTED`, `ai-maestro-webdesign` is `NO_TAG_PROTECT`, and
`ai-maestro-visual-communicator-plugin` is CLEAN (classifier discriminates, not blanket-flags).
The pure core + gather are proven against reality before the daemon/detector/skill were built.

**SUPERSEDED — do NOT carry forward:** nothing yet (new TRDD).
