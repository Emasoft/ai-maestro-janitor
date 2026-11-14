---
trdd-id: PF6ZIIET
title: A janitor-typed goal over 800 characters collapses into a pasted-text placeholder and strands the input box (issue 343)
column: testing
status: tasked
created: 2026-11-14T22:28:02+0100
updated: 2026-11-14T22:30:37+0100
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
approval-datetime: 2026-11-14T22:28:02+0100
implementation-commits: [6401fe4a]
---

# A janitor-typed goal over 800 characters collapses into a pasted-text placeholder and strands the input box (issue 343)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: (1) Capture ONE real Claude Code 2.1.325 frame of a single write over 800 characters (the placeholder) and of what C-a, C-k, C-u do to a placeholder chip: that is the only unknown the fix depends on. (2) Build chunked typing (fix A) in terminal_trigger.build_type_only_steps, then residue recovery (fix C) in _clear_ours and _clear_leftover_command. (3) Write the tests (a paste-collapsing pane script); run them only before the push. One bounded change per fix. Ask the Fable advisor first if the chip-deletion behaviour forces a different design.
- Status: research done, nothing built. GitHub issue 343 (open). The earlier card TRDD-85NZX5RJ (testing) analysed the same issue and found a DIFFERENT mechanism (wrapped input rows, fix 8dae3e5e); the failures of 2026-11-13 and 2026-11-14 below are NOT explained by it. Do not merge the two cards: different cause, different fix. Related: TRDD-S8BZI761 (testing, stranded goal tail), archived TRDD-KXZJOZBQ (text stranded by an earlier send).
2026-11-14 BUILT in 6401fe4a: build_type_only_steps types a command over 250 chars in pieces with a 0.3 s gap; the leftover-clear passes clear a [Pasted text #N] residue; fleet_inject refuses a multi-step iTerm plan. 3 tmux tests pass. NEXT ACTION: release, then watch clear-trigger.log for a long /goal arriving verbatim; close GitHub #343 once seen.

## Findings (verified by reading code, the janitor logs and the Claude Code 2.1.325 minified binary; V verified, I inferred)

The 2026-11-13 and 2026-11-14 failures are NOT a wrap or read-back problem. The janitor types the whole "/goal <text>" (1036 characters in the failing case) in ONE iTerm write text call (scripts/lib/terminal_trigger.py build_type_only_steps about L452-485: iTerm = one osascript "write text ... without newline" at about L476; tmux = one send-keys -l, no chunking, no bracketed-paste markers). Claude Code treats any single input chunk over 800 characters as a paste and collapses it to "[Pasted text #N]" (V: paste module R8 = 800; input handler tests the chunk length per input event). The roughly 14-character remainder arrives as a second chunk and is typed normally (I: the chunk split at about 1022 characters is inferred from the field text). The input box then holds "[Pasted text #283]eloper-plugin!" (V, from the log).

A paste-collapsed /goal can never run as a command even if the read-back accepted it (V by reading the minified submit path, not runtime-tested): the submit path skips slash handling when the visible text does not start with "/" but the expanded text does, and sends "Pasted text:" plus the text as prose.

The stranded placeholder is never removed (V code and log): _clear_ours (terminal_trigger.py about L1107-1178) stops after pass 1 because the field is not a suffix of the command ("field not emptied after 1 clear passes (stranded text)"), and the give-up _clear_leftover_command (about L1180-1197) only clears text equal to our command. Rule 1 (about L1276-1280) then defers every later /clear chain behind the non-empty field for hours: the identical "#283" placeholder was read on 11-13 20:50 to 21:49 and on 11-14 at 11:43, 12:45, 13:50, 16:45 (17:50 read None; 19:33 chain OK), about 19 hours. Only ONE failure actually typed the goal (2026-11-13 21:49, "chain: FAILED /goal ... not sent: gave up after 3600s (field not empty ('[Pasted text #283]eloper-plugin!'))"); the other five were later /clear chains deferred behind the stranded text. Host load1 was 25-57 and the osascript send step timed out twice, which contributes to coalescing and late renders (I).

Goal source: scripts/clear_trigger.py about L139-188 (GOAL_MAX_CHARS = 4000, sanitize_goal, clear_bootstrap), goal from session_continuity.clear_fields(transcript, goal_max=4000); the cap was widened to 4000 so the goal is not weakened, which is why truncation is not the answer.

## Decision

Fix A (core): chunked typing. In build_type_only_steps split the command into pieces of at most about 250 characters, one write text ... without newline per piece with a short sleep (at least 0.3 s) between them (RUN and SLEEP steps are already supported by _run_steps). Goal text and shape unchanged, works on tmux too, verified by the existing read-back (wrapped read-back handled by 8dae3e5e). Con: back-to-back writes can still coalesce into one read under heavy load (800 over 250 is about 3 pieces); more osascript calls against the 10 s step timeout; slower. Mitigation: fix C.

Fix C (needed with A; also ends the 19-hour block): residue recovery. In _clear_ours and _clear_leftover_command treat a field matching an optional "[Pasted text #N]" chip plus an optional suffix of our own command as ours; repeat clear passes, bounded, until empty; require that the janitor typed once and that no keystroke came since typing (the existing typing probe and minimum-length guard); log the malformed read-back text and each retype. Unverified: whether C-a, C-k, C-u removes a placeholder chip at all (Claude Code has chip-aware cursor handling).

REJECTED, with reasons:
- B, accept "[Pasted text #N]" as a valid read-back and press Enter: the submit path turns it into prose, so /goal would never be set.
- D, cap the goal below 800 characters: re-types a clipped, weaker goal; a goal near the cap still depends on single-chunk delivery. Acceptable only as a stopgap.
- E, a short /goal pointing at a state-dir file: changes the goal semantics (the condition Claude Code evaluates would be the pointer text); not recommended unless A fails.

## Tests (real, no mocks; run only before the push)

Existing coverage: tests/test_terminal_trigger_readback.py (wrapped read-back, clear passes, give-up) has no test mentioning "Pasted text"; tests/test_clear_trigger_busy_gate.py uses a real private-socket tmux with a simulated TUI that does not model paste collapsing; no test types a command over 800 characters. New: a paste-collapsing pane script (a single os.read chunk over 800 characters renders "[Pasted text #N]", chunks up to 800 render verbatim); drive the real run_chained_inject with a goal of about 1000 characters; assert (1) the field verifies and Enter submits the exact goal, (2) a pre-seeded "[Pasted text #1]tail" field is cleared (needs a real capture of the chip and C-u behaviour as a fixture before trusting this one), (3) a give-up leaves no machine residue. State in the docstrings that the pane is a simulated TUI, not a live Claude Code.

## Approval log

- 2026-11-14T22:28:02+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
