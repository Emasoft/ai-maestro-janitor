# Ratified branch-protection baseline — full reference

The janitor and maintainer plugins ratified a unified three-ruleset
branch-protection baseline — the two branch rulesets plus a tag-protection
ruleset (janitor
[#14](https://github.com/Emasoft/ai-maestro-janitor/issues/14) /
maintainer [#7](https://github.com/Emasoft/ai-maestro-maintainer-agent/issues/7)).
Both plugins emit **byte-identical** ruleset JSON after key-sorted
normalization. This document is the authoritative reference for the
payloads, the required-status-checks auto-detection, and the apply
algorithm the skill and the Tier 2 guard path share.

## Table of contents

- [The three rulesets](#the-three-rulesets)
- [Why `~DEFAULT_BRANCH`](#why-default_branch)
- [Why the admin bypass on baseline-pr-and-checks](#why-the-admin-bypass-on-baseline-pr-and-checks)
- [Why tag protection (baseline-tag-protect)](#why-tag-protection-baseline-tag-protect)
- [Required status checks — auto-detection](#required-status-checks--auto-detection)
- [Apply algorithm (idempotent-by-name + legacy cleanup)](#apply-algorithm-idempotent-by-name--legacy-cleanup)
- [Single source of truth](#single-source-of-truth)

## The three rulesets

The first two: `target: branch`, `enforcement: active`,
`conditions.ref_name.include: ["~DEFAULT_BRANCH"]`,
`conditions.ref_name.exclude: []`. The third (`baseline-tag-protect`) is
`target: tag`, scoped to `["refs/tags/v*.*.*"]`.

### 1. `baseline-history-protect`

No bypass actors — history protection applies to everyone, including
admins.

```json
{
  "name": "baseline-history-protect",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] }
  },
  "bypass_actors": [],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" }
  ]
}
```

### 2. `baseline-pr-and-checks`

The repo-admin `RepositoryRole` (`actor_id: 5`) gets an `always` bypass.

```json
{
  "name": "baseline-pr-and-checks",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] }
  },
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ],
  "rules": [
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "<auto-detected-job-id>" }
        ]
      }
    }
  ]
}
```

`required_status_checks` is `[]` when the repo has no CI check-runs yet
(see auto-detection below). The rule is still present — strict policy on
— it just gates on no specific contexts until CI surfaces some.

### 3. `baseline-tag-protect`

`target: tag` (NOT branch). No bypass actors — release-tag immutability
applies to everyone; creating a NEW tag is unrestricted, so `publish.py`
still cuts each `vX.Y.Z` with no bypass.

```json
{
  "name": "baseline-tag-protect",
  "target": "tag",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["refs/tags/v*.*.*"], "exclude": [] }
  },
  "bypass_actors": [],
  "rules": [
    { "type": "deletion" },
    { "type": "update" }
  ]
}
```

> Apply-time discipline: the exact GitHub-accepted literal for a
> `target: tag` ruleset's `ref_name.include` is READBACK-PINNED on the first
> real apply (same defence-in-depth as `actor_id: 5`). `refs/tags/v*.*.*` is
> the REST-canonical form we ship; if GitHub normalises or rejects it,
> reconcile to the echoed form — byte-identical with the maintainer — before
> either plugin calls it done.

## Why `~DEFAULT_BRANCH`

The `~DEFAULT_BRANCH` magic ref resolves to whatever branch the repo
declares as its default **at apply time** — so the same ruleset JSON is
portable across repos that use `main`, `master`, or a custom default,
and is byte-identical with the maintainer plugin. The janitor library
accepts a `default_branch` argument only to fail loudly on an empty
value and for signature symmetry; the emitted `include` is ALWAYS
`["~DEFAULT_BRANCH"]`, never `["refs/heads/<name>"]`.

## Why the admin bypass on baseline-pr-and-checks

A solo admin on their own repo would be locked out by
`required_approving_review_count: 1` — they cannot approve their own PR,
and there is no second reviewer. Granting the repo-admin role an
`always` bypass on the PR/checks ruleset keeps the self-merge path open
for a one-person repo while still enforcing the PR flow for everyone
else. History protection (`baseline-history-protect`) has NO bypass — a
force-push or branch deletion is never acceptable, admin or not.

**Emergency history-scrub path (the one exception, out-of-band).** Because
`baseline-history-protect` has `bypass_actors: []` on `non_fast_forward`, a
legitimate history rewrite (e.g. scrubbing a leaked secret from `main`) is
**never reachable via a push** — not even by an admin. The only sanctioned path
is an out-of-band owner toggle: temporarily set the ruleset's `enforcement` to
`disabled` (or `evaluate`) in **Settings → Rules → Rulesets**, perform the
rewrite + `--force-with-lease` push, then immediately re-enable `active`. This
is a deliberate, audited, human-only operation — documented here so a future
agent reads "history is protected, scrubbing is owner-toggle-then-rewrite," not
"history is permanently immutable."

## Why tag protection (baseline-tag-protect)

The branch pair protects only `~DEFAULT_BRANCH`. Release **tags** were
unprotected — and we both ship installs off `v*` tags, so a leaked token (or
accident) could **delete or MOVE** a published `vX.Y.Z` to re-point installers
at arbitrary code. A post-hoc CI gate can't catch this: a tag moved onto a
commit that itself passes CI sails through. `baseline-tag-protect` closes the
gap. Tri-party consensus (janitor + maintainer + MANAGER), USER-ratified
Tier-3 (release integrity), janitor#14.

- **`rules: [deletion, update]`, NOT `non_fast_forward`.** "Restrict updates"
  (`update`) blocks **every** repoint of an existing tag. `non_fast_forward`
  blocks only force-pushes — and a tag *fast-forward-moved onto a descendant*
  commit is NOT a force-push (append a malicious child commit, ff-move the tag
  onto it → bypass). `update` is minimal-complete and correct regardless of how
  GitHub evaluates tag fast-forwards.
- **Scope `["refs/tags/v*.*.*"]`.** Protects immutable full-semver release tags
  while leaving a *future* movable `vN`/`latest` alias free (`~ALL` or bare
  `v*` would freeze such an alias). Neither plugin currently ships a movable
  alias, so this is zero-friction today and future-proof.
- **`bypass_actors: []`.** Restricting *deletions* and *updates* does NOT
  restrict *creations* — so `publish.py` still cuts each new `vX.Y.Z` with no
  bypass actor. Zero publish-path impact.

## Required status checks — auto-detection

The exact shape the GitHub rulesets API wants for `required_status_checks`
is a **list of `{"context": "<name>"}` objects** (verified against the
maintainer plugin's `workflow-bootstrap` ruleset template). The janitor
auto-detects the contexts by parsing the repo's **workflow files** — it
NEVER hard-codes job ids.

`branch_protection_lib.detect_required_status_checks(project_root)`:

Globs `.github/workflows/*.yml` and `*.yaml` under `project_root`,
`yaml.safe_load`s each, and for every job emits its `name:` if set, else
the job id (the same value GitHub derives the check context from). The
result is a **sorted, de-duplicated** list of `{"context": "<name>"}`
dicts. A single malformed/unreadable workflow is skipped (never fatal);
a project with no workflows (or all unparseable) yields an empty list —
the ruleset is still created, gating on no specific contexts.

> Why the workflow CONFIG and not the runtime check-runs API
> (`repos/{slug}/commits/{branch}/check-runs`): runtime check-runs are
> EMPTY on a fresh repo whose CI has never run, so the very first PR
> would be ungated; and check-run *names* do not always equal the
> *context* GitHub uses for branch-protection matching — feeding the
> wrong contexts gets the whole rulesets POST/PATCH rejected with
> **HTTP 422 Validation Failed**, failing the entire apply. The
> configured workflow job ids/names are the source of truth GitHub
> itself derives the contexts from. This is the cross-plugin-agreed
> source (janitor #14) and matches the maintainer plugin's approach.

## Apply algorithm (idempotent-by-name + legacy cleanup)

`branch_protection_lib.apply_baseline_rulesets(slug, default_branch, project_root)`:

1. Fetch the repo's ruleset list ONCE. If the lookup fails, abort the
   whole apply (we can't tell PATCH from POST → would risk a duplicate).
2. Build a `{name: id}` map from the existing rulesets.
3. Auto-detect required status checks by parsing `project_root`'s
   `.github/workflows/*`; build the three ratified payloads (only
   baseline-pr-and-checks embeds the checks; the tag ruleset is static).
4. For each ratified payload, in order:
   - if a ruleset with the same name already exists → `PATCH
     repos/{slug}/rulesets/{id}` (reports `updated`),
   - else → `POST repos/{slug}/rulesets` (reports `created`).
5. **Only if all three ratified rulesets succeeded**, delete the orphaned
   pre-migration `janitor-baseline` ruleset
   (`DELETE repos/{slug}/rulesets/{id}`; reports `deleted`/`absent`). A
   failed apply KEEPS the legacy ruleset — stripping it after a failed
   apply would leave the branch unprotected.

Returns `(all_ok, results, checks)` where `results` is one
`(name, ok, message)` tuple per ratified ruleset plus one for the legacy
cleanup, and `checks` is the auto-detected required-status-checks list
that was actually applied (the caller reuses it for its announcement so
the workflow-file parse runs once, not once per consumer).

## Single source of truth

`scripts/lib/branch_protection_lib.py` is the only place the payloads
live. Both the Tier 1 user-invoked skill (`/janitor-branch-protection-setup`)
and the Tier 2 guarded auto path (`scripts/guard/branch_protection_apply.py`)
call `baseline_ruleset_payloads()` / `apply_baseline_rulesets()` — never
their own copy. Keep them byte-identical with the maintainer plugin; any
deviation (bypass-actor changes, loosened parameters, disabled checks,
enforcement switch) is NON-EXEMPT and requires MANAGER approval per the
ratification governance.
