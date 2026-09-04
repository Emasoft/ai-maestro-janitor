---
trdd-id: BH32A1A5
title: the branch-protection guard may resolve the janitors own repo from inside every project
column: todo
created: 2026-09-04T05:43:59+0200
updated: 2026-09-04T05:43:59+0200
current-owner: janitor-main-session
task-type: audit
priority: medium
severity: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [branch-protection, guard, fleet, env]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [janitor#294, TRDD-DD0M4QL7, TRDD-H8WRCW0I]
---

# The branch-protection guard may protect the wrong repo

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-04

- **ANSWERED, and the answer is "correct outcome, fragile mechanism" — NOT the described
  defect.** Measured, not inferred:
  - `dispatch.py:2269` launches the guard as `subprocess.run([str(script)], ...)` with
    **no `env=` argument**, so the child inherits dispatch's environment unchanged.
  - In the heartbeat path on this host, **both `CLAUDE_PLUGIN_ROOT` and
    `CLAUDE_PROJECT_DIR` are UNSET** (measured directly).
  - So `plugin_root_env` is `""` twice over and `plugin_root = Path("." )` — **the guard's
    cwd, which is the project**. It protects the right repo.
  - **Every link in that chain is now checked, not assumed** (a first version measured only
    the env vars, from an interactive shell rather than the guard's own process, which does
    not by itself establish the guard sees the same environment):
    - **No hook invokes this guard.** `branch_protection_apply` appears nowhere under
      `hooks/` or `.claude/` except as documentation; `dispatch.py` is its only caller. So
      the hook context — the one that *does* set `CLAUDE_PLUGIN_ROOT` — is never the path.
    - **Neither the dispatcher stub nor `dispatch.py` sets `CLAUDE_PLUGIN_ROOT`.** Grepped
      both; no assignment, no `setdefault`.
    - **Nothing in the chain calls `os.chdir`** — not the stub, not `dispatch.py`, not the
      guard. So the cwd `Path(".")` resolves against is the invoking shell's, which for the
      cron heartbeat is the project directory. The "cwd = the project" step was an
      assumption until this check.
- **The hazard is therefore CONDITIONAL on a context that does set `CLAUDE_PLUGIN_ROOT`**
  (a plugin hook invocation, as opposed to the cron heartbeat). In that context the cache
  dir *does* carry both a manifest naming `Emasoft/ai-maestro-janitor` and 7 workflow
  files, so the wrong-repo resolution is reachable — it simply is not what happens on the
  path that actually runs today.
- **NEXT ACTION** — decide whether the fallback ORDER is right, given the correct behaviour
  currently depends on two env vars both being absent. Reversing it
  (`CLAUDE_PROJECT_DIR` first) would make the right answer intentional rather than
  incidental. That is a change to an automated write path: **advisor first.**
- **DO NOT re-derive the env answer.** It took three contradictory inferences before one
  command settled it.

## What is established, by measurement

`scripts/guard/branch_protection_apply.py:162-169`:

```python
plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
if not plugin_root_env:
    plugin_root_env = os.environ.get("CLAUDE_PROJECT_DIR", "")   # fallback
plugin_root = Path(plugin_root_env or ".")
slug = bpl.detect_repo_slug(plugin_root)
```

and at `:234` the same `plugin_root` is passed to
`bpl.baselines_content_current(slug, default_branch, plugin_root)`, which globs
`.github/workflows/*` under it via `detect_required_status_checks`.

`detect_repo_slug` reads **`.claude-plugin/plugin.json` FIRST and treats it as
authoritative** ("a deliberate declaration of which repo a plugin belongs to"), falling
back to the git origin remote only when absent.

**Measured on this host** — the installed plugin cache
(`~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.4.14/`) contains:

- `.claude-plugin/plugin.json` with `repository: https://github.com/Emasoft/ai-maestro-janitor`
- **7 files under `.github/`**, including `workflows/release.yml` and `workflows/zizmor-scan.yml`

So both inputs the guard needs are present in the cache dir, and both name the JANITOR.

## The hazard, stated as a conditional because that is what it is

**IF** `CLAUDE_PLUGIN_ROOT` is bound to the installed cache dir when this guard runs,
**THEN** from inside *any* project the guard resolves `slug = Emasoft/ai-maestro-janitor`,
detects the *janitor's own* workflow contexts, and applies or verifies branch protection
against the **janitor's repo instead of the project it is running in**.

Consequences if it holds: user projects are never protected by the automated path (only by
the human-invoked skill), and the janitor's own repo gets repeatedly re-applied from N
projects. Neither is loud — a successful apply on the wrong repo logs success.

**The fallback ordering is the thing that makes this plausible rather than paranoid.**
`CLAUDE_PLUGIN_ROOT` first, `CLAUDE_PROJECT_DIR` only when it is unset, on a guard whose
job is to protect the *project's* repo. For that ordering to be right,
`CLAUDE_PLUGIN_ROOT` must mean "the plugin manifest of the project being guarded" — which
is what `:162`'s comment says ("resolve repo slug from this project's plugin.json"), and
which is TRUE for a project that is itself a plugin. It is exactly the non-plugin project
and the plugin-cache binding where the two readings diverge.

## Why this card exists rather than a fix — read this before touching it

Within one session I reasoned to **both** conclusions:

1. First I accepted a reviewer's claim that guard and skill diverge (`plugin_root` vs
   `project_root`) and nearly filed a defect.
