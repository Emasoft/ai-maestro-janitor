---
trdd-id: NRF7OJ5H
title: Janitor consumes the report-sanitizer core as a vendored copy
column: todo
status: tasked
created: 2026-11-16T01:25:36+0100
updated: 2026-11-18T09:49:13+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T01:25:36+0100
---

# Janitor consumes the report-sanitizer core as a vendored copy

## STATE — 2026-11-16
- NEXT ACTION: Scope 2 (the CI pin bump) waits on the owner: report-sanitizer main is 16 commits ahead of its origin (git rev-list --count origin/main..main, 2026-11-16 07:23) and pushing it is the owner's call. The current pin 16c9a12 still installs the standalone single-file tool, and the last CI run on main (e38fde00, release 3.9.4) passed with it; the commits after e38fde00 have not run in CI yet. Scope 3 and 4 are not started. report-sanitizer's merge (its card ZADXHV6W) is closed and its core/ is pinned to janitor 9dcaa0a3 (its commit fb4320d).
- 2026-11-16 (main agent): report-sanitizer feat/shield-core (TRDD-ZADXHV6W there) is merged into its main; the tool now spawns bun for every redaction. Janitor consequences: (1) tests/test_redact_staged_reports.py needed `bun` in its real_subprocess markers, or the sandbox guard (tests/sandbox_guard.py:703) blocks the spawn and 2 of 5 tests fail; added in the same commit as this line. (2) The CI step "Install sanitize-reports (pinned)" (ci.yml, SANITIZER_SHA 16c9a12) fetches ONE raw file; a pin bump past the merge must fetch the whole tree (core/, shield_bridge.ts) and install bun, or every real run exits 4. (3) Done: the shield hides dckr_pat_/dckr_oat_ tokens, Maven <password>/<passphrase> literals and npmrc :_authToken literals since 9dcaa0a3, and report-sanitizer dropped its Python copies of those three rules in its fb4320d.
- 2026-11-16 scope 3 re-scoped (main agent, checked this day): (1) it waits behind scope 2, because the report-sanitizer --stdin filter mode is commit 70217f5, which is not on report-sanitizer origin/main (git merge-base --is-ancestor 70217f5 origin/main exits 1), and janitor CI installs pin 16c9a12, so any janitor code calling --stdin would pass locally and fail in CI; (2) _SECRET_SHAPE_RE in scripts/detectors/memory-scope-leak.py is not a redactor but a per-token test inside two conditions (lines 362 and 373), so it leaves scope 3; (3) _masked_stderr_tail in scripts/daemon.py also logs the rotator tick's stderr (line 954), so changing it is under the rotator freeze, and its other caller is the workload retry log (line 611). Scope 3 is now only jev_shadow_log._redact_text, and the preferred route is the one scope 4 names: generate the Python patterns from the core instead of spawning the CLI, which would add bun and an undeclared tool as runtime needs of the published plugin.
- 2026-11-16 the 62 advisory UBS criticals on 9dcaa0a3 (pre-commit report, kept in the gitignored reports_dev/ubs/9dcaa0a3-precommit-ubs.json) are all in hooks/secret-shield/tests/patterns.test.ts and known-misses.test.ts: 39 hardcoded-secrets, 18 unsafe-secret-compare, 4 loose-equality, 1 sensitive-log. Every hardcoded-secrets line was read: the long literals are test names, [JANITOR_REDACTED:...] placeholders, env-var names, or fixtures already split into concatenated pieces or built by fake()/repeat(), so no live secret-shaped literal exists; the compare hits are expect(a === b) assertions. No change, no suppression added.
- 2026-11-16 CORRECTION of the line above: 'every hardcoded-secrets line was read' overstated it (7 lines were displayed). Replacing evidence: a full scan of both test files as of 9dcaa0a3 (patterns.test.ts unchanged since) found no provider-prefixed token inside one literal except an inert two-segment JWT-shaped fragment made of alphabet letters (patterns.test.ts:2427); its 137 high-entropy runs are bodies without a provider prefix that the tests join to their prefix at runtime. All 18 compare hits were listed: each is an expect() assertion or a redaction-output comparison (indexOf, === on redacted text), none an authentication check. The report is the pre-commit run on HEAD 67fbc0e3, the parent of 9dcaa0a3, files 3 (patterns.ts is in .ubsignore); its 05:31:57 time is two minutes after the commit's 05:29:57 date, unexplained.
- 2026-11-16 SCOPE of the two UBS lines above (supersedes their wording): the high-entropy runs are 65 in patterns.test.ts and 72 in known-misses.test.ts. All are without a provider prefix. In patterns.test.ts the bodies are joined to their prefix at runtime (j(...)); the known-misses fixtures are bare fakes on purpose (for example a 40-hex value passed to fake(), which returns it unchanged and only enforces uniqueness). The scan was per line, over quoted literals, with a listed prefix set (ghp_, github_pat_, AKIA, ASIA, sk-ant-, xox*-, glpat-, dckr_pat_, npm_, AIza, ya29., JWT eyJ.eyJ, PEM private key, hf_, pypi-AgE, Stripe and others), so multi-line templates and unlisted prefixes are not covered. Conclusion at that scope: no provider-prefixed secret literal, and the 62 advisories need no change.
- 2026-11-18 (main agent), provisional decision on the direction of the shared core and the scanner: the janitor stays the source of hooks/secret-shield and of scripts/shield_scan, and report-sanitizer vendors both byte for byte (option B of the merge plan, report-sanitizer reports_dev/cheap-worker/rs-merge-plan/20261118_090934+0100-plan.md, gitignored). Basis: no owner quote names an owner for the core (a worker extract of L1I0FP5T, reports_dev/fast-worker/l1i0fp5t-extract/20261118_094403+0100-report-v2.md, whose reading method the main agent did not check), and report-sanitizer already re-pins its core to janitor commits (L1I0FP5T STATE: 953ec92, bdcfc10, b8d9224). This defers scope 4 of this card (report-sanitizer as upstream); it does not cancel it. Open blocker D2: scan.ts reads .claude-plugin/plugin.json for plugin_version, which report-sanitizer lacks, so a byte-identical scan.ts exits 2 there; the route is decided when the merge starts (a janitor-side change of the version source is preferred over a local patch).
## Scope
1. hooks/secret-shield/{patterns.ts,rules/} become a vendored copy of report-sanitizer core/, pinned by hash, with a test.
2. CI install: .github/workflows/ci.yml:108-123 fetches sanitize_reports.py as one raw file pinned by SHA; after the swap the tool needs its core/ folder and bun, so CI installs bun and checks out the repo at a pinned commit.
3. The Python mini-redactors (scripts/lib/jev_shadow_log.py _redact_text, scripts/detectors/memory-scope-leak.py _SECRET_SHAPE_RE, scripts/daemon.py _masked_stderr_tail after checking what it serves) move to the CLI filter mode, one commit each. scripts/lib/oauth_rotator/reauth.py is excluded: rotator freeze (owner, 2026-11-05).
4. Upstream flip: report-sanitizer becomes upstream; scripts/lib/secret_names.py is generated from the core.
## Why
Owner goal 2026-11-15 (verbatim): "complete and improve the `~/Code/report-sanitizer` project, merging into it the secrets-shield code of the scanner, to create a powerful universal scanner and redactor."

