---
trdd-id: AGV84UGC
title: Secret shield URL password user part and its query and password loops are flagged as a regex denial of service shape
column: todo
status: tasked
created: 2026-11-14T22:28:32+0100
updated: 2026-11-15T03:49:46+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T22:28:32+0100
---

# Secret shield URL password user part and its query and password loops are flagged as a regex denial of service shape

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: read redactUrlPasswords and its guard walk (USER_RUN, MARK_AT, the colon it ends at) in hooks/secret-shield/patterns.ts, then build the rewrite below as one bounded change with differential tests against the old regex; re-run the scoped CPV skillaudit on hooks/secret-shield and confirm the findings at the URL_PASSWORD, QUERY and password-loop lines are gone. Tests only run before the push. Consult the Fable advisor first: the unrolling constraints (TRDD-HF7GNHNF, TRDD-AGOEWF2E) must not regress.
- Status: in progress (step 1 fa7294e2, step 2 a498ee6d). Blocks the CPV publish gate (v5.16.2 skillaudit) together with the JSON_OVER_BOUND card TRDD-MC895I0A. Related: archived TRDD-HF7GNHNF (URL_PASSWORD slowed between 96 KB and 128 KB), TRDD-AGOEWF2E (dev; very long URL password), TRDD-OD5Z90YL (plan; ReDoS harness).
2026-11-15 PROGRESS: research report reports_dev/sonnet-worker/20261115_023330+0100-agv84ugc-design-research.md (design: drop NOT_PASSWORD, QUERY and URL_PASSWORD; password = run up to PASSWORD_END; port skip via PORT_START /\d{1,5}[/?]/y and QUERY_STOP /[=\s@#]|:\/\//g, only under the bound; proxy scan: the only non-test finding is patterns.ts:66, the MC895I0A finding is gone). Step 1 DONE in fa7294e2: hooks/secret-shield/tests/url-password-walk.test.ts pins today's outputs (captured with Bun from the pre-change code; not yet run in the plugin engine; first run is the pre-push gate unless the owner allows dev runs of this one file, asked 2026-11-15, unanswered). NEXT ACTION: step 2, one worker applies the design to patterns.ts (constants, the :307-333 block, comments at :22-61, :70, :249, :278, :456, rules/code-hosts.ts:107, tests/patterns.test.ts:660), then scans the whole patched shield with the CPV scanner; the release also needs a finished tests/harness/redos_load_harness.py run (D8 cron waits for a quiet host).
2026-11-15 NEXT ACTION addendum: the step 2 worker also removes the stale 'Status: not started' bullet above, and adds one header line to tests/url-password-walk.test.ts saying the case 'an @ only after whitespace' was changed after capture and re-checked with Bun. The ReDoS load harness (TRDD-OD5Z90YL) runs in the pre-push gate on the rewritten code; its 2026-11-15 03:31 attempt on the old code aborted on load and judged nothing.
2026-11-15 03:42 STEP 2 DISPATCHED: one sonnet-worker is applying the design to patterns.ts, the comments in rules/code-hosts.ts and tests/patterns.test.ts, and one header line in tests/url-password-walk.test.ts; its report lands in reports_dev/sonnet-worker/*-agv84ugc-step2.md. Do NOT send a second writer to those files before that report is read. Correction to the addendum above: the main agent, not the step 2 worker, removes the stale 'Status: not started' bullet, after it accepts the diff. Coverage gap: url-password-walk.test.ts pins _a:// and .:// but no 1http://, a.b:// or uppercase-scheme case; that hasScheme accepts exactly what the removed lookbehind accepted rests on a code trace (ASCII), so add pinned cases for those three shapes before the pre-push run.
2026-11-15 03:48 STEP 2 DONE in a498ee6d: NOT_PASSWORD, QUERY and URL_PASSWORD are gone; redactUrlPasswords reads the password up to PASSWORD_END and the port skip with PORT_START and QUERY_STOP. Evidence on the applied code: parse (bun build --no-bundle) and the CPV scan (0 REGEX_DOS, 0 non-test findings; one minor CONTEXT_STUFFING finding in tests/url-password-walk.test.ts at the b://u:1? timing input, from step 1); the 0-diff differential belongs to the design and was not re-run on the applied code; the pinning tests first run in the pre-push gate. Correction to the 03:42 line: digit-first (1://, 9a://), plus, dot and hyphen schemes (a1+b.c-d://, -a://) were already pinned; only an upper-case scheme was not, and 'HTTPS:// is a scheme (upper case)' now pins it. NEXT ACTION: the release path (fast-forward main, owner confirms the in-flight commits, publish.py on main), with the ReDoS load campaign run by hand first (TRDD-OD5Z90YL).

## Finding

The CPV gate (skillaudit, REGEX_DOS, MINOR) flags hooks/secret-shield/patterns.ts line 66, the user part of URL_PASSWORD: `((?:NOT_USER|MARK_BODY)NOT_USER*(?:MARK_BODY NOT_USER*)*)`. It is linear (MARK_BODY starts with `[`, which NOT_USER excludes, so the parse is unique) and bounded by the URL guard, but it is a quantified group with an inner quantifier, the shape the scanner's TypeScript prover refuses by design. Lines 64 (QUERY: `[^\s@#:]*(?::(?!\/\/)[^\s@#:]*)*`) and 67 (the password loop `NOT_PASSWORD*(?::(?!\/\/)NOT_PASSWORD*)*`) carry the same group-with-inner-quantifier shape and escape only the line matcher (the `(?!\/\/)` breaks it); one card covers all three. Moving the source or hiding it behind an identifier would silence the line matcher with the compiled regex unchanged: a workaround, not a fix, so NOT done. The gate still blocks on line 66.

The user part interleaves NOT_USER runs and markers; no regex without nesting exists for it except a per-character group loop, which hits the engine iteration ceilings that the unrolling in TRDD-HF7GNHNF and TRDD-AGOEWF2E avoids.

## Design

Card design from the read-only check of redactUrlPasswords: the guard already walks the user part with USER_RUN and MARK_AT (the same grammar) and ends at `colon`. The regex can therefore start sticky (flag y) at that colon, with the user part sliced from the walk, which drops the user loop from the regex entirely. Then handle the QUERY loop (line 64) and the password loop (line 67) the same way, or prove them linear by an unrolled form the prover accepts. Byte-identical behaviour is required: dump TOKEN_ORDER (kind, source, flags of all TOKENS) with bun before and after and compare with cmp where the regex source is unchanged, and write differential tests (old regex versus new walk plus sticky regex) over user parts with markers, ports followed by paths and queries, passwords containing colons, passwords over the colon bound, and placeholder and marker-only passwords.

Gates after the change: scoped skillaudit as in ced9f0db (CPV 5.16.2 run_skillaudit_scan_files over the 18 hooks/secret-shield .ts and .md files; after ced9f0db: 2 non-test findings plus 28 in tests/); scripts/run_secret_shield_tests.py (845 pass, floor 800 at that commit); the mutation-check pattern used in ced9f0db (scratch copies outside the tree, claude plugin test).

Alternatives (not applied): the CPV audit-consent sentinel comment (turns the finding into a non-blocking WARNING; misleading on the shield's own code) and an upstream CPV issue for a TypeScript discriminator for such a group. See the JSON_OVER_BOUND card for the wording.

## Approval log

- 2026-11-14T22:28:32+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
