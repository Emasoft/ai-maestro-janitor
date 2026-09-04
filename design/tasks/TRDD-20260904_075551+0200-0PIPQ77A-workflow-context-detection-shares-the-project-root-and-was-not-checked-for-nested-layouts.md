---
trdd-id: 0PIPQ77A
title: workflow-context detection shares the project root and was never checked for nested layouts
column: backburner
created: 2026-09-04T07:55:51+0200
updated: 2026-09-04T07:55:51+0200
current-owner: janitor-main-session
task-type: audit
priority: low
severity: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [branch-protection, workflows, nested-layout]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-BH32A1A5, TRDD-H8WRCW0I]
---

# Does `.github/workflows/*` detection survive a nested repo layout

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-09-04

- **This card exists because its parent got FROZEN.** The question was recorded as a note in
  `TRDD-BH32A1A5`, on the reasoning that there was no evidence of a broken layout and the
  failure mode is degraded-but-safe — sound while that card was open. `BH32A1A5` then went
  terminal (`complete`), and **nobody sweeps frozen cards for open questions**. The board
  correctly reports it done; the question was not done. Hence a card of its own.
- **NOT a known defect.** Nothing has been observed failing. This is one specific,
  cheap-to-answer question, deliberately parked at `backburner` (genuinely deferred, not
  queued) where drift will resurface it.

## The question

`branch_protection_apply.py` gate 3 now resolves `project_root` from `CLAUDE_PROJECT_DIR`
(else the cwd) — `TRDD-BH32A1A5`, commit `e4dd674d`. That same root is then passed to
`bpl.baselines_content_current(slug, default_branch, project_root)`, which globs
`.github/workflows/*` under it via `detect_required_status_checks` to discover the CI job
ids that become `required_status_checks` contexts.

**The concern is an asymmetry with slug resolution, one layer up.** `detect_repo_slug` grew a
git-remote fallback precisely because manifest-only resolution failed on real layouts seen in
the wild (`TRDD-H8WRCW0I`): *"a repo nested under a workspace parent, a non-plugin project, a
manifest one level down"*. On a peer's host that produced `skip: cannot resolve owner/repo
slug` four times a day for days while the detector half filed real findings.

If the project root can be a level away from the repo root for **slug** purposes, it can be a
level away for **workflow** purposes too — and workflow detection has no equivalent fallback.
The slug would resolve (via the remote) while the workflow glob finds nothing.

## Why it is low severity

The failure is degraded, not wrong: `detect_required_status_checks` returning empty causes the
`required_status_checks` rule to be **OMITTED** from the payload entirely — GitHub 422s an
empty context list, so the code already declines to emit it. The result is a baseline applied
without a checks rule, not a baseline applied with the *wrong* checks. Nothing is written to
the wrong repo and no incorrect rule lands.

The upside case is the one that would have been dangerous, and it is already closed: under the
pre-`e4dd674d` ordering, a hook context would have globbed the JANITOR's own 7 workflow files
and applied *those* job ids as required checks on somebody else's repo.

## Acceptance criteria

- [ ] Determine whether any layout the janitor actually runs in has its `.github/workflows/`
      at a path other than `<project_root>/.github/workflows/` — a repo nested under a
      workspace parent being the specific case that broke slug resolution.
- [ ] If such a layout exists: decide whether workflow detection should walk to the git
      toplevel (matching where the slug's remote fallback resolves from), and record the
      decision. If none exists, record that and close — a fallback nobody needs is code nobody
      tests.
- [ ] Whichever way it goes, `detect_required_status_checks`' docstring states which root it
      expects and what happens when workflows are not under it.
