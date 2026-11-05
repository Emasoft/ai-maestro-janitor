---
trdd-id: T36Z4ACR
title: A publish gate runs the secret-shield TS suite
column: todo
status: tasked
created: 2026-11-05T02:01:56+0100
updated: 2026-11-05T05:26:48+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-05T02:01:56+0100
---

# A publish gate runs the secret-shield TS suite

## Problem
No automated gate runs the secret-shield TypeScript suite. scripts/publish.py stage_tests (publish.py:1829-1871) runs pytest only; no .github workflow calls claude plugin test; no pytest test runs it (tests/test_publish_lock_guard.py:211 only mentions plugin test code in a docstring); and nothing type-checks hooks/ (carried from earlier reports, not re-measured). Every shield family so far (d711e5f8, dbd5aaf9, 28b42512) was proven only by hand in a scratch plugin shell.

## Done when
 - [ ] publish.py gains its own stage, run right after stage_tests and before _reassert_publish_lock (or followed by a fresh re-assert), that fails the publish when the secret-shield TS suite fails: the TS suite also runs plugin test code with write access, and a test once deleted the publish lock. It is a publish.py stage, not a pytest test, so CI runners without a claude CLI are not affected by Done-when 3.
 - [ ] The stage builds a faithful shell: the real .claude-plugin/plugin.json, hooks/secret-shield/ copied, and a hooks.json listing ./secret-shield/register.ts until TRDD-2V7OAUPE wires the module.
 - [ ] It runs claude plugin test and requires exit 0 with 0 fail; a missing claude CLI fails the stage instead of skipping it.
 - [ ] CI parity is decided and written down on this card: either a CI job installs the claude CLI and runs the suite, or the card states why CI does not run it.
 - [ ] Proof that gets past stage_check_clean: in a scratch clone or branch with one deliberately failing TS test committed (or by calling the new stage function directly on such a tree), the publish stops at the new stage, and the block message is that stage's own.

## Related
TRDD-2V7OAUPE (wiring the shield), TRDD-Q6LPJTPO (the token families), TRDD-6FB7PKU2 (interim hand-run box).

## Approval log

- 2026-11-05T02:01:56+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

 - 2026-11-05 — Scope and risks: type-checking hooks/ is out of scope here; it gets its own card if wanted. The change edits publish.py, the release pipeline: consult the advisor first (CLAUDE.md), and check whether publish.py comes from a CPV template that a re-standardize would overwrite, since that decides where the stage must live. "No pytest test runs the suite" rests on one grep over tests/ for the pattern plugin test|.test.ts|"plugin", *"test" (hits: the docstring at tests/test_publish_lock_guard.py:211, the KNOWN-MISSES name-sync test, bench corpora); five test files that call claude were not read.
 - 2026-11-05 — Checked after the review of 5e71b67e: the lock deletion is documented in the _reassert_publish_lock docstring (scripts/publish.py:3305; a test wrote a lock at the real repo root and unlinked it, fixed in a52d5195) and in tests/test_publish_lock_guard.py:211. The re-assert warns and re-arms the lock and never fails the publish, so a stage before it is covered by the re-arm and a stage after it is not. The call sits at scripts/publish.py:3702, right after stage_tests; Done-when 1 is checked by reading that flow. Unmeasured: whether a secret-shield TS test can write files at all; the hand run's shell lives under /tmp, outside the repo. The ordering is cheap insurance, not a response to a measured risk.
 - 2026-11-05 — Correction to the note above and to the commit message of 16b9a4d7 (review of 16b9a4d7): the plugin copies built for hand runs so far live under scripts_dev/secret-mining/ inside the working tree of the repo (gitignored), not under /tmp; cd /tmp only sets the working directory, and no shell location limits what a test can write by absolute path. Where the future stage builds its shell is undecided. "Covered by the re-arm" was too strong: the re-assert restores a deleted lock for the stages after it and does not protect the TS stage while it runs; a lock left naming a live foreign pid is kept, not re-armed. The line numbers above will drift: the call is the _reassert_publish_lock call in the main flow of publish.py, just after stage_tests. a52d5195 verified: it exists, subject "fix(tests): the publish-lock test no longer DELETES the live lock mid-publish".
- 2026-11-05 — The ratio timing tests of the TS suite are load-sensitive on this host: on b3363706, 1 run in 3 failed the grown-URL ratio test (a path that change did not touch) under a sustained load of about 215-233 (5-minute average). The stage must decide how a timing failure is handled, for example re-running only the failed timing tests once and recording the load, and must never turn a real failure into a pass.