## Approval log

- 2026-11-16T01:25:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T04:58:34+0100 — column → todo. holds three live obligations after the 3.9.4 sanitizer swap

## Progress

2026-11-16: a re-probe of the live shield confirmed three gaps (bare dckr_pat_/dckr_oat_ tokens, Maven <password>/<passphrase> values, scoped npmrc :_authToken values without the npm_ prefix); the upstream rules are being written by the shield-gaps worker.
2026-11-16: 9dcaa0a3 adds the three shield rules (rules/dev-services.ts: dockerPat, npmrcAuthToken, xmlPassword); dockerPat joins the led list in tests/known-misses.test.ts. report-sanitizer fb4320d re-pins core/ to 9dcaa0a3 and removes its Python copies of the three rules, counting xml-password and npmrc-auth-token as cred. sanitize-reports on this host is a symlink to report-sanitizer main's sanitize_reports.py (clean at fb4320d), and it redacted each of the three probe lines. Timing, measured only: a scratch A/B with the main agent's own timing script, on the GitLab cookie shapes only, at load 124-156, failed "dense names with a value between" in 9 of 11 runs on both 9dcaa0a3^ and 9dcaa0a3, and "32-hex runs with no name" in 1 of 11 on the base and 0 of 11 on the new code. Five runs of the secret-shield mod on 9dcaa0a3 at load 96-115, with the main agent's own UBS scan (7 GB) running alongside, failed 3 of 5, on seven different timing tests in patterns.test.ts and url-password-walk.test.ts; the base was not run at that load. Whether the new rules shift those ratios is not established; the publish gate G3b needs one passing run on a quiet host (TRDD-Z41A13XV). UBS on 9dcaa0a3 is not settled: the commit hook reported 62 advisory criticals, and two re-scans were stopped when the UBS JS scanner grew past 3 GB.
2026-11-16 (main agent) Scope 3 is blocked on the same owner decision as Scope 2: sanitize-reports --stdin exists only in the report-sanitizer repo (commit 70217f5, 16 commits ahead of its origin, not pushed), and on this host the sanitize-reports command is a symlink into that local checkout. A janitor release that calls --stdin would fail on every machine without that checkout, so Scope 3 waits until the report-sanitizer push is decided.
