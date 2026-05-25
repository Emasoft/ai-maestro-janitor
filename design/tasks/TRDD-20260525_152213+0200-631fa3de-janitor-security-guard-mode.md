---
trdd-id: 631fa3de-77a6-400f-841c-c745a33637d4
title: Janitor security guard mode — evaluate autonomous remediation of high-risk findings
status: not-started
created: 2026-05-25T15:22:13+0200
updated: 2026-05-25T15:22:13+0200
---

# TRDD-631fa3de — Janitor security guard mode: evaluate autonomous remediation of high-risk findings

**Filename:** `design/tasks/TRDD-20260525_152213+0200-631fa3de-janitor-security-guard-mode.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)

## 1. Origin (user requests, verbatim)

> "we must also evaluate the possibility of the janitor acting to fix security
> risks in situations where the risk is too high, configuring github and editing
> yaml files if needed."

> "the user must be able to safely entrust the projects to the janitor plugin,
> and be sure that it will guard the plugin from any security danger."

This is an **evaluation request**, not an implementation order. The deliverable
is this design + a recommendation; nothing autonomous-acting ships until the
user picks a direction (see §9).

Context: the read-only DETECTION layer already shipped (commit 382d1e5) —
`workflow-security` (heartbeat Sentinel scan of `.github/workflows/`) and
`branch-protection` (read-only gh-api check of the default branch). Those
SURFACE findings; this TRDD is about whether/how the janitor should ACT on them.

## 2. The core tension — RULE 1

The user's own global CLAUDE.md RULE 1 is a hard invariant:

> "NEVER take charge of a project without explicit user permission … surface,
> don't act … applies to the orchestrator AND all spawned subagents."

The entire janitor architecture is built on it: detectors are dumb Python
scripts that emit *drift lines*; a human (or Claude, in an interactive turn)
decides and acts. The heartbeat protocol is explicit: *"Surface stdout
verbatim … one pass, no sub-agents."*

"Acting to fix security risks … configuring github and editing yaml" is, by
definition, the janitor taking charge of the project. So this feature is only
admissible as an **explicitly user-authorised, opt-in exception** to RULE 1 —
never a silent default. The exception must be scoped, transparent, and
reversible, or it stops being "safe to entrust" and becomes "a bot that edits
my repo behind my back."

## 3. Hard constraint: the heartbeat detector scripts MUST stay read-only

The heartbeat fires a fresh Claude turn that shells out to `dispatch.py`, which
runs the detector scripts and surfaces their stdout. The detector scripts have
**no LLM** — they cannot reason about whether a YAML edit preserves a workflow's
intent, whether a fix breaks CI, or whether "the risk is too high." A dumb
script that rewrites workflow YAML or flips repo settings is exactly the
unsafe-to-entrust failure mode.

Therefore: **whatever we build, the detector scripts themselves never mutate the
repo.** Any "acting" lives in a surface that has judgment (an interactive,
user-invoked skill where Claude proposes+applies with the user watching) or, for
the narrow auto path, in code restricted to a single idempotent reversible API
call with a loud announcement + audit log.

## 4. Taxonomy of "fixes" by blast radius

| Fix | Blast radius | Reversible? | Needs LLM judgment? | Auditable? |
|---|---|---|---|---|
| **Create baseline branch ruleset** (require PR, block force-push, block deletion on default branch) | Repo-wide policy; surprises a team if silent | Yes — delete the ruleset | No — fixed, standard hardening | Yes — repo settings + GH audit log |
| **Edit workflow YAML to fix injection** (move `${{ }}` into `env:`) | Can break CI; a wrong "fix" can DISABLE a security check | Yes via git, but a bad push to `main` is visible to all | **Yes** — must understand the workflow | Yes via git history |
| **Rotate/remove a committed secret** | Breaks anything using the secret; history rewrite is destructive | Hard (history rewrite) | Yes | Partly |
| **Pin an unpinned action to a SHA** | Low — mechanical | Yes | Low | Yes |

The two the user named — "configuring github" (row 1) and "editing yaml" (row 2)
— sit at OPPOSITE ends of the safety spectrum. They must be treated differently.

## 5. Proposed tiered remediation model

- **Tier 0 — DETECT + SURFACE.** Default, always on, RULE-1 compliant. *Shipped*
  (`workflow-security`, `branch-protection`, plus the existing security skills).

- **Tier 1 — GUIDED FIX (user-invoked skill).** The user explicitly runs a
  skill; Claude proposes and applies fixes WITH the user in the loop. This is
  already how `/janitor-github-workflow-doctor` works for YAML, and is
  RULE-1 compliant because the user invoked it. Extension: add a
  `/janitor-branch-protection-setup` skill that, on request, creates the
  baseline ruleset (and an explicit "apply this fix" path in the doctor skill).
  **This is the right home for YAML fixes** — judgment + review, no autonomy.

- **Tier 2 — GUARDED AUTO-REMEDIATION (opt-in, OFF by default).** A strictly
  bounded allowlist of actions the janitor performs WITHOUT a human in the loop,
  ONLY when the user has flipped `guard_mode_enabled: true` for that project.
  Recommended membership of the allowlist, in safety order:
  1. **Branch-protection baseline** (safest; row 1). Single idempotent
     `gh api` call, reversible, auditable, touches no code. Strong candidate.
  2. **Workflow YAML fixes** (riskiest; row 2): if included at all, the janitor
     **opens a PR** with the fix — NEVER a direct push to the default branch ("a
     bad PR is just an unmerged PR"). And because PR-authoring needs LLM
     judgment, it cannot run from the dumb heartbeat — it must be a
     user-invoked skill, i.e. it collapses back into Tier 1. **Recommendation:
     EXCLUDE auto-YAML-edit from Tier 2 entirely.**

## 6. Trust model — what makes it "safe to entrust"

Trust is earned by construction, not asserted:

- **Opt-in, OFF by default.** RULE 1 remains the default everywhere. Guard mode
  is a per-project knob the user consciously enables. (Mirrors how
  `plugin_auto_update_enabled` etc. are explicit.)
- **Allowlist, not open-ended.** The janitor acts only on a fixed enumerated set
  of safe actions. No "fix anything you find."
- **Reversibility first.** Only reversible actions auto-run. Destructive ones
  (secret history-rewrite) are NEVER auto; they are surfaced for the human.
- **Least privilege / least surprise.** Branch-protection baseline yes; pushing
  to `main` no; org-level changes no; touching another project's repo no.
- **Transparency + audit trail.** Every autonomous action is announced in the
  heartbeat output AND appended to `.janitor/logs/<detector>.log` with
  timestamp, repo, the exact API call/diff, and the before/after state — exactly
  the audit trail CLAUDE.md RULE 0.5 demands.
- **Idempotent + deduped.** Re-running never double-applies; a `…-acted.txt`
  ledger records what was done so a fix is attempted once, then re-surfaced (not
  re-attempted) if it didn't stick.

## 7. Defining "risk too high" — user-set, never janitor-invented

The janitor must not invent its own "this is bad enough to act" threshold —
that is itself a judgment call it will get wrong. Instead the user parameterises
it:

- `guard_mode_enabled` (bool, default **false**).
- `guard_actions` (allowlist, e.g. `"branch-protection"`; YAML-edit deliberately
  not offered, or offered only as `branch-protection,workflow-pr`).
- `guard_min_severity` (default `critical`) — only findings at/above this
  severity are eligible.
- The branch-protection auto path additionally self-gates on `viewerPermission
  == ADMIN` (can't configure what you can't administer) and only on the default
  branch.

## 8. Recommendation

1. **Keep the heartbeat detectors read-only forever** (Tier 0). Non-negotiable.
2. **Invest in Tier 1** as the primary "acting" surface: extend the doctor skill
   with an explicit apply-fix path and add a `/janitor-branch-protection-setup`
   skill. RULE-1 compliant, judgment-bearing, reviewable. This delivers most of
   the "guard my project" value with near-zero risk.
3. **For genuine autonomy (Tier 2), ship ONLY the branch-protection baseline
   action**, behind `guard_mode_enabled: false` (default off) + the §7 gates,
   with loud announcement, full audit log, idempotent ledger, and reversibility.
   This is the one action that is high-value, idempotent, reversible, auditable,
   and needs no LLM judgment.
4. **Do NOT auto-edit workflow YAML on `main`.** The most the janitor should
   ever do unattended with a YAML fix is open a reviewable PR — and since that
   needs LLM judgment it belongs in a user-invoked skill (Tier 1), not the
   heartbeat.

**The central tradeoff:** maximum autonomy ("set and forget; the janitor fixes
everything") vs. safety + RULE 1 + blast-radius control. The recommended middle
path keeps the dumb heartbeat read-only, puts YAML fixes behind interactive
review, and grants exactly one narrow autonomous action (branch-protection
baseline) that is reversible and auditable — which is what makes the plugin
genuinely *safe to entrust* rather than *a liability that edits your repo*.

## 9. Open decision for the user (blocking — pick before implementing)

- **Option A (recommended):** Tier 1 skills only — extend doctor with apply-fix
  + add `/janitor-branch-protection-setup`. No autonomous mutation anywhere.
- **Option B (recommended + 1):** Option A PLUS Tier 2 limited to the
  branch-protection baseline behind `guard_mode_enabled` (default off). No
  autonomous YAML editing.
- **Option C (maximal):** Option B PLUS unattended workflow YAML fixes via
  auto-opened PRs (never direct pushes). Larger surface, more moving parts.
- **Option D:** Do nothing further — detection-only is enough for now.

## 10. Implementation sketch (per option, for when chosen)

- **Tier 1 skills:** `/janitor-branch-protection-setup` → builds a baseline
  ruleset JSON and runs `gh api --method POST repos/{o}/{r}/rulesets` after
  showing the user the exact payload; doctor "apply-fix" → reuse the existing
  recipes to Edit the YAML with the user watching.
- **Tier 2 branch-protection:** a NEW user-authorised action module (NOT the
  read-only detector) gated on `guard_mode_enabled`, run from a dedicated
  path, writing a `branch-protection-acted.txt` ledger + an audit log entry +
  a `[guard] created baseline ruleset on {repo}@{branch}` announcement.
- **Tier 2 workflow-PR:** a user-invoked skill that branches, Edits the YAML
  via doctor recipes, pushes the branch, and opens a PR — explicitly never
  touching the default branch directly.

## 11. Security considerations

- Auto-creating a ruleset changes who-can-do-what; announce + log so the team
  is never silently locked out.
- A wrong YAML "fix" can DISABLE a security control — this is why YAML edits are
  review-gated, never autonomous-on-main.
- The action code paths run `gh` with the user's token; they must use a fixed
  argument vector (no shell interpolation of repo/branch names — sanitise),
  honour timeouts, and fail safe (any error → surface, never half-apply).
- Guard mode must HARD-REFUSE cross-project action (only the armed project's
  repo) and non-default branches, mirroring the plugin-update scope refusals.

## 12. Test scenarios (for the chosen option)

- guard off (default) → zero autonomous actions even on CRITICAL findings.
- guard on + branch unprotected + admin → baseline ruleset created once; second
  fire is a no-op (ledger); announced + logged.
- guard on + non-admin → no action (can't administer), surfaces instead.
- guard on + action fails (gh error) → no half-apply, surfaces the failure.
- YAML auto-edit on main → MUST NOT happen in any option; PR path (if Option C)
  never targets the default branch.

## 13. Out of scope

- Secret rotation / git history rewrite (destructive — always human).
- Org/enterprise-level rulesets.
- Acting on repos other than the armed project's.
- Anything that pushes directly to the default branch.
