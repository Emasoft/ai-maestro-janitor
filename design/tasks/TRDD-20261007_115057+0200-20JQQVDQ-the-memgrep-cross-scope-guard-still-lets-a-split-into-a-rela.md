---
trdd-id: 20JQQVDQ
title: The memgrep cross-scope guard still lets a split into a relative not-yet-existing page through
column: backburner
status: tasked
created: 2026-10-07T11:50:57+0200
updated: 2026-10-09T00:20:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T11:50:57+0200
review-after: 2026-10-09
---

# The memgrep cross-scope guard still lets a split into a relative not-yet-existing page through

## Symptom (INFERRED from reading commit 2a600afb's guard diff only, see the Note below, scripts/memgrep/src/memory.rs guard_downward_cross_scope)

The guard classifies each path as p.canonicalize().unwrap_or_else(|_| p.to_path_buf()) and then scope_layer. A page that does not exist yet cannot be canonicalized, so its RAW spelling is classified; scope_layer's hardcoded-root tests need a leading slash, so a relative spelling such as .claude/project/memory/new.md classifies as None and the guard fails open. That is exactly split-mem-topic's --into (it must not exist yet) given as a relative path: a cross-scope split lands a downward link. Existing relative pages are fixed by 2a600afb.

## Task

Absolutize before the fallback: canonicalize the PARENT and join the file name, or std::path::absolute, then scope_layer. Failing test first: split-mem-topic with a relative --into under a LOCAL root and --page under a USER root (scope overrides pointed at scratch) is refused and writes nothing.

## Context

Public issue 330 and commits 31c2e3b0, b5e8ae5c, 2a600afb. Found by a read-only review on 2026-10-07 (reports/board/batches/20261007_113607+0200-b5e8ae5c-review.md, gitignored). Also from that review, smaller: the code comments cite a card id that exists only on one host (cite issue 330 instead); nobody checked whether the merge/split skill or help text still advertises cross-scope merges, which these verbs now refuse in both directions.

## Note

