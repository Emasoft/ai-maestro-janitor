---
trdd-id: J6BET92S
title: memgrep split-mem-atom leaves the parent desc and keywords unchanged and truncates the new desc mid-word
column: backburner
status: tasked
created: 2026-09-24T19:54:59+0200
updated: 2026-09-24T19:54:59+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-24T19:54:59+0200
---

# memgrep split-mem-atom leaves the parent desc and keywords unchanged and truncates the new desc mid-word

## Symptom

Commit a5b76c68 ("docs(memory): split one over-budget atom on claude-code-continuity-engineering (janitor split chore)") ran `memgrep split-mem-atom` on `.claude/project/memory/claude-code-continuity-engineering.md`, splitting atom `^4ESPVFB8` (the six-layer never-stall stack) into two atoms. The split left two defects, both invisible to `memgrep validate`/`memgrep lint` (both ran clean on the page immediately after the split — no ERROR/WARN named either atom):

1. The ORIGINAL atom `^4ESPVFB8`'s body was narrowed to layers 1-3 only, but its `desc:` still read "The six-layer never-stall stack: settings substrate, account rotation (prevention), freeze recovery (ESC-only unstick), compaction discipline, nudging idle-armed sessions, rollout observability." and its `keywords:` still carried every layer-4-6 phrase (`janitor_backstop_versus_harness_auto_compact_competing`, `nudging_an_idle_armed_session_to_keep_working`, `keep_going_off_sentinel_to_mute_nudges`, `stale_hook_ghosts_mimic_an_unfixed_bug_after_a_shipped_fix`, `does_a_shipped_fix_apply_without_reloading_hooks`, `fleet_reachability_which_pane_can_be_injected`) — duplicated verbatim on the new second atom `^ATOM-DSGY-OJ87`, so `recall` for a layer-4-6 symptom returned BOTH atoms.
2. The NEW second atom `^ATOM-DSGY-OJ87`'s `desc:` was cut off mid-sentence: `"The last three layers of the never-stall stack: compaction discipline (janitor backstops harness auto-compact, never competes), nudging idle-armed sessions to keep going, and rollout observability (a "` — truncated at exactly 200 characters, mid-parenthetical, mid-word.

## Root cause — scripts/memgrep/src/mem_split.rs

`cmd_split_atom_cli` (scripts/memgrep/src/mem_split.rs:683) never re-tunes the ORIGINAL atom's `desc`/`keywords` by default. `split_atom_build` (mem_split.rs:544; see lines 590-602) only rewrites the original marker's `keywords`/`desc` when the caller passes `--orig-keywords`/`--orig-desc` (`SplitAtomArgs.orig_keywords`/`orig_desc`, both `Option<String>`, mem_split.rs:444-455) — when omitted, as it was in a5b76c68, the original atom's `desc`/`keywords` are left byte-for-byte unchanged even though its body just lost half its content. No warning is printed either way, and nothing detects that the split was topic-shaped (it was: layers 1-3 vs layers 4-6) rather than size-shaped.

The NEW second atom's `--desc` is rendered via `build_atom_marker` (scripts/memgrep/src/memory.rs:2358-2385, the `desc` prop at line 2368) which calls `sanitize_quoted_value` (memory.rs:2294-2300) -> `truncate_chars` (memory.rs:1664-1673). `truncate_chars` is CHAR-safe (a documented UTF-8-boundary guard: "never splits a UTF-8 boundary") but not WORD-safe: it silently takes the first 200 `chars()` regardless of word boundaries. `check_desc` (memory.rs:5162-5187) is the only validation `cmd_split_atom_cli` runs on `--desc` (mem_split.rs:688), and it enforces only a MINIMUM length (`MIN_DESC_CHARS = 24`, memory.rs:5061) — there is no maximum-length check and no warning when the silent truncation inside `build_atom_marker` actually fires.

## Why the gate missed it

`memgrep validate` and `memgrep lint` both passed clean on the page immediately after a5b76c68. Neither checks whether an atom's `desc`/`keywords` still describes the CONTENT of its own body after a split, and neither checks a `desc:` for a truncation artifact (a dangling open-parenthesis, an incomplete clause). Both defects are purely semantic, so the write-gate structurally cannot catch them — this makes the bug easy to ship again on any future split.

## Fix

1. `split_atom_build` should require (or at minimum WARN when omitting) `--orig-desc`/`--orig-keywords` whenever the split point looks topic-shaped rather than size-shaped, so the original atom's recall surface is narrowed to what it still holds instead of silently going stale.
2. `sanitize_quoted_value`/`truncate_chars` must never cut a generated `desc` mid-word: truncate at the last whitespace boundary before the 200-char cap (or refuse the write and ask the caller to shorten `--desc`) instead of silently emitting a dangling clause.

## Repro

The exact defect is preserved for review in `.claude/project/memory/claude-code-continuity-engineering.md` at commit a5b76c68 (superseded by the fix in this repo's own working tree — see the commit that lands alongside this TRDD for the corrected page).

## Approval log

- 2026-09-24T19:54:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
