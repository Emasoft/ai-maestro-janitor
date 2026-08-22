---
trdd-id: YWMKNKVT
title: Librarian notice must not carry a machine-local path; overview pages exempt from globs
column: blocked
created: 2026-08-08T12:41:58+0200
updated: 2026-08-22T12:02:05+0200
blocked-by: [stale-plugin-session-in-another-project]
pre-block-column: todo
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#243]
---

# Librarian notice channeling fix + overview-page globs exemption

## ✅ 2026-08-22 — one of the two blockers is discharged; the card stays blocked on the other

`blocked-by` listed `[TRDD-KVS6K7P9, stale-plugin-session-in-another-project]`. **TRDD-KVS6K7P9
is `column: complete`** — verified today — so it is dropped from the list.

The remaining blocker is real and NOT checkable from this repo: a session in ANOTHER project
holding an older cached plugin keeps re-writing the machine-global notice
([[claude-code-plugin-rollout-staleness]]). Nothing here can observe or clear another project's
plugin version, so this stays `blocked` rather than moving — a genuinely un-actionable wait, which
is what the column is for.

Worth pairing with today's TRDD-9T0U3M00 finding, which is the same root cause seen from the
other side: the installed plugin on THIS host is 3.3.26 while the repo is an unpushed 3.4.0. A
fleet running mixed plugin versions produces exactly this class of blocker, and the publish is
what drains it.

## Why (janitor#243, maintainer peer — measured)

1. **Channeling-class defect**: the USER-scope "MOVED" notice
   (`~/.claude/ai-maestro-janitor-memory/memory-reorg-proposed.md`) hardcodes ONE project's
   LOCAL proposal path. USER scope is read by EVERY project's session, so all but one reader
   is redirected into a foreign corpus — the peer nearly acted on another project's findings
   (26 per-project proposals exist and each is correct; only the notice lies). A machine-global
   file cannot carry a machine-local path without being wrong for all but one reader. Same
   class as [[janitor-per-project-channeling]].
2. **Page-shape FP**: the librarian flags `type: overview` scope-entry pages (SessionStart
   seeded, janitor#129) for missing `globs:`. An overview indexes a scope; it owns no file
   set — inventing a `globs:` would plant a FALSE ownership map (the peer correctly refused
   to add unjustifiable metadata; quote on file in #243).

## What

1. The notice writer prints the RESOLUTION RULE, never a literal path: "read
   `memory-reorg-proposed.md` under YOUR project's own LOCAL scope root
   (`~/.claude/projects/<your-project-slug>/memory/`)". Sweep existing notices to the new
   wording on the next librarian pass (correct in place; the old path is a wrong fact, not
   knowledge to preserve — but keep a dated lesson on the wiki page that owns the librarian).
2. The page-shape check exempts `type: overview` pages from the `globs:` requirement;
   `tier: hub` FUNCTIONALITY pages keep it. Test: an overview without globs → no finding;
   a functionality hub without globs → finding.

## ⏵ STATE — 2026-08-13: code was ALREADY done; box 3 is not, and cannot be, "corrected on the next pass"

Both code changes had landed and the card was never closed. Verified in source, not by grep
alone: `_ORPHAN_STUB` (memory-librarian.py:626) carries the resolution rule and cites #243, and
the hub check reads `tier == "hub" and page_type != "overview"` (:1219). Box 2's test exists
(`test_memory_librarian.py:727`). Box 1 had **no test** — added today.

### The live defect is still running, and the card's fix cannot end it

Measured on this host at 01:53 while working the card:

| copy | points at | mtime |
|---|---|---|
| canonical USER (`…/plugins/data/…/memory/`) | `…/projects/-Users-…-Code-**EMASOFT-ORCHESTRATOR-AGENT**/memory/…` | **01:53:11** |
| USER mirror (`~/.claude/ai-maestro-janitor-memory/`) | `…-Code-AI-MAESTRO-JANITOR-…/memory/…` | 01:45:17 |

The janitor's own log shows **this project redirected the canonical copy at 01:45:17** — and it
was overwritten again at **01:53:11**, carrying a *different project's* path. `247` redirect
lines are in that log: this is a **churn loop**, not a one-off orphan.

**The other writer is running older code.** The current writer physically cannot emit a path —
`stub = _ORPHAN_STUB.format(name=PROPOSAL_NAME)` interpolates `name` only. So a literal path in
that file can only come from a version whose stub interpolated `local_memdir`. A long-lived
session in another project holds an old cached plugin ([[claude-code-plugin-rollout-staleness]]):
plugin code is swapped at reload, not at publish.

### The real finding: this is a machine-global file with uncoordinated per-project writers

Box 3 assumes "the next librarian pass" can fix it. It cannot: our pass DID fix it and another
project's pass undid it 8 minutes later. Every project's janitor writes this one shared path with
no coordination, so correctness belongs to whoever wrote last.

This is **the same root cause recorded on TRDD-KVS6K7P9 finding 3 the same night** — a
machine-global resource (there, the USER memory root; here, the USER-scope notice) mutated by
per-project actors that cannot see each other. Two independent sightings, one defect class.
Whatever coordination primitive KVS6K7P9 lands should cover this file too, rather than each card
inventing its own.

**Not doing** the tempting hand-fix: rewriting the file by hand would be undone by the next old
pass, and it is an untracked file outside git (RULE 0) whose correction is the code's job.

## Acceptance

- [x] Notice text carries no absolute machine-local path (test greps the emitted notice) —
      `test_the_notice_never_carries_an_absolute_machine_local_path`, falsified by putting a
      literal path back into `_ORPHAN_STUB` (it failed; probe reverted). Checks POSIX, Linux and
      Windows path shapes, and asserts the resolution rule SURVIVES, so a notice cannot pass by
      going silent.
- [x] Overview exemption + functionality-hub retention both pinned by tests — pre-existing,
      `test_memory_librarian.py:727` + the `tier == "hub"` retention path.
- [ ] Existing mirror notice corrected on the next pass — **BLOCKED, and the wording is wrong.**
      Re-corrected every pass and re-broken by an older writer in another project. Ends when
      that session reloads, or when the multi-writer coordination from TRDD-KVS6K7P9 lands.
- [ ] #243 answered with the card id when it ships — queued behind the publish gate.
