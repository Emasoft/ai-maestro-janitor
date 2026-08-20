---
trdd-id: KDLJ04AM
title: github-config audit emits NO_PR_REVIEW unconditionally while the payload builder emits pull_request conditionally
column: testing
created: 2026-08-20T08:25:18+0200
updated: 2026-08-20T09:05:00+0200
implementation-commits: [98a38760]
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [janitor#283, TRDD-VR0E17Q0 (maintainer), 36f05aac]
npt: []
eht: []
---

# NO_PR_REVIEW false positive on solo-owner repos (janitor#283, hub-filed, VERIFIED here)

## Verified first-hand 2026-08-20 08:20

- `scripts/lib/github_config_audit.py:195-197`: NO_PR_REVIEW fires whenever `pull_request`
  is absent from the branch rules (only the janitor#244 unresolved-guard gates it).
  `require_pull_request` appears **0** times in that file.
- `scripts/lib/branch_protection_lib.py`: `require_pull_request_for` appears **5** times —
  since commit 36f05aac the BUILDER emits the `pull_request` rule CONDITIONALLY (USER
  Tier-3 ruling 2026-08-13: GitHub forbids self-approval, so the rule is omitted where a
  PR reviews nothing).
- Sharp edge confirmed: `scripts/github_config_fix.py:65` lists NO_PR_REVIEW as FIXABLE —
  a fixer acting on the false finding would RE-IMPOSE the rule the ruling removed, Tier-0
  EXEMPT while doing it. Live instance: Emasoft/ai-maestro-maintainer-agent (their
  GHCFG-001 / TRDD-VR0E17Q0).

## What

1. The audit consults the SAME predicate as the builder: emit NO_PR_REVIEW only when
   `branch_protection_lib.require_pull_request_for(slug)` says the repo SHOULD carry the
   rule. One SSOT — never a second copy of the ruling.
2. The hub's fixture ask: a solo-owned repo with no `pull_request` rule must produce NO
   finding (and the fix path must therefore never fire) — a test that FAILS on today's
   code.
3. Sweep: any other finding class in the audit that hard-codes a rule the SSOT emits
   conditionally (check NO_REQUIRED_CHECKS's has_workflows gate is the right analogue —
   it already conditions; NO_PR_REVIEW is the odd one out).
4. INTERIM (already honoured): NO_PR_REVIEW findings on solo-owner repos are suspect —
   no auto-fix until this lands.

## Acceptance

- [ ] solo-owner repo, no pull_request rule ⇒ zero findings (test fails pre-fix)
- [ ] repo where require_pull_request_for is True and rule absent ⇒ finding still fires
- [ ] grep-proven single predicate (audit imports the builder's, no copy)
- [ ] pytest, ruff, mypy clean; janitor#283 closed with the commit

## Approval log

- 2026-08-20T09:05:00+0200 — SHIPPED (todo → testing) by janitor-main-session. All four acceptance boxes met (fixture fails-pre-fix proven via single-path stash; falsification pair; gatherer carries both predicate answers; suite green with one isolated-pass load flake). janitor#283 commented + closed (98a38760). Gate to complete: rides 3.3.19; the three held fleet GHCFG tickets self-clear on the installed line.
