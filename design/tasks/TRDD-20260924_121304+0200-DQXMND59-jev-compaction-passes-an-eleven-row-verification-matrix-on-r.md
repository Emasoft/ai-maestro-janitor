---
trdd-id: DQXMND59
title: Jev compaction passes a twelve-row verification matrix on real transcripts before release
column: todo
created: 2026-09-24T12:13:04+0200
updated: 2026-09-25T14:02:58+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: audit
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T12:13:04+0200
implementation-commits: [e23e0b39, 73df900b, 2729b1cb]
---

# Jev compaction passes a twelve-row verification matrix on real transcripts before release

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-24

Landed (e23e0b39, 73df900b, 2729b1cb, 1461e7d6, this commit): expand restores attachment items (453 of 453 on 4 real sessions); stage 2 (1461e7d6) gave extract_items and expand ONE shared existence-and-text rule for attachment entries (jc.attachment_item_text) instead of two independent copies; stage 3 (this commit) moved the shared JSONL walk OUT of jev_compaction.py into a new stdlib-only scripts/lib/jsonl_walk.py (parse_jsonl_line, iter_jsonl_entries, drop_lone_surrogates) -- extract_items and expand's _read_jsonl_entry both import it now, so both source their per-line parsing from ONE function (parse_jsonl_line); NOT yet one shared iteration though (review of stage 3's first cut, finding f): _read_jsonl_entry calls iter_jsonl_entries (the generator), extract_items still calls parse_jsonl_line directly inside its own loop, deliberately kept separate to avoid re-indenting its large per-entry state machine (pending_tool_uses, quiet_tool_use_ids, window) -- see extract_items's own comment; expand's own printed text is now also sanitized against a lone surrogate (it used to crash there even though an Item's text was already safe), and so is window.summary (found while documenting the verbatim exception -- it is not an Item, so Item.__post_init__ never touched it, and compose() writes it straight into the document); malformed_lines and segmentation_failures are both REQUIRED keywords on extract_items now; the compact summary line reports both malformed=N and segmentation_failed=N; the lane (jev_compaction_lane.py) now parses and logs a nonzero malformed=N count to session-summary.log (it already did for blocked=N). CORRECTION to 2729b1cb's commit message stands -- see TRDD-A8DRRW0I for the readers outside Jev, which can now import jsonl_walk.py directly (its own dependency on this card's stage 3 is satisfied). Stage 3's full item list: docs_dev/20260924-stage3-malformed-review-fixes.md. Stage 3b (this review pass; TRDD-350W5II2 precondition met, committed 71c7f66a): item A moved the blocked=/malformed= parse+record out of run_compact_with_fallback and into run_compact itself -- the hook on-session-start-post-clear-compact.py calls run_compact directly and never read proc.stdout, so both were silently lost on the production post-clear path (confirmed directly: a stubbed exit-0 success carrying blocked=2/malformed=3 left neither a ledger entry nor a log line on HEAD, both present after the fix); item B sanitizes compose()'s own str parameters (header's values, full_context_path, conversation_summary) with jsonl_walk.drop_lone_surrogates at ONE entry boundary, Item.__post_init__ left untouched (items are data, not parameters); item D corrected the invented "PEP 3.11" citation to CVE-2020-10735/sys.set_int_max_str_digits; item E pins parse_blocked_summary/parse_malformed_summary against cmd_compact's real field order; item G reworded jsonl_walk's module docstring ("intended for every transcript reader ... used today by extract_items and expand"); item H switched drop_lone_surrogates's slow path to a compiled re.sub; _extract_block's docstring now states its verbatim guarantee's one exception (a lone surrogate becomes U+FFFD, via cmd_expand's own drop_lone_surrogates call). 512->513 tests (3 new: hook blocked/malformed, compose sanitization, parse-shape pin); ruff/mypy/pyright clean. Full detail: docs_dev/20260924-stage3b-spec.md.

Owner, 2026-09-24: "continue testing the jev compaction, make it flawless". Release gate for TRDD-RAEGS1D5. The matrix gates the release only after TRDD-BLGZTHQ9 and TRDD-U6C3YXEL have landed and been re-measured: until then V1's "no injected tool item is a truncated prefix" fails by design.

