---
trdd-id: DMH25CYD
title: Compact hold reports its selected waiting signal and conditional expiry
column: complete
status: archived
created: 2026-10-13T23:06:59+0200
updated: 2026-10-18T04:18:20+0200
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
approval-datetime: 2026-10-13T23:06:59+0200
relevant-rules: [5, 6]
implementation-commits: [0e131aa8, 815acb25]
---

# Compact hold reports its selected waiting signal and conditional expiry

## Task

Resolve GitHub issue #340 with diagnostics only. Preserve waiting predicate order, clocks, recovery guards, daemon-coverage exemption and every safety veto including --force restrictions. Evaluate the shared waiting evidence once; retain the boolean interface for existing callers. Report the selected blocking signal and its known conditional expiry in manual verdict output, not raw directives or agent identifiers. Recovery flags have unknown time-based expiry. A selected signal expiry does not guarantee the entire hold ends. Explain the 30-minute timestamp windows versus consumption-based recovery in the compact-context skill.

## Acceptance

- [x] Focused tests verify resume and directive expiry, agent attribution, daemon suppression and unchanged force vetoes.
- [x] Verdict reports selected signal and conditional or unknown expiry without leaking directive text or agent identifiers.
- [x] Skill explains timestamp windows and that another veto can remain.
- [x] Ruff, mypy, pyright and the full test suite pass.

## Constraints

PRRD S5.1 forbids suppressing validation to pass the gate; PRRD S6.1 requires preserving detector failure behavior. No new persistent state or safety-policy change.

## Approval log

- 2026-10-13T23:06:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T04:18:20+0200 — COMPLETE by main-agent@ai-maestro-janitor. all four acceptance boxes verified on 2026-10-18 against named tests, the skill text and a full green gate at 828097d1; the force-veto test is a weak, literal-string assertion, recorded in STATE.

## STATE

2026-10-17 impl (uncommitted, pending orchestrator commit): dispatch._active_waiting_signal returns (kind, expiry_text); _cadence_active_waiting is its boolean wrapper; external_handoff_clear._decide calls the signal once, facts[waiting_signal] only; VERDICT line adds waiting=<kind>, <expiry> when why=active-waiting; compact-context SKILL.md names the four signals and the 30-minute windows. Tests: new test_active_waiting_signal.py (15) plus 2 handoff tests; 392 passed across the six named files; ruff, mypy, pyright clean on changed files; full suite not run. recovery-flag is unreachable in the VERDICT line (recovery gate runs first), covered at function level only. Out of scope: issue suggestion 3.
2026-10-18 — SUPERSEDES the 2026-10-17 'uncommitted' line: the change is committed as 0e131aa8 + 815acb25 (implementation-commits). Boxes verified this session: (1) tests/test_active_waiting_signal.py covers resume-stamp and directive expiry (test_resume_stamp_reports_seconds_left, test_resume_directive_reports_seconds_left, test_the_1800s_boundary_returns_none_for_stamp_and_directive), agent attribution (test_agents_report_a_count_and_never_an_id) and daemon suppression (test_daemon_coverage_suppresses_only_the_stamp). Force vetoes unchanged: tests/test_external_handoff_clear.py:595 test_force_never_overrides_a_safety_veto (pre-existing, 95a5beda) still passes and keeps active-waiting non-overridable, but it asserts the reason-prefix predicate on literal strings, not the live gate, so it is a weak assertion; 0e131aa8 changed no test outside test_active_waiting_signal.py and two added handoff tests. (2) test_active_waiting_verdict_names_the_signal_and_leaks_no_directive_text plus the count-not-id test. (3) skills/janitor-compact-context/SKILL.md:70-79 names the 30-minute windows and that another veto can remain when the signal lapses. (4) Full gate at 828097d1 (contains both commits): ruff, mypy and pyright clean, pytest 18615 passed, 2 skipped. No release or field event is needed: the acceptance is all repo-verifiable.
