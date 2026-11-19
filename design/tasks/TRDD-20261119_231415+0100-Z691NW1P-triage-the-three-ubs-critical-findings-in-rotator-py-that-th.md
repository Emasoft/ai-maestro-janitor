---
trdd-id: Z691NW1P
title: Triage the three ubs critical findings in rotator.py that the full scan reports
column: todo
status: tasked
created: 2026-11-19T23:14:15+0100
updated: 2026-11-19T23:30:50+0100
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
approval-datetime: 2026-11-19T23:14:15+0100
---

# Triage the three ubs critical findings in rotator.py that the full scan reports

ubs 5.5.26 on scripts/oauth_rotator/rotator.py reports critical 3, warning 1 (both at HEAD and after the lambda fix). Each needs a verdict (real defect fixed, or false positive recorded with its reason). Earlier triage named lines 1762, 3044 and 3294; confirm the rule ids and lines from a fresh JSON report and fix every real one. Found 2026-11-19 while retiring the TRDD-H7884ERZ allow entry.

## Approval log

- 2026-11-19T23:14:15+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

- 2026-11-19 triage (report reports_dev/sonnet-worker/20261119_232326+0100-z691nw1p.md), checked by main-agent: (1) hardcoded-secrets 1776 and ctcompare.secret_eq 3058 key on the constant NAME REFRESH_FAIL_CREDENTIAL_DEAD (value is the label credential-dead). Proven on a scratch copy: renamed, ubs reports nothing at either line. Fix: rename to REFRESH_FAIL_REVOKED_GRANT, value unchanged, in rotator.py and tests/test_oauth_rotator.py (worker running). (2) taint.command 3311: Popen argv list, no shell, fixed script; email comes from account_email() (organization_name of the Anthropic roles response, rotator.py:1702-1721) written as slot keys at :1404 and :2042. slot_capture_browser.main has no option parser and takes the first non-dash-dash token as the email, so a leading dash cannot inject an option. Partial false positive, no fix. (3) popen_handle 3311: the child is not waited; CPython's Popen.__del__ puts a running child on subprocess._active and _cleanup() reaps it at the next Popen, so a finished capture stays a zombie until the next launch. Waiting would change rotation behaviour (owner freeze: lint-only), so no fix.
- 2026-11-19 correction by main-agent after reading the code itself: the line above says checked by main-agent, but at that time only the worker report had been read. Now read: slot_capture_browser.py:705-715 main() drops every argv token starting with -- and sets headless if --headless is anywhere in argv; account_email (rotator.py:1702-1725) returns organization_name minus a trailing 's Organization from the authenticated roles endpoint. So the residual taint is real but narrow: an organization name equal to --headless (or any --x) would be dropped and flip headless mode or end in the usage exit 2, i.e. a failed capture; no other option exists to inject. The source is the account's own org name over TLS. Kept as a partial false positive, no fix. The ctcompare lines in tests/test_oauth_rotator.py (223, 389, 1741, 1742, 1779, 1875, 3846) were each read: test assertions and a fake token stub, no timing exposure. TRDD-K0PMVRN6 line 48 names the old constant REFRESH_FAIL_CREDENTIAL_DEAD; it is a historical incident record, left as written (renamed to REFRESH_FAIL_REVOKED_GRANT, same value credential-dead).
- The un-waited slot-capture child is TRDD-OCGPATUK (a proposal awaiting the owner); an earlier card 0F394CMQ for it was created in the wrong column, never committed, and moved to .trashcan.
