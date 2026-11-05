---
trdd-id: 11KWFU5L
title: Sweep Claude JSONL transcripts on disk and hide secrets with the shield engine
column: todo
status: tasked
created: 2026-11-05T02:58:23+0100
updated: 2026-11-05T03:06:19+0100
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
approval-datetime: 2026-11-05T02:58:23+0100
npt: [HF7GNHNF]
---

# Sweep Claude JSONL transcripts on disk and hide secrets with the shield engine

Derived from TRDD-RPHJ64W1 (owner directive 2026-11-05 quoted there). No corpus project fits: write our own TypeScript sweeper on the shield engine in hooks/secret-shield/patterns.ts, which imports only ./rules/* (checked 2026-11-05), so it can run outside the hook runtime. The sweeper owns its own JSON walker and calls redact() on every string, with no depth limit; it does not use redactDeep(), which stops at 12 levels (patterns.ts:386, TRDD-UBWU9AQC). Measured 2026-11-05: ~/.claude/projects holds 61718 jsonl files, about 52 G in total (du), 53 over 50 MiB (find -size +50M), the largest 590.5 MB (decimal), so the sweeper must stream line by line. The shield at write time covers only text and tool_result blocks of five row doors (hooks/secret-shield/rows.ts:10, patterns.ts:418-437) and is not wired yet (TRDD-2V7OAUPE); assistant text, thinking, tool_use inputs and files already on disk are not covered. URL_PASSWORD has a large slowdown step between 96 KB and 128 KB (TRDD-HF7GNHNF); at 52 GB that step decides the runtime, so HF7GNHNF is a prerequisite.

Design (ideas from the corpus, no code copied without its notice): skip a string only by its position in the record schema (for example image data under a block whose source type is base64, ids, signatures), never because its content looks like base64: many secrets are base64 (idea of a skip list: maccydee_scrub-transcripts scrub.py:400-410); stream to a new 0600 temp file in the same directory, fsync it, rename, fsync the directory (SpyMonk atomic.rs:56-122, devops247-online_shellclear safefile.go:21-52); copy unchanged lines byte for byte and parse-check every changed line; give unparseable lines the raw-text pass and report them; skip files modified in the last N minutes, recheck size and mtime before rename, or merge an appended tail (shellclear cleaner.go:225-250); marker [JANITOR-REDACTED:<kind>]; no backup that keeps the secret by default; a verify pass re-scans the result. Also list the sibling stores (history.jsonl, file-history, shell-snapshots, todos, plans, paste-cache, debug) with their existence on this machine.

Safety: --dry-run is the default. A false positive in a live run destroys non-secret text with no git copy to restore it, and no corpus of benign text exists (the general benign sample in tests/patterns.test.ts is 6 lines, besides per-rule must-stay-visible tests), so the owner judges the dry-run samples before any live run. The first live run over ~/.claude needs the owner's approval of the exact command (RULE 0 of the owner's global rules: transcripts are not in git).

## Done when
 - [ ] A dry run over a copy of the store reports per-file hit counts by kind, and per kind a masked sample list (path, JSON key path, kind, and the first and last 2 characters only for values of 16 characters or more, kind and length only for shorter ones), written to reports_dev with file mode 0600 for the owner to judge false positives.
 - [ ] A live run on a scratch copy leaves every line valid JSON, unchanged lines byte-identical, and the verify pass finds 0.
 - [ ] A second run over its own output changes nothing: a marker is never hidden again (test).
 - [ ] An interrupted run resumes per file without redoing or corrupting finished files (test).
 - [ ] A test appends to a file during the run and the file is not corrupted.
 - [ ] The largest file (590.5 MB) is processed with bounded memory (measured peak RSS), and the throughput in MB/s is measured with the projected time for the whole store.
 - [ ] A test shows re-serialising a changed line alters nothing outside the redacted strings (numbers, escapes, key order).
 - [ ] A string nested deeper than 12 levels is hidden (test).
 - [ ] The owner approves the exact live command before the first live run.
 - [ ] Signed thinking blocks are handled by a recorded decision (skip them, or accept that a swept session cannot be resumed), and claude --resume is tested on a swept copy of a transcript.
 - [ ] The sibling stores (history.jsonl, file-history, shell-snapshots, todos, plans, paste-cache, debug) are listed with their existence and size on this machine, and each is swept or excluded with a reason.

## Approval log

- 2026-11-05T02:58:23+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
