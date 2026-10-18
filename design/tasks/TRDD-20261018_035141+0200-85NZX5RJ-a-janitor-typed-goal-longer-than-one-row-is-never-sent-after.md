---
trdd-id: 85NZX5RJ
title: A janitor-typed goal longer than one row is never sent after a clear
column: todo
status: tasked
created: 2026-10-18T03:51:41+0200
updated: 2026-10-18T03:51:52+0200
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
approval-datetime: 2026-10-18T03:51:41+0200
parent-trdd: K9AHY1ZB
---

# A janitor-typed goal longer than one row is never sent after a clear

## Symptom

Every janitor-typed `/goal` re-send after a clear has failed in all 3 logged attempts in `.janitor/logs/clear-trigger.log` (2026-10-05 03:17 s:20d63f12, 2026-10-13 14:41 s:3a6129dd, 2026-10-14 02:04 s:1e85b407). Each logged `not sent: gave up after 3600s (field not empty (<text>))`, and `<text>` is the TAIL of the goal itself, never the head. A successful chain logs `chain: OK` without the goal text, so this log cannot show whether any goal chain ever succeeded: 3 logged failures, success not observable here. No `inject` line between the clear and the give-up shows a typing or settle failure.

## Measured so far (2026-10-18)

- Goal lengths 156, 173, 164 chars. The logged tails start at offsets 131, 135, 135: the split fits the input field wrapping onto a second row at a pane width near 137 columns (INFERRED from three offsets, not measured; the 10-05 tail has no leading space, the others do, which suggests word wrap).
- `terminal_trigger.extract_prompt_field` (scripts/lib/terminal_trigger.py:192) is written to join wrapped rows from the last marker line down to the box rule, yet the logged field is only the second row. Why the head row is lost is NOT known.
- Short commands (`/janitor-resume`, `/clear`) fit on one row, so this path has probably (not verified: `/model ...` or `/reload-plugins --force` could wrap on a narrow pane) only been exercised by `/goal`.

## Hypotheses to separate (each predicts a different capture)

1. The capture does not contain the marker row (cursor/scroll or a capture line limit).
2. The marker row is excluded by `_is_choice_row` or the marker is not at the start of the row once the text wraps.
3. The text already sat in the field before the inject loop ran (an earlier step typed it), so the first read saw a field that was not ours-only. If this one is confirmed, the defect is in the TRDD-B3PY3HV7 chain code and B3PY3HV7 goes back to dev instead of waiting here.
4. The continuation row carries a marker-like glyph (for example a cursor glyph at the row start), so the last-marker rule lands on row 2 and returns exactly the tail. This fits the evidence best and differs from 2.

## Acceptance

- [ ] A real pane capture (tmux and iTerm) of a 160-character typed line in Claude Code is recorded under reports/, and the hypothesis it confirms is named.
- [ ] A regression test built from that real capture fails before the fix and passes after.
- [ ] Fix lands; full gate (ruff, mypy, pyright, pytest) green.
- [ ] Field: after a release, one janitor clear of a session with an unmet goal logs `chain: OK` and the goal is active in the new session (this also closes TRDD-B3PY3HV7).

## Approval log

- 2026-10-18T03:51:41+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
