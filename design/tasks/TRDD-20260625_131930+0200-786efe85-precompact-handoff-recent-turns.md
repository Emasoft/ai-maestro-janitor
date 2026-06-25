---
trdd-id: 786efe85-c650-422d-9eda-3724fa0dca29
title: PreCompact handoff also carries the last N verbatim user-assistant turns
column: published
created: 2026-06-25T13:19:30+0200
updated: 2026-06-25T13:55:36+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
priority: 3
severity: MEDIUM
effort: S
labels: [hooks, precompact, anti-hallucination, handoff]
task-type: feature
parent-trdd: TRDD-fe45babc
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
runtime-targets: [macos, linux]
last-test-result: pass
last-test-at: 2026-06-25T13:49:00+0200
test-failures: 0
implementation-commits: [f227c2d]
published-version: 0.24.3
published-at: 2026-06-25T13:55:36+0200
external-refs: []
---

# TRDD-786efe85 — PreCompact handoff carries the recent verbatim conversation

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

### STATUS: COMPLETE — implemented, tested (23/23), shipping via publish.py
Both handoff enhancements are built, tested (`tests/test_precompact_handoff_hook.py`,
real subprocess, no mocks — 23/23), ruff-clean, pyright 0/0/0, and verified against the
REAL 164 MB session transcript + the live memory corpus.

**Shipped — two new handoff sections:**
1. `## Recent conversation` (Req A) — `_recent_turns(transcript_path, n=5)` tail-reads the
   transcript, filters heartbeat / meta / sidechain / tool-only turns, keeps each user/
   assistant turn's text (≤1500 chars), newest last. VERBATIM raw messages, NOT the summary.
2. `## Recent memory changes` (Req B) — `_recent_memory_atoms` lists the most-recently-updated
   memory pages (24 h, top 8) with atom IDs only; >5 atoms → collapse to the FILE+count; a
   prose page → filename. Scope-labelled `[LOCAL|PROJECT|USER]`, de-duped by resolved path.

**Load-bearing fixes found by running against REAL data (verify-before-report):**
- *All-ASSISTANT window* — a long autonomous assistant streak pushed the user's last ask off a
  pure last-5 window; `_recent_turns` now PREPENDS the most-recent user turn so the handoff
  always shows WHAT WAS ASKED.
- *2 MB tail* (was 512 KB) — the driving user-text turn sat ~800 KB from EOF (the log is 164 MB;
  user turns are sparse, dwarfed by tool_result/assistant turns). 512 KB held zero user text.
- *Exclusions (correctness + PRIVACY)* — skips detector artifacts (`MEMORY.md`,
  `memory-reorg-proposed.md`, `memory-index.md`) and NEVER lists the PRIVATE `user-mem/` store
  (the handoff is agent-read; user-mem is agent-invisible by design — listing it would leak it).

**FOLLOW-UP (NEW user request 2026-06-25 — its OWN TRDD):** add a `desc` atom-metadata field
(≤64 chars, a concise title) so memgrep shows a one-line summary in search results AND the
handoff can show `id — desc` (no memgrep round-trip per recent memory). MULTI-COMPONENT (atom
block-property grammar — `desc` is a PHRASE, exempt from the space-split-into-array rule the
other keys use — + memgrep Rust parse/display + the handoff render + authoring skills + docs).
The handoff `id — desc` rendering lands with that feature; THIS TRDD stays id-only.

### The gap (USER-reported, VERIFIED)
`scripts/hooks/pre-compact-handoff.py` builds the handoff from ONLY filesystem/git/TRDD
state (git HEAD + last 12 commits + `git status --short` + plugin version + the in-flight
TRDD `## STATE` blocks). It captures PROJECT state but **drops CONVERSATIONAL state** — the
verbatim recent user↔assistant exchange. After a compaction, the only record of "what the
user just asked / what I just answered" is the LOSSY summary; the "un-hallucinatable" anchor
says nothing about it. The USER asked it to "at least include the last 5 messages between
claude and the user."

