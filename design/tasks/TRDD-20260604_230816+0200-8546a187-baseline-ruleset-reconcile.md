---
trdd-id: 8546a187-781b-4449-93f4-d84af4ed1bcf
title: Baseline-ruleset byte-identical reconcile with maintainer-agent + 2 shared follow-ups
column: blocked
created: 2026-06-04T23:08:16+0200
updated: 2026-06-11T11:06:34+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-11

### ⏵ SESSION ADDENDUM — 2026-06-11 (baseline-tag-protect now LIVE on the janitor repo)

The remaining-item #1 below ("Live first-apply readback-pin of baseline-tag-protect")
is **DONE**. Applied live to `Emasoft/ai-maestro-janitor` (ruleset id **17545495**,
POST of the exact `baseline_ruleset_payloads()[2]` payload). **Readback-pin confirmed
byte-identical** — GitHub echoed `ref_name.include == ["refs/tags/v*.*.*"]` UNCHANGED
(matching the maintainer's first-apply observation), `rules == ["deletion","update"]`,
`bypass_actors == []`, `target: tag`, `enforcement: active`. The janitor repo now has
**all three** ratified rulesets live (history-protect 17286452 + pr-and-checks 17286453
+ tag-protect 17545495); zero stragglers. This closes the MANAGER's coverage-table gap
("janitor itself is missing baseline-tag-protect").

Why now (the 2026-06-08 "rides the next publish, do NOT one-off-apply" guidance is
superseded): that deferral was written while gated on the maintainer SHA-exchange. Since
then the maintainer SHIPPED all 3 live (ids 17471104/05/06) and confirmed the `v*.*.*`
echo; the USER ratified tag-protect (Tier-3); the MANAGER flagged the janitor's missing
tag-protect as a gap to close. The live apply is independent of the CPV-blocked plugin
PUBLISH (the maintainer applied its 3 live the same way, not via a publish). The CODE that
emits tag-protect is already committed + tested and ships on the next CPV-unblocked publish.

Still genuinely publish-gated (be patient — CPV FP fix incoming): shipping the baseline
CODE in a published janitor version, and the 2 shared follow-ups (job-level `if:` filter,
gh-stub real-API-semantics) which must land byte-identical WITH the maintainer.

### ⏵ SESSION ADDENDUM — 2026-06-08 (verified current state; supersedes stale claims below)

The body below describes a **TWO-payload** baseline and "blocked on maintainer". BOTH are now
partly stale — verified against live code + janitor#14 this session:

- **THIRD ruleset `baseline-tag-protect` is IMPLEMENTED + TESTED in the janitor** (NOT just the
  2-payload pair the body describes). `branch_protection_lib.py`: `TAG_PROTECT_RULESET_NAME`
  (`target: tag`, `rules: [deletion, update]`, `bypass_actors: []`) in
  `baseline_ruleset_payloads()`; `baselines_present()` requires all THREE; `apply_baseline_rulesets()`
  applies all three then deletes the legacy orphan union. **60 branch-protection tests pass, ruff clean.**
- **USER RATIFIED `baseline-tag-protect` (Tier-3, owner approval)** on janitor#14
  (2026-06-05T23:50Z, MANAGER post). MANAGER's part done; janitor + maintainer own the apply.
- So the janitor CODE side is **DONE for all THREE baselines** (history-protect + pr-and-checks +
  tag-protect, orphan-delete union, PUT-not-PATCH update path, PR-trigger required-check filter).

**Remaining (genuinely gated — NOT unilaterally actionable):**
1. **Live first-apply readback-pin** of `baseline-tag-protect`'s `ref_name.include` (the exact
   literal GitHub echoes — facts-not-assumptions). This is a LIVE GitHub mutation that RIDES the
   next CPV-G3-cleared publish; do NOT one-off-apply it out-of-band.
2. **Byte-identical reconcile with the maintainer** on all payloads + the 2 follow-ups — still
   gated on the maintainer posting its commit SHAs on #14 (its CPV-G3 hold). No janitor action
   until then.
3. The **2 shared follow-ups** (job-level `if: github.event_name=='push'` awareness; gh-stub
   tighten to real-API method→status semantics) — must land byte-identical WITH the maintainer.

Net: #157 is NOT idle-stale — janitor code is done; it waits on the maintainer SHA exchange +
the next publish. Nothing for the janitor to implement solo right now.

---

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

**3rd shared item — TAG PROTECTION (CONSENSUS CLOSED 2026-06-05, Tier-3 — awaiting USER ratify):**
A THIRD baseline ruleset (it EXTENDS the ratified pair). Gap: the pair targets only
`~DEFAULT_BRANCH`, so `v*` release tags are unprotected — a moved/deleted published tag re-points
installers at arbitrary code, and a post-hoc CI gate can't catch a tag moved onto a CI-passing
commit. **All three plugins (janitor + maintainer + MANAGER) converged byte-identical.** FINAL spec:

```
name: baseline-tag-protect
target: tag
enforcement: active
conditions.ref_name.include: ["refs/tags/v*.*.*"]
conditions.ref_name.exclude: []
bypass_actors: []
rules: [deletion, update]
```

KEY DECISIONS (mechanism-verified, not assumed):
- **rule = `[deletion, update]`** (NOT `non_fast_forward`). `non_fast_forward` does NOT block a tag
  fast-forward-moved onto a DESCENDANT commit (append a malicious child commit, ff-move `vX.Y.Z`
  onto it → bypass). `update` ("Restrict updates") blocks EVERY repoint → minimal-complete, and
  correct regardless of how GitHub evaluates tag fast-forwards. (MANAGER self-corrected its earlier
  "a move is always a force-update" — it was wrong.)
- **scope = `["refs/tags/v*.*.*"]`** — protects immutable full-semver release tags; leaves a future
  movable `vN`/`latest` alias free. Verified: NEITHER repo ships a movable alias (janitor tags =
  v0.4.3…v0.6.1 full versions only), so zero friction today; `v*.*.*` is the precise future-proof form.
- **bypass = `[]`** — new-tag creation is unrestricted → publish.py still cuts releases, NO bypass
  actor. Zero publish-path impact.
- **literal lock** — readback-pin the exact `ref_name.include` GitHub echoes on first apply (same as
  `actor_id:5`); both verify-blocks assert `rules == [deletion, update]` + `bypass_actors == []`.

ROLLOUT (single-owner-per-domain, on USER ratify, folded into the same CPV-G3-cleared publish):
janitor → add `baseline-tag-protect` to `branch_protection_lib.py` (3rd payload + orphan-name
awareness), applied Tier-0; maintainer → 3rd payload in `workflow-protect-branch` + apply; MANAGER →
ratify/gate only. Janitor threads: #14 comments 4635916630 / 4635958034 / 4636007547. STATUS:
plugin-side consensus CLOSED; MANAGER + maintainer escalated to owner, recommendation = approve;
**only the USER's Tier-3 ratify remains.** Maintainer's other audit items are maintainer-internal
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
