---
trdd-id: 85NZX5RJ
title: A janitor-typed goal longer than one row failed in all 3 logged goal re-sends after a clear
column: testing
status: tasked
created: 2026-10-18T03:51:41+0200
updated: 2026-10-18T11:04:13+0200
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
implementation-commits: [8dae3e5e]
---

# A janitor-typed goal longer than one row failed in all 3 logged goal re-sends after a clear

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-18
CAUSE UNKNOWN. No capture or synthetic case on record yields a tail-only read in a realistic state. The 10:30 line under Hypotheses refutes hypothesis 4 ONLY for a fresh, never-cleared Claude Code 2.1.302 session in tmux at 137 columns with an empty box; the failing re-send runs right after /clear and the bootstrap chain, on the Claude Code versions of 10-05 to 10-14, so hypothesis 4 stays open for that state. Hypothesis 1 is not supported by any capture so far (the synthetic scrolled case returned None, not a tail); "unlikely" in the 10:30 line overstates. Item 4 sentence "1 and 2 also produce exactly the tail" is SUPERSEDED by the probe (reports/board/20261018_102008+0200-85NZX5RJ-probe.md): H1 gave None, H2 gave the full goal or None. Not checked: whether the 10-05/10-13/10-14 sessions ran in tmux at all (another terminal means a different capture path). The janitor capture argv (terminal_trigger.py:636) is worker-read. The stuck-goal defect is now its own card (TRDD-S8BZI761). NEXT ACTION: capture the screen in tmux right after a janitor /clear with a long goal re-sent; then read every caller of extract_prompt_field for its handling of None and partial reads (requirement for any fix: None means unreadable, never empty).
2026-10-18 11:04 CAUSE FOUND; FIX 8dae3e5e (the STATE text above, from 10:4x, is superseded). Claude Code indents every wrapped input-box row by two spaces; extract_prompt_field joins the rows, so a wrapped command reads back with a doubled space at each wrap, and prompt_field_shows_only's exact compare returned False on two real 2.1.302 captures (shows_only: False, main-session run). The inject loop then called clear_fn, whose C-a/C-k/C-u kills only the first visual row (live tmux test, reports/board/20261018_103557+0200-85NZX5RJ-tidy-keys.md), leaving the tail that every later pass logged as field not empty until the 3600 s give-up. The reader was never at fault; hypotheses 1-4 are moot and hypothesis 3's clause sending TRDD-B3PY3HV7 back to dev does not fire. The None-means-unreadable requirement stands only for the repaint race (an empty read before the box repaints, seen in a capture). Fix: compare after collapsing runs of 2+ spaces (first character kept). Gates: readback 80 passed, full suite 18639 passed 2 skipped, ruff/mypy/pyright clean. REMAINING RISK: a half-drawn first read still takes the clear path and can strand text until TRDD-S8BZI761 lands. If the post-release field check fails with field not empty, check it against S8BZI761's strand path before blaming this fix. FIELD CHECK to close: after a release, one logged 'chain: OK' after a /goal re-send in .janitor/logs/clear-trigger.log. TRDD-B3PY3HV7 stays blocked on this card until then. Untested: Claude Code versions of 10-05..10-14, non-tmux readers, a wrap with no space in the command (e.g. after a hyphen). Follow-up: fleet_inject.field_holds_our_command has the same wrap blind spot (TRDD-9OFH7DLQ).
2026-10-18 11:04 SCOPE: the mechanism (doubled space at the wrap, exact compare False, tidy stranding the last row) was reproduced on Claude Code 2.1.302 in tmux; the three field failures (10-05, 10-13, 10-14, older versions) are consistent with it, not reproduced. The commit message and the WHY comment of 8dae3e5e say 'failed this way', which overstates; soften the comment on the next edit of terminal_trigger.py. The full suite (18639 passed) ran before three comment-only edits; the last gates were git diff --check, the readback file (80 passed), ruff and pyright.

## Symptom