**Why this is consistent with the hook's anti-hallucination purpose (not a violation of it):**
the hook avoids *summary prose* because the summary is lossy. But raw transcript MESSAGES are
**verbatim ground truth**, not a summary — so including the last N verbatim turns is exactly
the kind of un-hallucinatable anchor the hook exists to provide. The original design
over-corrected to "no transcript at all".

### THE FIX
Add ONE new section to the handoff, sourced from the PreCompact payload's `transcript_path`
(already delivered to the hook on stdin; today only `cwd`/`trigger` are read from it):

`## Recent conversation (last N turns — VERBATIM transcript, more reliable than the summary)`

- Parse the transcript JSONL; walk from the END backward collecting the last **N=5** GENUINE
  conversational turns (user text + assistant text), newest last in the rendered output.
- **Filter the noise** (so the 5 slots hold real exchange, not cron spam):
  - SKIP `user` turns whose text starts with `[janitor-heartbeat]` (the cron prompts) — and
    other bare janitor markers — they are not user conversation.
  - SKIP turns that are PURELY tool_use / tool_result with no human/assistant prose; for an
    assistant turn mixing text + tool calls, keep the TEXT, drop the tool blocks.
  - Collapse a turn's content blocks to their text; note elided tool activity tersely as
    `[+ tool calls elided]` rather than dumping tool JSON.
- **Bound it:** each turn truncated to `MAX_TURN_CHARS` (≈1500) with a `… (truncated)` marker;
  the whole section capped. Keeps the handoff small even when a message was huge.
- **FAIL-OPEN (cardinal rule — same as the rest of the hook):** missing/unset `transcript_path`,
  unreadable file, malformed JSONL, or any exception → emit the section header + a single
  `(recent conversation unavailable)` line and continue. NEVER raise, NEVER block compaction,
  NEVER exit non-zero. A best-effort partial parse (some lines bad) still renders what it could.
- The faithfulness instruction is amended: the verbatim turns are MORE reliable than the
  summary, but they are RECENT-ONLY (not the whole history) — re-ground on them + the disk
  sections, not on the summary.

### DERIVED TASKS (consequences to handle)
1. **Transcript schema robustness.** The Claude Code transcript JSONL line shape is not
   contractually fixed — parse DEFENSIVELY: tolerate `message.role`/`message.content` vs
   top-level `role`/`content`, content as a string OR a list of `{type,text|...}` blocks,
   and unknown block types (skip them). One bad line must not abort the walk.
2. **Size/perf.** Do NOT read the whole transcript into memory if it is large — read the tail
   efficiently (the file can be many MB); collecting only the last few turns must not stat-bomb
   or OOM. (Read all lines is acceptable for the bounded sizes seen, but cap the bytes scanned.)
3. **No new blocking surface.** The new parse runs inside the existing top-level try/except that
   already guarantees exit 0; assert the new helper is itself exception-proof so a parser bug
   can never reach the (already safe) outer guard as anything but a degraded section.
4. **Privacy/footprint.** The handoff lives in gitignored `.janitor/state/` (local only, never
   pushed) — conversation text there is fine (same locality as the rest of the handoff). No new
   leak surface; do NOT echo the handoff anywhere it could be committed.
5. **Tests** (`tests/test_precompact_handoff_hook.py`, real — no mocks): a transcript fixture →
   the section renders the last 5 genuine turns, newest last; heartbeat-cron user turns are
   excluded; a tool-only turn is excluded / its text-portion kept; an over-long turn is
   truncated; a MISSING/CORRUPT transcript_path → `(recent conversation unavailable)` + exit 0
   (fail-open) + the rest of the handoff still present.
6. **Docs.** Update the hook docstring's section list + the README/CLAUDE.md mention of the
   handoff contents if they enumerate the sections.

### NEXT ACTION
SHIPPED in **v0.24.3** (feature commit `f227c2d`, release `adfda76`, tag `v0.24.3`, pushed
2026-06-25). Release CI finalizing the binaries. Follow-up `desc` field tracked in
TRDD-056384eb. This TRDD is terminal (published).

## Why this TRDD exists
USER reviewed the handoff content on 2026-06-25 and identified that it omits the recent
conversation — a real gap for an anti-hallucination handoff. One TRDD per change.
