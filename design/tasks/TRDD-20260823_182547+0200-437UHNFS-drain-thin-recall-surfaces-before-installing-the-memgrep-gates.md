---
trdd-id: 437UHNFS
title: drain the corpus of thin recall surfaces before installing the memgrep metadata gates
column: dev
created: 2026-08-23T18:25:47+0200
updated: 2026-08-23T18:25:47+0200
current-owner: ai-maestro-janitor-48
task-type: infra
approval-tier: 0
scope: project
project-id: ai-maestro-janitor
implementation-commits: [3461ef6d, a7ea94c5, b4638b14, e647a37a]
---

# Drain thin recall surfaces before installing the memgrep metadata gates

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-23

- **memgrep source is DONE and GREEN.** `cargo test --release` → bin 218/218, cli 145/145
  (`e647a37a` fixed the last four fixtures). The gates themselves are settled and stay.
- **memgrep is deliberately NOT INSTALLED.** `~/.cargo/bin/memgrep` is still the Aug-22 build.
  Installing is the LAST step of this card, not the first.
- **NEXT ACTION:** add the `enrich` memory chore (see *The plan*), then let the heartbeat drain
  the corpus. Install only when all three scopes lint at 0 ERROR.
- **Do NOT run `cargo install --path scripts/memgrep`** until the drain is done. That is the
  whole point of this card.

## The decision (owner, 2026-08-23)

The metadata gates landed in `3461ef6d`: an atom or lesson needs ≥10 distinct keyphrases, a page
`description:` needs ≥15 distinct `/`-separated phrases, and duplicates are refused — a count is
a proxy for COVERAGE, so a repeated phrase inflates it without adding a way to find the memory.

Measured first-hand with the release binary on 2026-08-23, across **277 pages**:

| scope | ERROR | thin atoms | thin page descriptions | duplicated keyphrases |
|---|---|---|---|---|
| PROJECT (`.claude/project/memory`) | 186 | 137 | 44 | 4 |
| USER (plugin DATA `memory/`) | 851 | 695 | 137 | 15 |
| LOCAL (`~/.claude/projects/<slug>/memory`) | 147 | 75 | 39 | 32 |
| **total** | **1184** | **907** | **220** | **51** |

Every scope fails the default lint gate, and `dispatch.py` promotes the lint line past quiet
mode — so installing today would put an ERROR count on **every heartbeat fire, permanently**,
because no single maintenance pass can move a number that large. That is janitor#276 verbatim:
*a completed pass could not move the number, so the same line repeated forever.*

Three options were put to the owner: (1) install and ship noisy, (2) install with the two new
lint rules downgraded to WARN while the write gates stay hard, (3) **drain the corpus first,
then install**. **The owner chose (3).**

**Why (3) and not (2)** — the cheaper-looking option. (2) leaves the corpus permanently split
into a compliant new half and a silent legacy half, with nothing that ever forces the second to
converge; "drains opportunistically as pages get touched" is a hope, not a mechanism. It also
teaches the linter to under-report the exact defect it was just taught to detect, which is the
failure the severity model exists to prevent.

## The plan

1. **Add an `enrich` memory chore** — the drain mechanism. It raises thin recall surfaces:
   extends an atom's keyphrases to ≥10, a page `description:` to ≥15 phrases, and de-duplicates.
   It is EDITORIAL work (it must write phrasings a future session would actually search with, in
   the words of the SYMPTOM, not the fix), so it belongs to the existing
   `janitor-memory-subconscious-agent` as one more per-chore skill — NOT to a script. A script
   can only pad, and padding is precisely what the gate exists to reject.
2. **Let the heartbeat drain it**, one bounded scope-pass per dispatch, like every other chore.
3. **Install `memgrep` only when all three scopes lint at 0 ERROR**, then re-pin and let the
   gates go live everywhere at once.

## Acceptance criteria

- [ ] An `enrich` chore exists, is scheduled, content-prechecked, claimable, and dispatched by
      the heartbeat exactly like the existing chores.
- [ ] Its skill refuses to satisfy a count with filler — the pass is measured by recall
      coverage gained, and it says what it skipped rather than padding it.
- [ ] `memgrep lint` reports 0 ERROR on PROJECT, USER and LOCAL.
- [ ] `cargo install --path scripts/memgrep` run, and `memgrep --version` on PATH matches.
- [ ] A heartbeat fire after the install is QUIET (no promoted lint line).

## Notes

- **The write gates are not live today either.** Nothing enforces ≥10 keyphrases at write time
  until the install happens, so new pages written during the drain can still be thin. That is
  accepted: the drain pass re-lints, so anything written thin in the meantime is picked up by
  the same sweep rather than escaping it.
