---
trdd-id: SWQXCIOS
title: Bandit is clean under the CPV canonical config with no suppression
column: todo
status: tasked
created: 2026-11-18T06:19:20+0100
updated: 2026-11-18T07:06:56+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T06:19:20+0100
parent-trdd: BAQB9SYO
---

# Bandit is clean under the CPV canonical config with no suppression

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-18

- Measured 2026-11-18 by main-agent: bandit with the CPV canonical .bandit.yml (gen_bandit_yml of CPV v5.23.1: skips B404 and B603, and B101 in test files only) over the 1267 Python files the CPV ci-preflight feeds bandit gives 779 findings in 269 files: B607 372 (231 in tests, 141 runtime), B108 189 (all tests), B110 126, B105 49, B101 13 (11 runtime), B112 6, B608 6, B613 5 (HIGH, tests), B311 5, B604 3, B606 2, B102 2, B605 1. The per-file list is a local scratch file of that run, not in the repo.
- NEXT ACTION: commit .bandit.yml byte-identical to gen_bandit_yml; pilot the B607 helper in three contexts (a hyphen-named detector, a hook, a test file); measure the cost of one pilot unit; then fan out by lane.
- Disclosure, 2026-11-18T06:25:00+0100, by main-agent: two parts of this plan satisfy the CPV gate without hardening anything, and the owner may rule on them together with the jev_compaction.py nosec. The canonical .bandit.yml skips B404 and B603 for every file and B101 in test files (CPV-authored and drift-checked, so a plugin cannot change it). The B607 helper returns shutil.which(name) or name; its canon docstring says it does not change security and only keeps the bare name out of the call. "No suppression" in the title means no marker added by this card, not that these two are hardening.
- Correction and step 1 done, 2026-11-18T07:06:00+0100, by main-agent: c38eddcd adds .bandit.yml, byte-identical to gen_bandit_yml of the installed CPV 5.23.1 (cmp equal, sha256 0d0d65d6...289a2, checked by main-agent). Its commit message says that without the file "the local gate and CI judged different rule sets"; that is wrong for this repo: no workflow under .github/workflows runs Mega-Linter or bandit, and .mega-linter.yml states that it is dormant (TRDD-6SIY2VX2). What reads .bandit.yml here is the CPV ci-preflight that publish.py runs (cpv_ci_preflight.py:1134 passes -c .bandit.yml when the file exists) and the CPV canonical-pipeline drift check (validate_plugin.py:7675 lists the file). The commit stands; this line corrects its stated reason. NEXT ACTION: pilot the B607 helper in three contexts (a hyphen-named detector, a hook, a test file), measure the cost of one pilot unit, then fan out by lane.

Parent: TRDD-BAQB9SYO (publish route A: fix every finding in code; no nosec, skip or ignore marker; a site that cannot be fixed without one goes to the owner).

## Lanes

- Mechanical, no behaviour change (B607, B613, B101, B311, B608): cheap workers, bandit 0 on each file plus that file test run.
- Behavioural (B110, B112: 132 sites, mostly hooks, daemon and rotator): each edit changes what is swallowed. Sonnet workers, one stated reason per site in the report, the diff read by main-agent. Pilot one hook and scripts/daemon.py first.
- Classify first (B108, B105): a split literal or a renamed variable is not a fix. Each site is classified (a fake path or value in a test, a real temp-file use, a word that only looks like a password) before any edit.

## Rules for every worker

- B607 helper: canon semantics exactly, shutil.which(name) or name, called at the use site, never as a module-level constant (PATH-patching tests would see a stale value, and a module-level call to a local function is the shape that tripped the ubs step limit on publish.py).
- Banned shapes, each measured to clear B110 or B112 without changing anything: except BaseException in place of except Exception; a tuple that holds Exception or BaseException; a body of ..., a string, del exc, or return None whose only purpose is to clear the rule. A narrowed except names the exceptions the try body can raise, read from the called code; a deliberate broad catch gets a body that does real work (a fixed-text stderr line, a counter, a re-raise).
- After each batch, main-agent greps its diff for the banned shapes and for split /tmp literals. Commit per batch, so one ubs exit 2 blocks one batch.
- Single test files only; the full suite runs once before the publish.

## Known sites

- scripts/lib/jev_compaction.py:1188 already carries "# nosec B108" on tmp_root = "/tmp" (llm-ext reads input only under /tmp, the home folder or the working folder, TRDD-2GCJ5D3M). It is a suppression under the owner rule and goes to the owner; the 43 B108 sites of tests/test_jev_compaction.py are classified against it first.
- tests/test_hook_fail_open_guard.py pins the shell wrapper hooks/hook-run.sh only; it pins no except clause in a hook body.
- scripts/publish.py (B607 29, B101 1) and scripts/lib/transcript_redact.py (B101 1, fixed by the step 3 lane switch of TRDD-BAQB9SYO) are handled in their own commits, outside the fan-out.

## Acceptance

- [x] .bandit.yml committed, byte-identical to gen_bandit_yml at the CPV pin (evidence: c38eddcd; cmp equal and sha256 0d0d65d6...289a2 against gen_bandit_yml of the installed CPV 5.23.1, checked by main-agent)
- [ ] bandit with that config exits 0 over the ci-preflight file list
- [ ] no nosec, skip or ignore marker added; the jev_compaction.py nosec decided by the owner
- [ ] ci-preflight passes on a fresh clone

## Approval log

- 2026-11-18T06:19:20+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
