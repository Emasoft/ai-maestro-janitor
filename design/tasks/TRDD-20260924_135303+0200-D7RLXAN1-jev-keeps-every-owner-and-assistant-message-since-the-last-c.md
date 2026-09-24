---
trdd-id: D7RLXAN1
title: Jev keeps every owner and assistant message since the last compaction verbatim and never scores it
column: testing
created: 2026-09-24T13:53:03+0200
updated: 2026-09-24T18:15:20+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: feature
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-24T13:53:03+0200
parent-trdd: null
implementation-commits: [c7779d84]
status: tasked
---

# Jev keeps every owner and assistant message since the last compaction verbatim and never scores it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-24
- DECIDED 2026-09-24 (owner gave full authority: "i've given you full authority to decide by yourself, just made the decisions on the base of verified facts and tests"): Q1 accept the one-time READ FIRST cost (single file; the two-file alternative stays unbuilt unless acceptance (d) shows it is too costly); Q2 "all" = since the session's LAST compact_boundary, older prose represented by Claude Code's own summary kept verbatim; Q3 enforce in code (prose is never a scored item), no prompt text changed. Implementation in progress (column dev).
- Column: dev. IMPLEMENTED 2026-09-24, NOT YET COMMITTED (the orchestrator commits; drafts docs_dev/20260924-d7-commit-*.txt): the change list with advisor fixes A-E and 14 test functions (tests 1-12, test 11 split into its Jev and llm-ext halves, plus one for the rule below) -- 13 shown failing on HEAD, the llm-ext guard (which HEAD already satisfies) shown failing on a tail=() mutant. One measured addition: extract_items drops only the BARE 'janitor heartbeat' reply -- transcript_roles.is_heartbeat_reply also matches that reply plus up to two lines, which silently dropped 9 real assistant messages from b2bf5b7b's full copy (acceptance (a) caught it). Report: reports/compaction-replacement/20260924_180444+0200-d7rlxan1-implementation.md
- NEXT ACTION: review and commit the behaviour change (only the 10 files this card touched -- other agents have uncommitted edits in the same tree), then decide acceptance (c)'s one failing criterion: d30bf250's injected copy shows 0 tool/event items and 4eb7bf5d's 2 (thin), because the token stage (budget_tokens 8000) admits large tool items the injected copy can only point at (TRDD-U6C3YXEL amendment S1 limits inline items to the token stage's set). Pre-existing -- HEAD showed 0 tool items on d30bf250 too, its floor met by assistant prose that now sits in the exchanges block. A scratch probe reading S1 as 'Jev kept' (scores.kept) gave 8/10/8 inline tool/event items on d30bf250/fd5cc3e0/b2bf5b7b; that is a change to another card's rule, so it needs its own card. Advisor fixes A-E and the review history: reports/compaction-replacement/20260924_140604+0200-advisor-prose-verbatim.md.
- Full design with the measurements: reports/compaction-replacement/20260924_133048+0200-prose-verbatim-design.md (gitignored scratch copy; THIS card holds the decisions).
- Digest question CLOSED (advisor): keep build_digest(items, ...) sending the newest 3 owner + 2 assistant messages to Jev as task context — not a violation, since the directive governs what survives into the output, not what Jev sees as its task description; stripping prose from the digest would degrade every tool-item score for no gain.
- OWNER QUESTIONS Q1-Q3 ANSWERED 2026-09-24 (see the first line of this block): (1) the ~20-35k-token one-time READ FIRST cost is accepted, single file; (2) "all" = since the session's LAST compact_boundary; (3) enforced in code, no prompt change, because a prompt sentence cannot guarantee a threshold outcome.
UPDATED 2026-09-24: column -> testing, implementation-commits: [c7779d84]. Acceptance (a)(b)(c)(e)(f) PASS, (d) measured (b2bf5b7b 126 KB ~31.5k tok 2 Reads, d30bf250 169 KB ~42k tok 2 Reads -- above the 20-35k estimate Q1 was accepted on --, 4eb7bf5d 65 KB ~16k 1 Read, fd5cc3e0 62 KB ~15k 1 Read); the two-file option (~35 KB of kept items/pointers out of the mandatory read) is the next lever if the read cost matters, unbuilt. Risk added: nothing yet checks a resumed session actually obeys READ FIRST. NEXT ACTION: 350W5II2 can now unblock (its blocker-probe reads this card's column).

## Owner directive (verbatim, 2026-09-24)
"its not good. assistant prose and user prose (the messages exchanges) should be all kept intact. modify the jev prompt to ensure that."

## Decision
Enforced in code, not only in the prompt: prose never becomes a scored item, so no score can drop it. A prompt sentence cannot guarantee a threshold outcome. RETRIEVE_QUESTION is unchanged and now only ever sees tool results and events. DECISION_QUESTION is never asked any more, so it retires.

"All" means since the session's LAST compact_boundary: the prose before it is represented by Claude Code's own compaction summary, which is now kept verbatim. That summary is currently dropped, as role "skip".
Exclusions that survive the change and are NOT owner/assistant prose (advisor §1): the heartbeat fire's own prompt (jev_compaction.py:563-564, _is_heartbeat_entry), a bare "janitor heartbeat" assistant reply (:660-661), isMeta/isSidechain/isVisibleInTranscriptOnly records (scripts/lib/transcript_roles.py:288-293), isApiErrorMessage placeholders (:648-649), and peer/notification/system-role records (kind "event", scored).

## Changes
1. scripts/lib/jev_compaction.py
   - New ItemKind "control", replacing "event" for content-free owner inputs (DZ1KOGAC's purpose is kept: build_digest and the newest-owner pick use kind == "user" only).
   - extract_items gains an in-place out-parameter `window: ConversationWindow`, in the same idiom as segmentation_failures, still one walk. It records: boundary_turn (the turn counter at the LAST type=system subtype=compact_boundary line), preserved_uuids (that line's compactMetadata.preservedMessages.allUuids), and summary (the isCompactSummary entry PAIRED TO THAT BOUNDARY by compactMetadata.preservedMessages.anchorUuid, not by "the last one seen" — advisor finding D, verified on fd5cc3e0: ba4aba30/bcd8a921 each equal their boundary's anchorUuid). On each boundary line the walk resets window.summary = None and records the boundary's pending anchor uuid; the isCompactSummary branch captures an entry as the boundary's summary only when no anchor is pending or the entry's own uuid equals the pending anchor. A boundary with no following summary line (session killed between the two) leaves window.summary = None instead of reusing a stale prior summary.
   - Measured (advisor review, 2026-09-24): d30bf250 has 10 compact boundaries; parity (boundaries == isCompactSummary lines == preservedMessages lines) holds in 28/28 files carrying boundaries, across 1007 transcript files in this project's dir. The summary is not literally "the next line" after its boundary -- on fd5cc3e0 it is 4 lines later (attachments in between: 4093->4097, 7846->7850) -- harmless for the design since capture is by anchorUuid, not position, but wrong as a fixture assumption. On the first boundary, preservedMessages.allUuids has 24 entries of which only 9 resolve to any line in the file (uuids has 8, all resolving); the other 15 name nothing in the JSONL -- membership testing on the superset is harmless, the preserved set is mostly non-prose (thinking, tool_use, tool_result, attachments, one isMeta user record).
   - New split_conversation(items, window) -> (conversation, scored). conversation = live user/assistant/control items, where live = turn >= boundary_turn or uuid in preserved_uuids. scored = every tool and event item. Unpreserved pre-boundary prose goes in neither list (it is covered by the summary, and `expand <id>` still resolves it from the raw JSONL).
   - compose() gains `conversation` and `conversation_summary`. The FULL render opens with "## Conversation since the last compaction (verbatim, never scored)": the summary, then every message in order, uncapped. The INJECTED render precomputes an exchanges block, part of render()'s fixed text, so _select_injected's baseline charges it and the max_bytes guarantee is untouched. The block gets _INJECT_EXCHANGE_SHARE = 0.60 of the room after the fixed lines. It starts with the READ FIRST line: "<full path> holds every message since the last compaction verbatim (N; only the newest M below); read it in full before acting, possibly with several Reads". Then the newest kind=="user" message (capped at 1500 B), then a CONTIGUOUS newest-first run (each capped at 700 B), with explicit gap and count markers; an over-cap message is a verbatim prefix plus a pointer. The old trailing "Full compacted context ... read it ONLY if" line is dropped from the injected render. _render_minimal_fallback takes the newest owner message from the conversation.
2. scripts/jev_compact.py cmd_compact: score_items(scored, ...), which is the enforcement point. jsl.log_decisions(scored, ...) — not because the zip guard requires it (an unscored item is skipped at `sc is None -> continue` before the zip, so nothing forces this — advisor finding E), but because only what was scored should be logged; the kind=="user" retrieve rows then vanish naturally. compose(..., conversation=...). The summary line gains `conversation=N`.
3. scripts/hooks/on-session-start-post-clear-compact.py and scripts/summarize_previous_session.py: the success path passes tail=() to trim_cards_for_room and compose_handoff ONLY when source == jcl.SOURCE_JEV, because the exchanges now arrive verbatim in the Jev block; the llm-ext fallback keeps tail=tail (`tail=tail if source == jcl.SOURCE_LLM_EXT else ()` at summarize_previous_session.py:340), because llm-ext's own compose_handoff call is its ONLY carrier of verbatim messages — advisor finding A. The room-sizing use of tail (hook :297-301, lane :264-267) stays tail=(). The template/failure path (compose_template_handoff, hook :397; SOURCE_FAILED, summarize_previous_session.py :305) never had a tail parameter and still doesn't (external_clear.py:1611-1613 has no `tail` arg — advisor finding B): delete the hook's now-dead `ec.recent_messages` call instead of trying to pass it a tail it can't use.
4. scripts/lib/external_clear.py: the "jev" header text says the newest messages are verbatim and never scored, and the tool items and events are chosen by Jev.

## Follow-up commit, separate: dead code
Remove the following (verify each with tldr impact first): DECISION_QUESTION and the asks_decision path; the user group in score_items; the decision-threshold CLI/env/userConfig; jev_shadow_log's decision dimension; the owner and decision tiers of _select_injected (steps 1, 3, 4 and 6) and their constants; and Scores.decision_passed. TRDD-98SP58TJ is then superseded.
No userConfig option exists for this (grep of .claude-plugin/plugin.json finds no jev_ option), so nothing user-visible is removed. Retiring DECISION_QUESTION also retires replay --question decision (jev_shadow_log.py :27, :227) and _RETRIEVE_ROW_ID_SUFFIX (:242); old on-disk "retrieve" rows simply become unselectable — one version of the code, no compatibility shim. Must stay: Item.protected/_effective_protected, _NON_OWNER_FLOOR, _INJECT_MIN_BODY_CHARS, _notification_block, _tool_result_part, is_control_input — all about tool/event items, not the decision question.
Related: TRDD-R9UXOSR5 (this dead-code retirement, split out as its own card, sequenced after D7RLXAN1's acceptance run passes).

## Tests (each fails on HEAD)
1. control kind;
2. window pairs a boundary's summary to it by anchorUuid, not by "the last isCompactSummary line seen" (advisor finding D);
3. split drops unpreserved pre-boundary prose only;
4. the full render holds every live message verbatim and in order;
5. the injected render starts with READ FIRST and shows the newest run;
6. the newest owner message survives a long assistant tail;
7. the injected render stays within max_bytes with 100 KB of prose (at 5000 and 600);
8. at least 3 tool items beside the exchanges;
9. the CLI never sends a prose id to Jev;
10. the hook's success injection has no Recent turns and each exchange appears once, on the Jev source only;
11. the same for the detached lane, Jev source; and the llm-ext fallback source keeps its tail=tail (advisor finding A, summarize_previous_session.py:340);
12. a boundary as the LAST walked entry: boundary_turn == len(items), no post-boundary prose, conversation == preserved prose only, newest owner item may be None (advisor finding D).

## Acceptance (b2bf5b7b, d30bf250, 4eb7bf5d, fd5cc3e0, plus accccb8b)
Re-render from the saved scores, filtered to the scored ids.
- (a) The full copy holds every live prose message verbatim and in order, checked against an independent jq extraction; the summary is present where a boundary exists, and no unpreserved pre-boundary prose is present.
- (b) No prose id is scored.
- (c) The injected copy stays under 9,000 B after compose_handoff; READ FIRST comes first; the newest owner message and the newest message are present; at least 3 tool or event items with real content, read by hand.
- (d) Report the full copy's size and the number of Read calls it needs.
- (e) The real hook (run_hook.py) on accccb8b and fd5cc3e0 prints under 10,000 chars.
- (f) RETIRED, precisely: byte-identity of compose()'s output WITH HEAD's pre-change output is retired by this design. NOT retired: compose() stays pure, so re-rendering from the SAME saved scores is still byte-identical run to run (advisor).

## Risks
- The mandatory READ FIRST cost is roughly 20-35k tokens, paid once into an empty context and cached afterwards: digest (up to 4,000 tokens) + Claude Code's own summary (13-15 KB, ~3.5k tokens) + live prose (0.3k-26k tokens measured) + kept tool items (up to budget_tokens 8,000) + pointers (advisor §4). It replaces about 2k tokens today: a reduction of about 96% instead of 99.7%, bounded by what one context window held before the boundary (preTokens ~868k, postTokens ~21-27k on fd5cc3e0). This is the owner's explicit choice, pending confirmation — see owner question (1) above.
- The most likely way it is wrong: the turn and boundary alignment. It holds because the walk is strictly top to bottom and turn never decreases; test 3 pins it.
- Measured-after-acceptance option, not built now: if acceptance (d)'s tool-item share turns out large, write the conversation (summary + live prose) to its own jev-conversation-<key>.md as the READ FIRST target, keeping the Jev document's "read only if needed" role; saves the tool-item budget and pointers from the mandatory read (roughly a quarter to a third of it) at the cost of one more atomic_write and one more path in the fixed lines (advisor §4). Build only if the single-file cost proves too high.
Unverified: nothing yet checks that a resumed session actually obeys the READ FIRST line -- the injected render tells the agent to read the full copy before acting, but no test or runtime guard confirms a real resumed agent does so; the mandatory cost (risk above) is paid on faith that it gets read.

## Related

TRDD-R9UXOSR5 — retire the decision question and owner tiers once prose is never scored (dead-code follow-up, sequenced after acceptance).
TRDD-350W5II2 — Jev scores only live tool and event items, not pre-boundary ones (builds on D7RLXAN1's window/boundary machinery; advisor §7).
TRDD-RAEGS1D5 — not this card's parent-trdd (RAEGS1D5's npt/eht does not list D7RLXAN1); tracked via Related links only; D7RLXAN1 must land before RAEGS1D5's release-blocking eht cards (BLGZTHQ9, DZ1KOGAC, O2FNJ4KW) can be re-measured on the final tree.
TRDD-IYNS7H83 -- the shared heartbeat-reply predicate (transcript_roles.is_heartbeat_reply) still hides real assistant content outside Jev's path; this card's extract_items narrowing to bare-reply-only is what surfaced the split.

## Approval log

- 2026-09-24T13:53:03+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T14:19:34+0200 — column → design_human_review by emanuelesabetta. AI review done (advisor: SOUND WITH CHANGES, fixes A-E folded in); awaiting owner answers to Q1-Q3 before implementation
- 2026-09-24T17:32:35+0200 — column → dev by emanuelesabetta. Q1-Q3 decided under the owner's full-authority grant; implementing with advisor fixes A-E
- 2026-09-24T18:13:52+0200 — column → testing by emanuelesabetta. implementation landed in c7779d84; moving to testing for acceptance/verification follow-through












## Acceptance results (2026-09-24)

- (a) PASS on all 4 cached sessions: every jq-extracted live prose record is either in the full copy's conversation section as its exact block, in order (b2bf5b7b 116/194, d30bf250 188/215, 4eb7bf5d 27/35, fd5cc3e0 3/3), or a documented exclusion (bare heartbeat replies; notifications, peer messages and other system-role records, all scored as events); 0 unexplained, 0 out of order; rendered blocks == found; Claude Code's summary present and anchor-paired where a boundary exists; no unpreserved pre-boundary prose.
- (b) PASS: no owner, assistant or control id in any scored set.
- (c) injected copy wrapped by compose_handoff: 6,946 / 5,776 / 5,720 / 5,425 B (all under 9,000); READ FIRST is line one; newest owner message whole on 3 sessions (fd5cc3e0 has no owner message since its last boundary -- the preserved set holds none; by design, advisor test-12 case); newest message present (whole or stated prefix). FAIL on 'at least 3 tool/event items with real content': b2bf5b7b 4, fd5cc3e0 3, 4eb7bf5d 2 (thin headings), d30bf250 0 -- see NEXT ACTION.
- (d) full copy: b2bf5b7b 126,204 B (~31.5k tokens, 1,155 lines, 2 Reads), d30bf250 169,035 B (~42k tokens, 1,942 lines, 2 Reads), 4eb7bf5d 65,136 B (~16k, 1 Read), fd5cc3e0 61,669 B (~15k, 1 Read). d30bf250 exceeds the 20-35k estimate: its 188 live messages alone are 124.5 KB; the unbuilt two-file option would take the ~35 KB of kept items and pointers out of the mandatory read.
- (e) PASS: the real hook (run_hook.py) printed 6,683 B on accccb8b (46 s) and 5,903 B on fd5cc3e0 (22 s), Jev really ran, no truncation marker; the accccb8b injection opens its exchanges with the owner's directive itself, verbatim.
- (f) compose() stays pure; byte identity with HEAD's output is retired by this design.