2. Then I declined it, on the grounds that `slug` derives from the SAME `plugin_root`, so
   the two uses are **consistent** — and `if not slug` bails safe.
3. Then a second reviewer pointed out that *consistent is not correct*: self-consistently
   reading the janitor's own cached copy is exactly as wrong, and quieter.

(2) was the error, and it is the session's signature defect in a new register: I checked
that two things AGREED and reported that as correctness, without asking what they agreed
ABOUT. The `if not slug` safety I cited is also void here — the manifest is present in the
cache, so a slug always resolves; the bail never fires.

## Why `priority: medium` — derived, not adopted

The field was `high` while this looked like a live defect, and the STATE block was later
rewritten to say the running path resolves correctly. Medium is the value that follows
from the facts now established, and the derivation is recorded because a number adopted
on someone's recommendation is unjustified again the next time anyone reads it:

- **Not `low`.** The hazard is one environment variable away from live, and its failure is
  **silent** — an automated write path targeting the wrong repo logs success. Silent-wrong
  outranks noisy-broken.
- **Not `high`.** It does not manifest on any path that currently runs, and all four links
  of that are verified: no hook invokes the guard, neither the stub nor `dispatch.py` sets
  `CLAUDE_PLUGIN_ROOT`, both vars are unset, and nothing calls `chdir`.
- **Therefore `medium`:** real impact, currently-zero likelihood, non-zero fragility.

## Acceptance criteria

- [ ] One real guard invocation logs `CLAUDE_PLUGIN_ROOT` and the resolved `slug`, from a
      project that is NOT ai-maestro-janitor. That single line settles it.
- [ ] If the hazard is real: a decision recorded on whether the guard should resolve from
      `CLAUDE_PROJECT_DIR` first, or whether the current ordering is deliberate — with the
      advisor consulted, because this changes which repos an automated path writes to.
- [ ] If a change lands, a test pins which directory the slug resolves from, for both a
      plugin project and a non-plugin project.
- [ ] Whatever the answer, `:162`'s comment is made to state it explicitly — the comment
      currently says "this project's plugin.json", which reads as the project even if the
      code means the plugin cache.

## Notes and lessons learned

- **"The two uses are consistent" is not a correctness argument.** It rules out one class
  of bug (disagreement) and says nothing about whether the agreed-upon value is right.
  Both a correct guard and a guard silently pointed at the wrong tree are self-consistent.
- **A safety bail that cannot fire is not a safety bail.** I cited `if not slug` as
  fail-safe without checking that the manifest which makes `slug` resolve is present in
  precisely the directory the hazard concerns.