All 3 logged janitor-typed `/goal` re-sends after a clear failed, in `.janitor/logs/clear-trigger.log` (2026-10-05 03:17 s:20d63f12, 2026-10-13 14:41 s:3a6129dd, 2026-10-14 02:04 s:1e85b407). Each logged `not sent: gave up after 3600s (field not empty (<text>))`, and `<text>` is the TAIL of the goal itself, never the head. A successful chain logs `chain: OK` without the goal text, so this log cannot show whether any goal chain ever succeeded: 3 logged failures, success not observable here. No `inject` line between the clear and the give-up shows a typing or settle failure.
2026-10-18 GitHub issue janitor#343 reports this defect; the card, not the issue, holds the live analysis (the issue's whitespace hypothesis does not explain a tail-only capture).

## Measured so far (2026-10-18)

- Goal lengths 156, 173, 164 chars. The logged tails start at offsets 131, 135, 135: the split fits the input field wrapping onto a second row at a pane width near 137 columns (INFERRED from three offsets, not measured; the 10-05 tail has no leading space, the others do, which suggests word wrap).
- `terminal_trigger.extract_prompt_field` (scripts/lib/terminal_trigger.py:192) is written to join wrapped rows from the last marker line down to the box rule, yet the logged field is only the second row. Why the head row is lost is NOT known.
- Short commands (`/janitor-resume`, `/clear`) fit on one row, so this path has probably (not verified: `/model ...` or `/reload-plugins --force` could wrap on a narrow pane) only been exercised by `/goal`.

## Hypotheses to separate (each predicts a different capture)

1. The capture does not contain the marker row (cursor/scroll or a capture line limit).
2. The marker row is excluded by `_is_choice_row` or the marker is not at the start of the row once the text wraps.
3. The text already sat in the field before the inject loop ran (an earlier step typed it), so the first read saw a field that was not ours-only. If this one is confirmed, the defect is in the TRDD-B3PY3HV7 chain code and B3PY3HV7 goes back to dev instead of waiting here.
4. The continuation row carries a marker-like glyph (for example a cursor glyph at the row start), so the last-marker rule lands on row 2 and returns exactly the tail. It would produce exactly the tail and is the only hypothesis that keeps the head row in the capture; 1 and 2 also produce exactly the tail. Not ranked: none is measured.
2026-10-18 10:30 MEASURED. Hypothesis 4 REFUTED on a real capture: Claude Code 2.1.302, tmux 3.7c, 137-column pane, the janitor's own argv (tmux capture-pane -p -t <pane>, scripts/lib/terminal_trigger.py:636); a typed 164-char /goal wraps to a second row that begins with two ASCII spaces, not the marker, and extract_prompt_field returns the full text (reports/board/20261018_102355+0200-85NZX5RJ-real-capture.md). A synthetic marker-on-row-2 screen reproduces the tail only by construction (reports/board/20261018_102008+0200-85NZX5RJ-probe.md), so it is not evidence. Hypothesis 1 is unlikely: the 10-13 tail was read identically at 14:41, 17:40, 18:40 and 19:40, a steady screen. Untested: the post-clear screen state in which the re-send actually runs, older Claude Code versions (10-05 to 10-14), and the 131-offset split of 10-05 (no leading space). Separate defect found in the same log: the goal text stayed in the input field for hours, blocking every later /clear with field not empty; it needs its own card. Constraint for any fix (review): extract_prompt_field callers must treat None as unreadable, never as empty, or a fix turns give-up into typing over existing text. NEXT: capture the screen right after a /clear with a long goal typed in, then read every caller's handling of None and partial reads.

## Acceptance

- [ ] A real pane capture (tmux and iTerm) of a 160-character typed line in Claude Code is recorded under reports/, and the hypothesis it confirms is named.
- [ ] A regression test built from that real capture fails before the fix and passes after.
- [ ] Fix lands; full gate (ruff, mypy, pyright, pytest) green.
- [ ] Field: after a release, one janitor clear of a session with an unmet goal logs `chain: OK` and the goal is active in the new session (this also closes TRDD-B3PY3HV7).

## Approval log

- 2026-10-18T03:51:41+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T11:03:55+0200 — column → testing. fix 8dae3e5e; field check after a release
