---
trdd-id: 7EXBJB03
title: History rewrite must be allowed in every ruleset of every repo and the janitor must enforce it
column: complete
created: 2026-08-27T18:51:47+0200
updated: 2026-08-28T03:25:26+0200
current-owner: janitor-main-session
task-type: security
priority: high
scope: project
project-id: ai-maestro-janitor
severity: major
min-approval-requirement: user
labels: [branch-protection, rulesets, baseline, fleet, owner-ruling]
blocked-by: []
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# History rewrite must be allowed in every ruleset of every repo

## ⏵ STATE — READ THIS FIRST ON RESUME

**USER Tier-3 ruling, 2026-08-27, verbatim:** *"i already told you that history rewrite is allowed
and must be allowed in all rulesets of all github repos. the janitor must ensure of that. decide
the rest by yourself."*

The code SSOT is DONE and verified. The prose sweep and the test sweep were delegated and are
landing. **The fleet IS now repaired — applied 2026-08-28, see the apply record below.**

### What changed in the ratified baseline (`branch_protection_lib.baseline_ruleset_payloads`)

| ruleset | before | after |
|---|---|---|
| `baseline-history-protect` | rules `[deletion, non_fast_forward]`, admin bypass | rules **`[deletion]`**, admin bypass unchanged |
| `baseline-tag-protect` | rules `[deletion, update]`, **`bypass_actors: []`** | rules unchanged, **admin bypass added** |
| `baseline-pr-and-checks` | — | UNCHANGED |

### Why each half, since "decide the rest by yourself" was the instruction

