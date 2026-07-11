---
trdd-id: EG2HSPMQ
title: SessionStart hook died on import for three weeks — rules stopped installing
column: complete
created: 2026-07-11T20:03:59+0200
updated: 2026-07-11T20:03:59+0200
current-owner: janitor-session
assignee: janitor-session
priority: 0
severity: HIGH
effort: S
labels: [hooks, rules, silent-failure, guardrail]
task-type: bugfix
parent-trdd: null
npt: []
eht: []
blocked-by: []
supersedes: []
superseded-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, integration]
audit-requirements: []
review-requirements: []
runtime-targets: [macos, linux]
impacts: [install-script]
attempts: 1
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-11T20:00:00+0200
implementation-commits: [b28c53a]
external-refs: ["https://github.com/Emasoft/ai-maestro-janitor/issues/84"]
---

# SessionStart hook died on import for three weeks — rules stopped installing

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-11

**FIXED and tested (`b28c53a`). Not yet published — the fix reaches no machine until a
release ships.**

- Root cause, fix, and the guardrail are all landed. Full suite green (12,535 passed).
- **The one thing still outstanding is the PUBLISH**, which is user-gated. Until then this
  machine's `~/.claude/rules/` stays frozen at its 2026-06-22 state and the USER-memory
  backup mirror stays unsynced.
- Do NOT "fix" this by hand-running the hook against the cached v0.39.0 plugin: that would
  install the OLD (pre-slimming) rules and make the context floor *larger*. The correct
  sequence is publish → the new version is cached → the next SessionStart installs the
  canonical rules.

## What happened

`on-session-start.py` raised `ModuleNotFoundError: No module named 'state'` at IMPORT time on
every session from **2026-06-20** (`4df60fc`) until **2026-07-11**. It never executed a single
statement for three weeks.

```
on-session-start.py:140   from lib import global_state
  → scripts/lib/global_state.py:34   import state
     ModuleNotFoundError: No module named 'state'
```

## Why (a collision of two import conventions)

| caller | sys.path | import form | a lib module's bare `import state` |
|---|---|---|---|
| detectors, `dispatch.py` | `scripts/lib/` | `import global_state` | resolves ✅ |
| `on-session-start.py` | `scripts/` only | `from lib import global_state` | **fails** ❌ |

`global_state.py` has bare-imported its sibling `state` since the daemon landed — safe under
the detector convention. `4df60fc` made the hook import it via the `lib` package, where that
same absolute import has nothing to resolve against. **Neither change is wrong on its own.**

Leaving `scripts/lib/` off the path was *deliberate* — a comment explained it satisfies the
CPV hook validator's local-sibling detector — which made a load-bearing line read as a style
choice. The fix is additive: keep the package form the validator wants, and add the path the
sibling import needs.

## Why it went unnoticed for three weeks — the part that matters

Claude Code does not surface a SessionStart hook crash. And this hook's entire job is things
whose **absence is invisible**:

- **Rules stopped installing.** All 8 shipped rules froze at their pre-2026-06-22 versions.
  `universal-kanban.md` was added *after* the hook died, so it was never installed once — the
  kanban pillar's rule has loaded in **zero sessions** on this machine.
- The rules' on-demand reference docs stopped shipping.
- The SessionStart memory breadcrumb stopped printing.
- **The USER-memory backup mirror — the copy that survives an uninstall — stopped syncing.**

Nothing was overwriting the rules because *nothing was running*. A bug that produces only
absences generates no error, no failing test, and no user complaint.

It was found only because the ai-maestro Claude, working from the OUTSIDE, noticed two of the
symptoms (janitor#84) and reported them — with a plausible but wrong diagnosis (it blamed
marker-gating in the installer). The installer is fine: it byte-compares and overwrites, and
installs all 8 rules correctly when it is actually reached.

## The guardrail (the real deliverable)

The unit tests could never have caught this: they import the libs **directly**, which is the
convention that works. Only running a hook the way Claude Code runs it reproduces the crash.

`tests/test_hooks_execute.py` now EXECUTES every hook as a subprocess (real `uv`, real stdin,
sandboxed HOME) and asserts no import-time death. Hooks are discovered by glob, so a new hook
is covered the day it lands. Plus an outcome test pinned to this incident: after
`on-session-start` runs, the shipped rules must actually be on disk — so a future regression
that reaches the hook but not `install_rules` also fails loudly.

## Notes and lessons learned

[^1]: [ocd:2026-07-11 lmd:2026-07-11] **A test that imports a module does not test the module
  as it is actually loaded.** Every lib here was well unit-tested, and the suite was green the
  whole three weeks — because the tests use the import convention that works. The failure lived
  entirely in the *loading*, which only the real entry point exercises. Lesson: for anything
  with an entry point (hook, CLI, plugin callback), at least one test must invoke it THE WAY
  THE PLATFORM DOES — as a subprocess, with the platform's env and stdin. Import-level tests
  cannot see an import-level bug.

[^2]: [ocd:2026-07-11 lmd:2026-07-11] **A component whose only output is an absence needs a
  liveness signal, not just correctness tests.** This hook's work is invisible when it
  succeeds *and* when it fails; the two states are indistinguishable from the outside. Its own
  log stopping dead on 2026-06-22 was the sole evidence, and nobody reads a quiet log. Where a
  component's success is silent, either make its failure loud or assert its OUTCOME
  periodically — otherwise "it stopped running" is a state the system cannot report.

[^3]: [ocd:2026-07-11 lmd:2026-07-11] **The outside reporter was right about the symptoms and
  wrong about the cause — and both halves were valuable.** #84's diagnosis (marker-gating)
  would have led to "fixing" a correct installer. Taking the *observations* seriously while
  re-deriving the *cause* from scratch is what found it. Treat an external bug report as
  evidence, never as a diagnosis: the reporter can see what you cannot (your absences), but
  you can see what they cannot (your code).
