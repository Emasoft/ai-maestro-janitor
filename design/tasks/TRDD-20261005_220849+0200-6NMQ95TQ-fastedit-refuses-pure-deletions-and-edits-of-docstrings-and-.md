---
trdd-id: 6NMQ95TQ
title: fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script
column: backburner
status: tasked
created: 2026-10-05T22:08:49+0200
updated: 2026-10-08T17:32:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:49+0200
blocked-by: []
pre-block-column: 
blocker-probe: gh issue view 14 --repo Emasoft/fastedit --json state
blocker-holds-if: match:OPEN
blocker-probe-canary: match:state
unblock-when: []
---

# fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed three times in one day in this repository: fastedit refused a pure deletion of a block inside a function, an addition to a module docstring, and a new module-level constant. In the first case the worker edited a scratch copy by script and applied it as a full-function replacement, which the standing rule forbids; in the second the item was skipped and a stale docstring remains; in the third the text was written inline instead. To do: reproduce each refusal on a scratch file, find the supported way to make each edit, report upstream what has none, and state in worker prompts what to do on a refusal.

## Approval log

- 2026-10-05T22:08:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 FOURTH REFUSAL CLASS: a one-line insertion inside a function body (cmd_recall_cli and the find function of scripts/memgrep/src/memory.rs, card ZYX8B2RA) was refused six times across two workers. The owner refused the plain-edit fallback on 2026-10-06. ZYX8B2RA now waits on this card.
2026-10-06: further fastedit defects, a different subject from this card, recorded here as pointers. (a) Reported as Emasoft/fastedit#15: after two edits to one file, fastedit diff shows both edits, not only the last (measured on a scratch file, fastedit 0.5.0), and its help does not state the baseline; which backup it compares against is INFERRED, not read in the code. (b) Seen once, not reproduced, mentioned in a comment on #15: on that scratch file a later fastedit diff in a new process printed nothing and fastedit undo said there was no undo history; the same sequence on a second file kept its history. If real, undo history can vanish between processes.
- 2026-10-07T04:29:46+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on Emasoft/fastedit#14 and #15 (refused edits, diff baseline), both open on 2026-10-07; re-test the six recorded edits on each new fastedit release


## STATE

2026-10-06 NEXT ACTION: the refused edits are reported upstream as Emasoft/fastedit#14 (and the diff baseline as #15; file modes on #11, recurrence commented 2026-10-06). Wait for fixes there; this card's blocked dependents (TRDD-ZYX8B2RA, TRDD-YELTOX2S) resume when a fastedit release accepts the six recorded edits. Re-test those edits against each new fastedit release.
2026-10-06: hooks/hooks.json was found at mode 0600 after two fastedit writes today (an anchored fastedit edit for bace60f4, then create --force for dd779c12; mode not checked in between); a scratch test with fastedit 0.5.0 kept 0644 for create --force and edit, so the trigger is unknown. 41 tracked files in this repo were at 0600 (unknown writers and times); all restored to 0644 on 2026-10-06. Reported as a correction on Emasoft/fastedit#11. The dd779c12 commit message overstates (says both files).
2026-10-06: worker-reported, not reproduced: fastedit could not delete two stray blank lines in scripts/memgrep/src/fixers/mod.rs (C22 step S1); the worker then rewrote the whole file with fastedit create --force instead of stopping as its brief asked. The committed diff removed no original line. Same class as this card if reproduced: deletions with no replacement text are refused.
2026-10-06 (C22 S3+S4, commit 1f2a2896): three more refusals, all worker-reported and not reproduced by the main agent except that, for (b), the main agent checked that the committed diff near lint_label adds only the three stray lines, (a) and (b) on scripts/memgrep/src/memory.rs, (c) on design/specs/wikimem-memgrep-spec.md: (a) fastedit edit --replace lint_label with lint_label's own doc and body as the snippet printed a content-faithfulness failure, then 'Applied edit' while the file stayed unchanged; (b) fastedit delete lint_label removed the function but left its attached doc comments; (c) a keep-marker section replace in design/specs/wikimem-memgrep-spec.md was rejected after 9 attempts with a marker leaking into the merge. Earlier in the same step fastedit deletions left orphan #[test] and doc lines that a worker then removed with Python string replaces.
2026-10-07: the probe checks fastedit issue 14 only; blocked-by also names issue 15, so the card can auto-clear while 15 is still open. Check 15 by hand before resuming.
2026-10-08: both issues CLOSED upstream (14 at 09:30Z, 15 at 09:29Z, closure comment documents the deterministic paths for the refused classes) but the fixes are ON MAIN ONLY — fastedit 0.5.0 is still the latest tag/release (compare v0.5.0...main is 4 commits ahead) and the installed uv tool is 0.5.0. Probed the installed 0.5.0 with issue 14's repro shapes: the pure-deletion refusal still stands (function-splice guard correctly refuses a snippet with no definition line) and --insert-after works. unblock-when set to the two issue predicates so trdd-drift sees them closed — BUT the card's own discipline says re-test the six recorded edits against each new fastedit RELEASE; the fix is not released yet, so the card stays blocked on the practical gate: upgrade the installed fastedits tool (uv tool upgrade fastedits or install from main), re-run the six recorded edits, then resume the blocked dependents ZYX8B2RA and YELTOX2S. Adding a release predicate is not expressible (no kind for it), so the hand-check noted in the card's 2026-10-07 line still applies.
2026-10-08 re-test against INSTALLED fastedit 0.5.0 (per review round 6, before the drift fire could auto-unblock): (b) delete no longer leaves attached docs — plain python fn, python fn with docstring, and a Rust fn with a comment ABOVE it all deleted cleanly (the Rust case prints 'warning: parse errors after delete' — cosmetic, tree-sitter chokes on the # comment I planted; the removal itself was correct); (a) replace-with-shorter-body now APPLIES correctly (faithfulness guard accepts it, file verified changed, and a no-op re-edit is correctly refused as 'No change resulted'); (c) keep-marker: a snippet MERELY MENTIONING marker words applies cleanly; the diff baseline (issue 15) is correct — diff shows the last edit, a no-op re-edit reports no change. CONCLUSION: on the shapes re-testable in isolation on 0.5.0, the recorded refusals do NOT reproduce — but the fix is still UNRELEASED (main is 4 commits ahead of tag v0.5.0, no newer tag exists), and one refusal class (the original 'Applied edit while file stayed unchanged' on a 624 KB Rust file) was never reproduced in isolation. Card moves to backburner: re-run this re-test against the NEXT fastedit RELEASE (tag > 0.5.0), then resume dependents ZYX8B2RA and YELTOX2S.
2026-10-08 — review round 7 narrows the conclusion above: it was ~4 SHAPES on SMALL SYNTHETIC scratch files against 0.5.0, which never contained the fix (fix lives on main only). The original failures were LARGE-FILE model-merge phenomena (624 KB TS, memory.rs-scale Rust) — the regime small files exclude (8X7C7TU9: memory grows with the square of chunk size), so the probe proves only 'small-file shapes pass on 0.5.0', NOT 'the bug is gone'. Roughly 4 of ~7 recorded shapes were re-tested; the C22 (a) shape was approximated (shorter-body, not full-symbol-doc-and-body) and the #11 mode-0600 class was NOT re-tested. GATE for resuming dependents ZYX8B2RA and YELTOX2S remains: original shapes on original files against a fastedit that contains the fix (next release tag > 0.5.0, OR install from git main via uv tool install if resumption becomes urgent).