**`non_fast_forward` removed, not merely bypassed.** It is GitHub's "Block force pushes" rule —
the single rule whose entire function is to forbid a history rewrite. Keeping it while being told
history rewrite must be allowed *in all rulesets* is not a defensible reading. The admin bypass
added on 2026-08-13 does not satisfy the directive either: a bypass is a KEY TO A LOCK, and the
ruling says the lock must not be there. This is the same move, for the same stated reason, that
removed `required_linear_history` on 2026-08-08 (janitor#14) — the guardian must not be the thing
blocking the work.

**`deletion` kept.** Losing a branch is not a history rewrite; it is the loss of the ref you would
rewrite FROM. It still binds every non-admin, which is where the residual protection now lives.

**Why the two rulesets got DIFFERENT treatments from one sentence — do not "fix" this into
consistency.** On branches the offending rule was REMOVED; on tags `update` was KEPT and a bypass
added instead. That is deliberate. `non_fast_forward` exists only to forbid a history rewrite, so
under this directive it has no remaining job. Tag `update` has a job that survives the directive
— stopping CI, an agent, or a contributor from silently repointing a published release tag — and
it blocks the owner only as a side effect. Removing the rule is right where the rule IS the
prohibition; a bypass is right where the rule protects against someone else and merely caught the
owner in the blast radius.

**The tag ruleset was the REAL gap, and it is why the ruling was needed at all.** With
`bypass_actors: []` nobody — owner included — could repoint or drop a tag. So after a *permitted*
history rewrite, every existing release tag was stranded on a commit that no longer existed, with
no way to move it. **A rewrite you cannot follow through on is a rewrite you are not allowed to
make**, so the empty list contradicted the directive in effect even though `non_fast_forward`
never appeared in that ruleset. TRDD-X4LJFTB4 hit exactly this: the 3.4.0 push was refused on
`main` *and* both tag refs. Non-admins still get `deletion` + `update`, which is the actual threat
model (CI, agents, or a contributor silently moving a published release tag). New-tag CREATION was
already unrestricted, so `publish.py` is unaffected.

### The "must ensure" half needed NO new code — verified, not assumed

The existing drift machinery already repairs a repo sitting on the old baseline. Measured against
the live functions, not inferred:

```
drift(old hist): ['baseline-history-protect: extra rule non_fast_forward (a repair apply would remove it)']
drift(old tag ): ['baseline-tag-protect: bypass_actors differ']
drift(new hist): []   drift(new tag ): []
```

`ruleset_content_drift` flags an EXTRA live rule and a `bypass_actors` mismatch. Adding a detector
for this would have been duplicate machinery.

**But that measurement alone does NOT establish that a live repo gets repaired, and the first
draft of this card claimed it did.** `ruleset_content_drift` is a PURE dict-diff; the sentence
"a repair apply would remove it" inside its own drift message is PROSE, not evidence. An
adversarial review caught the gap. The actual chain, traced end to end through the code:

`baselines_content_current` → consumed at `branch_protection_apply.py:165` (gate 6) → on drift
it **falls through** ("fall through: gate 7 + the ratified re-apply repair the drift") → gate 7
admin check → `apply_baseline_rulesets` → `gh api --method PUT repos/<slug>/rulesets/<id>` with
`--input -` carrying the WHOLE payload. PUT, never PATCH — a PATCH 404s on real GitHub
(janitor#14).

**On "PUT drops a rule the payload omits" — that is GitHub's semantics, not ours, so cite the
right evidence.** Reading janitor code establishes only that we SEND the full payload to the PUT
endpoint; it says nothing about whether GitHub replaces or merges the `rules` array. The evidence
that it REPLACES is empirical and already in hand: `required_linear_history` was dropped from this
same payload (janitor#14) and the fleet was applied and **per-object verified** on 2026-08-20 with
the rule gone. Same endpoint, same mechanism, same shape of change. If that precedent is ever
doubted, re-verify with a real `gh api repos/<slug>/rulesets/<id>` GET after the first apply
rather than reasoning from our own source.

**Two preconditions, both of which fail SAFE (no repair) rather than wrong:**

1. **The per-ruleset DETAIL fetch must succeed.** The ruleset LIST endpoint returns summaries
   with no `rules`/`bypass_actors`, so comparison needs `fetch_ruleset_detail`, which returns
   `None` on any non-zero `gh` exit, timeout or JSON error. Then `baselines_content_current`
   returns `None` and gate 6 RETURNS 0, logging `skip: ruleset detail lookup failed … content
   unverified`. Such a repo is neither reported nor repaired — grep that log line before
   declaring the fleet converged.
2. **The viewer must be a repo admin** (gate 7). Otherwise the apply is skipped and surfaced for
   human review.

So the accurate claim is: **detected as drifted and repaired on the next apply, PROVIDED the
detail fetch succeeds and the viewer is admin.** Verify the fleet per-object after applying;
do not infer convergence from silence, because precondition 1 is also silent.

## NEXT ACTION

**Re-apply the baseline across the fleet — and note that NOTHING does this automatically.** Every
fleet repo was last applied on 2026-08-20 with the OLD shape (per `manager-approval-defaults.md`
§F), so each still carries `non_fast_forward` and an empty tag bypass.

**There are TWO apply paths and only one of them is fleet-wide.** An earlier draft of this card
implied the heartbeat would converge the fleet on its own. It will not:

| path | scope | trigger |
|---|---|---|
| `scripts/guard/branch_protection_apply.py` | **THIS repo only** — `detect_repo_slug` reads the CURRENT project's `.claude-plugin/plugin.json`, so it can only ever repair the repo the session is running in, and only when that project IS a Claude plugin with a github `repository` URL | automatic (heartbeat guard) |
| `scripts/github_config_fix.py --all` (`/janitor-github-config-fix`) | **the whole fleet** — iterates every ai-maestro plugin repo from the marketplace catalog, fetching each remote's workflows to detect CI contexts | **manual only** |

So the fleet converges only when someone deliberately runs the second one. It is PLAN-FIRST:
without `--apply` it prints exactly what would change and mutates nothing.

```
uv run scripts/github_config_fix.py --all            # plan, mutates nothing
uv run scripts/github_config_fix.py --all --apply    # after reading the plan
```

Applying the ratified baseline AS-IS is Tier-0/EXEMPT, so this needs no further approval — but it
touches every fleet repo, so read the plan first and report the per-repo result. Verify
per-object afterwards; do not infer convergence from silence (precondition 1 above is silent).

## Known stale references OUTSIDE this repo — do NOT edit from here

`~/.claude/rules/manager-approval-defaults.md` §F documents the old baseline in prose (it names
`non_fast_forward` and `bypass_actors: []`). That file belongs to **ai-maestro**, not to this
plugin (the janitor's shipped global rules are the ones in this repo's `rules/`), so per
`~/.claude/rules/how-to-fix-issues-of-other-projects.md` it must NOT be edited from this session.
It already tells its reader to build payloads from this repo's code SSOT and never from its prose,
so it is wrong-but-declared-non-authoritative. File it upstream.

## Provenance

USER Tier-3 ruling 2026-08-27, given while TRDD-X4LJFTB4 (the 3.4.0 push block) was awaiting an
owner decision — the tag refusals in that card are the concrete incident this ruling generalises.

## Fleet apply record — 2026-08-28

`uv run scripts/github_config_fix.py --all --apply` over the whole fleet: **14 repos updated,
0 errors**, each reporting all three rulesets updated by id plus the six legacy names confirmed
absent. Re-audit: **zero `BASELINE_CONTENT_DRIFT` fleet-wide.**

**Verified live rather than from the tool's own summary** (`gh api repos/…/rulesets`):
`baseline-history-protect` now carries `deletion` ONLY — `non_fast_forward` is gone, so history
rewrite is permitted, which was the USER's ruling — alongside `baseline-pr-and-checks` and
`baseline-tag-protect`.

**A finding that survives and is NOT this card's:** 9 repos still report `NO_REQUIRED_CHECKS`.
Different condition entirely — no detectable CI job to require, so the baseline deliberately
OMITS the `required_status_checks` rule there (GitHub 422s an empty list). The applier already
routes it to `/janitor-github-workflow-doctor`. Do not read it as a baseline failure; I briefly
misread the audit's per-repo finding COUNT as unconverged drift, and the distinction is the
finding TYPE, not the count.

