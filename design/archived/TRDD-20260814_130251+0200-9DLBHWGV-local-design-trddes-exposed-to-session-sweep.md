---
trdd-id: 9DLBHWGV
title: LOCAL design TRDDs live in Claude Code's swept session dir with no backup
column: complete
created: 2026-08-14T13:02:51+0200
updated: 2026-08-14T14:12:00+0200
current-owner: janitor-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
relevant-rules: []
npt: []
eht: []
implementation-commits: [c0540120]
---

# LOCAL design TRDDs live in Claude Code's swept session dir with no backup

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

**Found by the CC 2.1.213→2.1.232 changelog audit. VERIFIED first-hand, not inferred.**

**NEXT ACTION:** implement `sync_local_design_mirror()` in `scripts/lib/memory_scopes.py`,
modelled on the existing `sync_user_memory_mirror()` (same two directions, same
never-delete/fail-open discipline), mirror dir under the plugin DATA dir at
`<DATA>/local-design-mirror/<slug>/`, called from `on-session-start.py` beside the memory
mirror. Tests in `tests/test_local_design_mirror.py`.

## The evidence (verified, with the commands that produced it)

`~/.claude/projects/<slug>/` is Claude Code's own session store — it holds the session
`.jsonl` transcripts, which is what makes it the directory CC's `cleanupPeriodDays` cleanup
sweeps. Listing it shows transcripts. Alongside them:

```
find ~/.claude/projects/<slug>/design -name 'TRDD-*.md' -type f | grep -c .   ->  6
```

Six real LOCAL TRDDs sit inside the swept directory.

**CC 2.1.228** shipped: *"Fixed session cleanup deleting contents inside a project's memory
folder."* That fix is the proof of exposure, not a reassurance: cleanup **was** deleting
content inside subfolders of this directory, and only `memory/` was carved out. `design/`
has no carve-out.

USER-scope memory has a synced backup mirror at `~/.claude/ai-maestro-janitor-memory/`
(TRDD-GFT33HT9), deliberately kept OUTSIDE the data dir so it survives an uninstall.
LOCAL `design/` has **no mirror at all**.

## Why this is high severity

A TRDD is the durable record of a design decision — the thing the whole 3-pillars system
exists to preserve. Losing one is losing the reasoning behind work already done, and it is
exactly the class of loss RULE 0 exists to prevent. The loss would also be **silent**:
nothing reads LOCAL `design/` on a schedule, so a swept card is discovered only when
someone goes looking for a decision and finds nothing.

## Approach — mirror, do NOT relocate

**Chosen: mirror.** Additive, follows an established in-repo precedent, and changes no
documented contract.

**Rejected: relocating the LOCAL design root** out of `~/.claude/projects/<slug>/design/`.
That path is fixed by the global rule `~/.claude/rules/trdd-design-tasks.md`, which the USER
owns and which applies to every project on the machine. Changing it unilaterally would
re-point every existing LOCAL TRDD on the machine and silently orphan those already written.
If the user wants relocation instead, that is a Tier-3 decision and supersedes this card.

## Constraints on the implementation

- **Never delete.** The mirror is a backup, not a two-way sync with removals. A file on one
  side and not the other is COPIED, never removed from the other side. A "tidy" mirror that
  deletes is a second way to lose the same data.
- **Fail-open.** It runs at SessionStart; a mirror fault must never cost a session.
- **Outside the swept tree.** The mirror's whole value is living somewhere CC's cleanup does
  not touch — under the plugin DATA dir, never under `~/.claude/projects/`.

## Notes and lessons learned

[^1]: {id: LESSON-9DLB-01, status: active, keywords: "a bugfix changelog entry is evidence of
exposure, carve-out for one folder implies the others are exposed, storing data in another
tool's managed directory", ocd: 2026-08-14, lmd: 2026-08-14}
DO NOT read "they fixed cleanup deleting the memory folder" as reassurance, BECAUSE the fix
is proof that the sweep DOES reach inside that directory and only one subfolder was spared.
DO treat every OTHER thing you keep in a directory another tool manages as exposed until it
has its own carve-out or its own backup.
