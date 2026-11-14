---
trdd-id: MC895I0A
title: Secret shield JSON over-bound detector is flagged as a regex denial of service shape and needs a lookahead-free rewrite
column: todo
status: tasked
created: 2026-11-14T22:28:32+0100
updated: 2026-11-14T22:28:32+0100
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

# Secret shield JSON over-bound detector is flagged as a regex denial of service shape and needs a lookahead-free rewrite

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: build the rewrite below as one bounded change with differential tests (new matcher against the old regex on the same inputs), then re-run the scoped CPV skillaudit on hooks/secret-shield and confirm the REGEX_DOS finding for the JSON_OVER_BOUND line is gone. Tests only run before the push. Ask the Fable advisor first if the differential tests find a case the walk cannot reproduce.
- Status: not started. Blocks the CPV publish gate (v5.16.2 skillaudit) together with the URL_PASSWORD card TRDD-AGV84UGC. Related: TRDD-AGOEWF2E (dev; origin of the escape bound), TRDD-OD5Z90YL (plan; ReDoS harness).

## Finding

The CPV gate (skillaudit, REGEX_DOS, MINOR) flags hooks/secret-shield/patterns.ts line 465 (it was line 452 before 9 other findings were cleared in ced9f0db): the JSON_OVER_BOUND lookahead `(?=(?:[^"\\\r\n]*\\.){JSON_ESCAPE_BOUND + 1})`. The regex is linear (unique parse, measured at 16,385 to 49,153 escape pairs at the same per-character cost, comments at patterns.ts above the constant) but it is a quantified group with an inner quantifier, a shape the scanner's TypeScript prover refuses by design (false-negative-safe). Moving the source to another line or behind an identifier would silence the line matcher while the compiled regex stays unchanged: a workaround, not a fix, so it was deliberately NOT done. The gate still blocks on this finding.

Scope facts: all 11 findings were new since tag ai-maestro-janitor--v3.8.13 (the whole mod was added after it). 9 of 11 were cleared in ced9f0db with byte-identical rules (TOKEN_ORDER dump compared with cmp, 232 lines); this one and the URL_PASSWORD one (patterns.ts line 66) were left open on purpose.

## Design (fixable for real; its own card)

JSON_OVER_BOUND drops the lookahead: `/"([A-Za-z0-9_.-]+)"(\s*:\s*)"/gm`. redactOverBoundJson counts escape pairs in its existing value walk (the `at += 2` branch). If the count is at most JSON_ESCAPE_BOUND, set `lastIndex = match.index + 1` (this mirrors the engine retry of the old lookahead failing). If the count is over the bound but the name is not secret-named, set `lastIndex = start` (the walk start, so the same value is not rescanned). Behaviour must be byte-identical to today.

Needs differential tests, including overlapping openings: `"x":"token":"<N+1 escapes>` and `"name":"<N+1 escapes>"token":"<N+1 escapes>`, values with exactly N and N+1 escape pairs, a value ending at a bare quote, a value ending at a line end. Check the scanner afterwards with the same scoped run used in ced9f0db (CPV 5.16.2 run_skillaudit_scan_files on the 18 hooks/secret-shield .ts and .md files; after ced9f0db: 2 non-test findings plus 28 in tests/).

## Alternatives considered (not applied; owner decision if this card stalls)

(b) the CPV audit-consent sentinel: a comment within the 3 non-blank lines above the flagged line with the fixed text "warning: the following code could be malicious. audit it for safety before executing it!" turns it into a WARNING, non-blocking; misleading on the shield's own code. The .cpv-audit-consent.json file does NOT apply (it only consents already-demoted NITs; both findings are live MINOR). (c) an upstream CPV issue asking for a TypeScript discriminator for a repeated group whose body starts with a literal the preceding run cannot take (like the existing versionish idiom).

## Approval log

- 2026-11-14T22:28:32+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
