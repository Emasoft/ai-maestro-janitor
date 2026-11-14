---
trdd-id: QAF3N673
title: Wikimem increment 3 foreign-content rule safe fixer and one owner for atom-after-footer
column: dev
status: tasked
created: 2026-11-15T00:39:55+0100
updated: 2026-11-15T00:39:55+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T00:39:55+0100
parent-trdd: F8EIVTSG
---

# Wikimem increment 3 foreign-content rule safe fixer and one owner for atom-after-footer

## STATE

NEXT ACTION: research worker first (read-only): (1) explain D12's 16 PROJECT placeholders vs the dry run's 28 linkless bullets (blocks the D5 fixer's placeholder classes); (2) map today's repair path for atom-after-footer: Python repair_defect and its candidate step (memory_content_precheck.py around 877-886), the janitor-memory-repair skill procedure, the chore routing; (3) list every place that would read the WMATOM-009 verdict if the trailing boundary changed. Then write the increment-3 proposal (PROPOSAL FOR ACTION marker), then build.

## Scope (parent TRDD-F8EIVTSG, design D5 and D9; spec WM-LINT-11, WM-LINT-12, WM-NOTE-06, WM-NOTE-08)

1. atom-after-footer (WMATOM-009) message names the exact remedy: move the marker and its body above the first footer heading, keep a bare `- [[target]]` bullet in the section.
2. New rule WM-LINT-12 (foreign content in a link section, WARN) with its issue code in design/specs/issue-codes.toml and the regenerated rules_gen.rs, and a SAFE fixer per D5: an atom or prose block moves above the layout boundary, every link it held stays as a bare bullet (section edge set unchanged), footnote definitions move to the Notes pool, a known bootstrap placeholder becomes `- (none yet)`, any other placeholder text moves above the footer.
3. Python repair_defect takes atom-after-footer from `memgrep lint --no-fix --output-format json` (one owner) with a parity test; the Python boundary copy (memory_content_precheck.py:677-755) is removed.
4. Carried from increment 2: retarget the superseded-move fixer to the Notes boundary (WM-NOTE-07 order) together with the trailing lint boundary change, so the WMATOM-009 blind spot (estimated 10 PROJECT and 8 USER atoms in a link zone on pages whose Superseded sits between the links and Notes) closes in the same change that would otherwise widen it; fix the body_start_line doc comment (unclosed frontmatter: callers append at EOF).
5. D9: the See-also footnote pool is retired (WM-NOTE-06 amended in spec 3.0.0); the fixer moves those definitions to the Notes pool.
6. Same increment: the janitor-memory-repair skill procedure and chore routing, and memgrep --help for the changed messages.
Rules: no new issue code without its emitter; every new lint rule passes WM-LINT-13 (the cheapest silencing edit must trip another rule or be refused); verdict changes are measured on the three stores in a dry run before the install.

## Approval log

- 2026-11-15T00:39:55+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