| id | what | pass condition |
|---|---|---|
| V1 | 7 real transcripts spanning sizes: ~0.3 MB, 6.4 MB (b2bf5b7b), 17 MB (fd5cc3e0), 49 MB (d30bf250), 96 MB (35e1e917), 183 MB (c8a95d7e), 258 MB (4eb7bf5d) | per run: exit 0, source jev, final hook stdout < 10,000 B, not sliced, wall < 60 s, newest real owner message present, no injected tool item is a truncated prefix, the path appears once |
| V2 | every pointer in the injected AND full copies expanded with the exact trailer command; every "--list --grep" instruction run as worded | exit 0 and non-empty original text for each; zero failures |
| V3 | the real SYNC hook (scripts/hooks/on-session-start-post-clear-compact.py) end to end with a real sidecar and SessionStart payload | its stdout is what gets injected; same limits as V1 |
| V4 | the DETACHED lane (scripts/summarize_previous_session.py --transcript) end to end | handoff file written in the scratch state dir; same limits |
| V5 | timing variance: the 258 MB run 3 times | every run under 60 s; report min/max |
| V6 | failure paths: bad key (401/402/403), 429 with Retry-After, 5xx, network down, a firewall-blocked batch | the documented retry-then-fallback behaviour; never a crash, never a silent empty injection; the template handoff when both fail |
| V7 | edge transcripts: empty file, one owner message, tool calls only, one 5 MB tool result, non-UTF-8 bytes, a truncated last line, base64 images | exit 0 or a clean, named decline; never an exception; never an over-budget output |
| V8 | determinism: the same transcript twice with cached scores | identical selection and card-list order |
| V9 | isolation: run from the scratch dir | no file written under the real repo's .janitor/state |
| V10 | the content read by hand for every V1 run | a resumed session can tell (a) the owner's last request, (b) what the session did, (c) what is next; every stated owner decision is inline or pointed at |
| V11 | the cards section (TRDD-O2FNJ4KW) | the cards the session worked are listed first; the other open ids are named as many as fit in the capped line (ids part 300 B, line about 340 B), then the rest are counted |
| V12 | the no-sidecar fallback (scripts/hooks/on-session-start.py) end to end: a clear flag, NO per-pane sidecar, and a foreign or legacy handoff as the newest file in the state dir | stdout is a pointer line naming that handoff, never its body (the path 5fba6c67 changed; TRDD-4P4Y2KBR) |
- 2026-09-25 13:50 — the full suite (no -x, clean tree 52c87cbb) is green: 17540 passed, 2 skipped. V3 and V12 remain to be run on this commit; results land here.
- 2026-09-25 14:10 — V3 and V12 PASS on commit 52c87cbb via the existing scripts_dev/jev_verify harness (run_hook.py on real transcripts c8a95d7e 6.5s/5725B, d30bf250 4.4s/7959B, 35e1e917 5.0s/6983B — every assertion true, no truncation markers, live state untouched; run_v12.py all four assertions true). Full suite green (17540 passed, 2 skipped, no -x). MATRIX COMPLETE on this commit. Remaining is the owner decision recorded in the 2026-09-24 13:41 CURRENT line: reconcile whether the matrix gates the release only after BLGZTHQ9+U6C3YXEL re-measure, or ships after F1b+F3+one full run (the owner was told the latter). NOT published until the owner's explicit yes.

## Approval log

- 2026-09-24T12:13:04+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Release checklist

- [ ] The installed ~/.claude/rules/janitor-heartbeat-protocol.md still carries the old STATE_DIR recipe (f0eb0848 moved it into a code block below the heartbeat table in the repo's rules/janitor-heartbeat-protocol.md; on 2026-09-24 the two files differ). The release must install the repo's rule; check: the installed copy is byte-identical to the repo's after the upgrade.

## Notes

V5 baseline (one developer machine, 2026-09-24, from the previous session's measurement): on the 258 MB transcript the sync lane spent about 46.5 s in the compose plus about 4.7 s in state_head_paths, roughly 51 s of run_compact's 60 s bound, about 9 s of headroom; a slower host can exceed it. V5 must be re-measured on the final tree before this row can pass.



DROPPED 2026-09-24: an earlier append-only STATE entry here first stated "about 20 hooks" affected, then corrected it to "9 files"; both counts were superseded by TRDD-A8DRRW0I's own read-and-classify pass, which narrowed the real scope further (see that card). The current STATE is the block right after the title.


## Related

TRDD-A8DRRW0I -- sweeps the transcript JSONL readers outside Jev (scripts/lib/external_clear.py and the json.loads(line) hooks) onto the same shared byte-safe walk this card's extract_items/expand fix introduced.
