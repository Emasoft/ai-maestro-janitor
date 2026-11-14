---
trdd-id: VHFGPCOJ
title: C23 — strip noqa from recall output
column: todo
status: tasked
created: 2026-10-01T19:45:14+0200
updated: 2026-11-14T15:44:33+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:14+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, VHFGPCOJ]
blocker-holds-if: not-match:READY
---

# C23 — strip noqa from recall output

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C23, wave W2.

Writes (exclusive): the recall output file per U8 (search.rs vs memory.rs; parallel with C20–C22 if U8 says search.rs)
Task: Strip noqa comments from recall output
Verify: A CLI test: a page with noqa gives recall output without it
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:07+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-01 — scope correction from C00/U8: recall output is formatted in src/memory.rs (finalize_recall ~8471, recall_one_atom ~8717, recall_one_page ~8753), so this card writes src/memory.rs and runs AFTER C22 (TRDD-JD2QR5SQ) in the memory.rs serial chain.
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-11-13 — unblocked from TRDD-JD2QR5SQ (C22): proceeds on test evidence (610f569c real-binary lock+ledger, cargo 9+64 green), not field evidence; if JD2QR5SQ's field run finds a defect, re-check this card
- 2026-11-13T20:30:41+0100 — column → todo by main-agent@ai-maestro-janitor. proceeds on test evidence (610f569c real-binary lock+ledger, cargo 9+64 green), not field evidence; see TRDD-JD2QR5SQ Cleared blocked-by (--clear-blocker override).
- 2026-11-13 — note: this card writes src/memory.rs; C22 (TRDD-JD2QR5SQ) still has undecided DECISION items (C21-(c), unused-noqa label) that may also touch memory.rs; serialize, do not run in parallel with them.
- 2026-11-13 — why todo and not blocked like EMZUVIBK: the memory.rs overlap with C22's undecided items is speculative, while EMZUVIBK's cli.rs overlap is certain (C21-(c) and the unused-noqa label would change cli.rs lint tests). Check C22's DECISION items before starting this card.
2026-11-14 DESIGN, TWO REVIEW ROUNDS SPENT, nothing built. Measured: noqa::strip (scripts/memgrep/src/noqa.rs:206) exists with no caller; recall prints at 20 sites in memory.rs 9422-9601 plus 3 in cmd_recall_cli (9671-9680); comments also reach locator lines through atom_listing_summary (memory.rs:1760, 120-char body prefix, flattened) and the page summary (memory.rs:476, first prose line without a colon); finalize_recall is shared with cmd_find_cli (10398) and cmd_prose_cli (10014). Rejected: rev 1 (wrap only the 6 content prints: misses summaries, strips rendered fragments); rev 2 (strip the whole recall output once: one unclosed or cross-result fence would invert stripping for every later result). REVISION 3 DRAFT, UNREVIEWED: strip PER RESULT block (its locator lines plus body), never across results; both summary pickers strip the body BEFORE flattening and the 120-char cut and skip comment-only lines (no dangling dash, no empty label); converted functions carry #[deny(clippy::print_stdout)] so no raw print survives the clippy -D warnings gate; every early return flushes; fixtures add an unclosed fence on one page followed by a commented page, an atom body starting with ---, and the branches --no-notes, --with-keywords, full-layer page results, empty result, jargon path. RISK, recorded and not engineered away: an agent that rebuilds a page from recalled text drops its suppressions (no write verb consumes recall output today; a --raw flag is out of C23's scope). FOR THE OWNER: (1) a third review round or build revision 3 as is; (2) should memgrep find and memgrep prose, which share finalize_recall and print page content too, also strip noqa comments, or stay byte-faithful?
2026-11-14 REVISION 3 DRAFT, completed per review: it keeps revision 2's fixtures (line-level body comment, page-level memgrep: noqa line, [^N] lesson-line comment, inline-code example, fenced example inside one atom) and its exact-output assertions (each comment and its leading whitespace removed), PLUS the added fixtures above; the three cmd_recall_cli prints (jargon warning, two section headers, 9671-9680) are emitted in order between result blocks and pass strip; #![allow(dead_code)] in noqa.rs stays unless clippy -D warnings passes without it; the find/prose answer becomes a parameter on finalize_recall.