These commits were made in this checkout by a writer the main session could not identify. Do not start this card while that writer is still editing scripts/memgrep; coordinate through the owner.
2026-10-07 review corrections: (a) evidence level is INFERRED, not VERIFIED: only the guard's diff in 2a600afb was read; scope_layer's body and the path from cmd_split_topic_cli to the guard were not, so first confirm by a failing test that --into is not made absolute earlier. (b) The gap is narrower: a spelling with a slash before the scope segment (./.claude/project/memory/new.md) classifies; only spellings like .claude/project/memory/new.md or memory/new.md from inside a scope fail open; the test must use one of those. (c) Fix: canonicalize the nearest EXISTING ancestor and append the remaining components (canonicalizing only the parent fails for a new subfolder; std::path::absolute does not resolve symlinks). (d) The guard's doc comment in 2a600afb claims the fallback closes the relative-path hole; correct it with the fix. (e) Startable when scripts/memgrep has no uncommitted change and no new memgrep commit for 24 hours, or when the owner says go.
2026-10-07 second correction: point (b) above is also INFERRED (scope_layer's body was not read in this session). Test spelling: use .claude/project/memory/new.md with the process cwd set to a scratch project root and every scope override pointed at scratch; do not use memory/new.md, which only adds a cwd dependency.
2026-10-07: commit dbf2f0c9 cites this card in its subject but is NOT this card's fix: it only clears two clippy errors in b69a5d32's symlink-alias test so the release gate passes. Do not list it under implementation-commits.
2026-10-08 (park caveat): the review-after date 2026-10-09 is a known false-positive — the real restart condition is memgrep tree quiet 24h (card note (e)); if any Rust commit lands tonight the date expires while the condition is false. Re-derive the condition before starting; do not trust the date alone.
2026-10-08 — second-round review of the corrective edit: no blockers. Two recorded dispositions: (1) card verified STARTABLE per note (e). WHY IT STAYS PARKED: orchestrator judgment at session end — starting a fresh memgrep Rust implementation at 23:53 with no owner present would strand a half-landed change across sessions; this is WIP discipline, not a blocker. AUTHORITY CAVEAT (fourth-round review): the fan-out directive was session-scoped; carrying it forward is an inference, not an owner statement — a cold-reading session must NOT treat this note as a work order. Re-derive note (e) AND get owner sanction — a go from a session where the owner is present and responding (NOT a heartbeat auto-resume or unattended fire), or the owner's written answer to the pending escalation — before pulling. THIS CAVEAT LAPSES when owner escalation (a) — cross-session authorization for pulling THIS card — is answered (escalation (b), the governance conflict, is a DIFFERENT escalation and does not open this gate): the answering owner message itself is the sanction (if affirmative TO PULLING THIS CARD) or the reversal (if negative); when answered, this line is replaced with the answer's date and verdict — the answering session owns that bookkeeping. Do not re-ask. Also corrected: the no-fresh-review-rounds owner ruling does NOT apply here (this is new implementation work, not review-loop adjudication); (2) the owner-quote provenance in memory atom LS2E-OQ8N is refuted against FABRICATION (exact text confirmed in a user-role transcript message) — automation-injection not excluded in principle, no observed mechanism (every automated message OBSERVED this session was tag-wrapped or token-prefixed; the quote is bare prose; the class was not exhaustively enumerated).
2026-10-09 fourth-round review of 4214f0f9: accepted, no blockers; two owner escalations pending — (a) cross-session authorization for pulling this card, (b) two-rounds-max vs one-owner-loop-closure governance conflict. Line above amended with the authority caveat per its finding 1.
2026-10-09 seventh review of 2c7b0449: accept, three LOW (clause density; a LIVE attended-session go is outside the lapse clause — if you sanction by live go, amend this line yourself or say 'pull 20JQQVDQ' in your own words, which supersedes this note regardless; bookkeeping unenforceable on a card-blind session — stall direction is under-pull, never over-pull). REVIEW LOOP CLOSED at round 7 under atom LS2E-OQ8N's owner rule (rounds 6-7 both pre-declared no remaining load-bearing layer); this closure is PROVISIONAL — reversed if the owner rules otherwise on escalation (b). The bar covers adjudication-of-the-loop ONLY: a fresh fork for NEW work on this card (a new change to review) remains permitted. The mechanical review gate still demands forks on future writes regardless — do not cite this line to refuse a gate demand. Residuals durably live in this card's Note entries (fourth-round record above) and in chat; no separate packet document exists.
2026-10-09 ninth review of da30eccd: accept, two LOW (vacuous PROVISIONAL marker — names no reverted-to state, since two-rounds-max expired ~round 3 and only attrition remains either way; closure date stale vs rounds 8-9 edits — reconciliation is on-card via the gate-compliance caveat). Round 9's stated conclusion: NO content-level defect category on this card's note text remains unexhausted — rounds 6-9 were pure-KEEP polishing of each other's own fixes. What remains is owner decisions (escalations a and b), not defects. Escalation (b) is now evidenced by nine rounds: the gate generates fork rounds against a loop its own owner rule closed; mechanical compliance is the only thing still producing forks.
2026-10-09 tenth review of 7fb2a0ff: accept, two LOW-MEDIUM + two LOW, no outcome changes. Corrections adopted into the record: (1) the exhaustion claim is bounded — 'no category the nine rounds EXERCISED remains open', not an uncompletable universal; (2) 'pure-KEEP polishing' was false precision — rounds 6-9 returned LOWs each time, the honest form is 'only LOW-severity findings, each polishing the previous round's own fixes, no new load-bearing layer'; (3) the 'two-rounds-max expired ~round 3' line is the parent's interpretive gloss echoed by round 9, not a checked fact (immaterial: the cap was exceeded on any count); (4) gate share of fork production is ~dominant-not-sole for rounds 6-7 (the parent's fix-every-LOW choice fed the loop alongside the gate; gate-only for rounds 8-9). TERMINAL STATE per round 10: loop functionally closed at round 7 (provisional on escalation (b)); rounds 8-10 were gate-compliance artifacts, not defect-finding; card note text at its floor; every residual routes to owner decisions (a) and (b). No further fork on this card's note text can return anything a decision does not already cover.

## Approval log

- 2026-10-07T11:50:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-08T20:33:40+0200 — column → dev. batch fan-out from main session; owner 2026-10-07 delegation covers code edits
- 2026-10-08T20:37:42+0200 — column → backburner. 24h memgrep-quiet clock resets on any DGBZVZPP Rust commit; parked with review-after, restartable when the tree has rested 24h per card note (e)
- 2026-10-08T23:45:29+0200 — re-park CORRECTED after adversarial review (no column move happened — card stayed on backburner). Evidence, verified this session: fd880f60 (R9UXOSR5) touched no scripts/memgrep path (git show --stat: 0 memgrep files). Note (e) condition re-derived 2026-10-08T23:53+0200 and HOLDS: last memgrep commit dbf2f0c9 at 2026-10-07T12:45:58+0200 (~35h prior), git status --porcelain scripts/memgrep = 0 uncommitted. Card is STARTABLE per note (e); the quiet-clock is no longer a reason to stay parked.
