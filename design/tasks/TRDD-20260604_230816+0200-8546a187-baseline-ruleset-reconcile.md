---
trdd-id: 8546a187-781b-4449-93f4-d84af4ed1bcf
title: Baseline-ruleset byte-identical reconcile with maintainer-agent + 2 shared follow-ups
column: blocked
created: 2026-06-04T23:08:16+0200
updated: 2026-06-06T00:05:00+0200
current-owner: janitor-dev-session
assignee: janitor-dev-session
priority: 3
severity: LOW
effort: S
labels: [branch-protection, coordination, github-rulesets]
task-type: infra
parent-trdd: null
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
impacts: [ci-pipeline]
runtime-targets: [macos, linux]
last-test-result: pass
last-test-at: 2026-06-04T22:55:00+0200
implementation-commits: [5922c1a, 8c63ad3, 874cdd7]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/14", "github.com/Emasoft/ai-maestro-maintainer-agent/issues/7"]
---

# TRDD-8546a187 — Baseline-ruleset reconcile with maintainer-agent

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-04

**What this is:** the janitor + maintainer-agent plugins standardised their GitHub
branch rulesets to ONE ratified pair. The janitor side is **DONE**; this TRDD tracks the
remaining **byte-identical reconcile** (gated on the maintainer) + **2 shared follow-ups**.
Coordinated entirely on **janitor#14** (and maintainer#7).

**Janitor side — DONE (live + committed):**
- Live janitor repo now has EXACTLY `baseline-history-protect` (bypass `[]`: deletion +
  non_fast_forward + required_linear_history) + `baseline-pr-and-checks` (admin
  `RepositoryRole 5` `always` bypass: pull_request 1-approval + required_status_checks).
  `main-hardening`/`main-ci-gate` deleted; zero stragglers. Admin bypass present →
  `publish.py` direct-push works.
- Code (UNPUSHED, ride next release):
  - `5922c1a` — shared orphan-delete UNION (6 names: janitor-baseline + main-hardening +
    main-ci-gate + default-branch-{ruleset,no-force-no-delete,required-checks}) +
    emergency-scrub doc note.
  - `8c63ad3` — PR-trigger filter on required-check auto-detection (`_workflow_triggers`,
    the YAML `on:`→`True` parse), byte-identical to maintainer `cde65eb`. Janitor repo
    7→4 checks (dropped push-only notify/release/audit).
  - `874cdd7` — **ruleset UPDATE is PUT not PATCH** (PATCH 404s on real GitHub; the
    janitor's `_post_or_patch_ruleset` had PATCH; stub answered any method so tests missed
    it). Maintainer verified its own apply already uses PUT+POST-fallback (clean) and added
    a guardrail comment `138dfdd`.
- 55 branch-protection tests pass; ruff clean.

**NEXT ACTION (BLOCKED on maintainer):** the maintainer is the long pole — gated on its
own **CPV-G3** hold. When it clears it posts its commit SHAs on #14, and BOTH sides
reconcile **byte-identical** on: `baseline-*` payloads + orphan-delete union + PR-trigger
filter + PUT update path. No janitor action until then.

**2 shared follow-ups — land byte-identical AFTER the SHA exchange (paired issues both repos):**
1. **Job-level `if: github.event_name == 'push'`** — a job INSIDE a PR-triggered workflow
   that itself no-ops on PRs still passes the workflow-level `on:` filter and would deadlock
   a required check. Needs job-level `if:` awareness (the `on:`-filter is the common case).
2. **gh-stub tightening to real-API semantics** — the test gh-stub "answers any method/any
   path", which hid BOTH latent bugs (PATCH-vs-PUT, push-only deadlock). Tighten:
   method→status (`PATCH /rulesets/{id}`→404, `PUT`→200, `POST`→201), unknown-path→404, and
   a check-runs fixture where a push-only job never reports on a `pull_request` event (makes
   the required-check deadlock reproducible IN-SUITE).

**3rd shared item — TAG PROTECTION (NEW, maintainer#7 2026-06-05, Tier-2 — needs MANAGER co-ratify):**
The maintainer proposed a THIRD baseline ruleset (it EXTENDS the ratified pair, so co-ratification
required). Gap: both ratified rulesets target `~DEFAULT_BRANCH`, so `v*` release tags are
unprotected — a moved/deleted published tag re-points installers at arbitrary code, and a post-hoc
CI gate can't catch a tag moved onto a CI-passing commit. Janitor ENDORSED on merits (#7 comment
4635916630) with one scoping note: prefer `["refs/tags/v*"]` over `["~ALL"]` (so it never breaks an
intentional moving `latest`/`nightly` tag). Proposed `baseline-tag-protect`: `target: tag`,
`enforcement: active`, `include: ["refs/tags/v*"]` (exact GitHub-accepted spelling locked together),
`bypass_actors: []`, rules `[deletion, non_fast_forward]`. **Zero publish.py impact** — new-tag
creation is neither deletion nor non_fast_forward, so publish.py still cuts releases with NO bypass
actor. STATUS: awaiting MANAGER co-ratification; once ratified, janitor adds it to
`branch_protection_lib.py` as a third payload (+ orphan-name awareness), byte-identical with the
maintainer, applied Tier-0 like the pair. Maintainer's other audit items are maintainer-internal
(no baseline change, no janitor co-sign).

**Load-bearing facts:**
- `triggers()` = `wf.get(True, wf.get('on'))` is loader-swap-safe (YAML 1.1 `on:`→`True` +
  YAML 1.2 literal `'on'`). Confirmed by manager — do NOT "simplify" it to one lookup.
- Applying the ratified baseline is EXEMPT (manager+maintainer+owner GO on #14).
- Live ruleset UPDATE must use PUT (PATCH 404s). The apply short-circuits once both
  baselines are present (Gate 6), so to UPDATE a live ruleset's checks, PUT it directly.

**Durable artifacts:** janitor#14 (full thread), maintainer#7, maintainer commits
`cde65eb` (filter) / `138dfdd` (PUT guardrail). Janitor ratified spec:
`skills/janitor-branch-protection-setup/references/ratified-baseline.md`.

## Why blocked
`blocked-by` is empty by UID (the blocker is the maintainer's external CPV-G3 hold, not a
janitor TRDD), but the column is `blocked` because the reconcile cannot proceed until the
maintainer posts its SHAs. Restore to `dev` when the SHAs land.
