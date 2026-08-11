---
trdd-id: JPL0JU86
title: A page no chore can ever maintain must say so — silent permanent abstention
column: todo
created: 2026-08-11T20:55:12+0200
updated: 2026-08-11T20:55:12+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#249, TRDD-G4BCRUP7]
---

# An unmaintainable page must not abstain silently

## Why (janitor#249, AgentlensPro peer — reproduced first-hand 2026-08-11)

Four pages in the USER-scope memory root are SYMLINKS resolving outside that root, into this
repo's own git-tracked PROJECT memory:

```
claude-code-{continuity-engineering,continuity-settings,esc-input-semantics,plugin-rollout-staleness}.md
  -> <this repo>/.claude/project/memory/
```

The transaction core's M-10 symlink-escape guard refuses them — correctly. The consequence is
that **no editorial chore can ever maintain those four pages from the scope they live in**, and
the content-hashed refusal that records the abstention is, for content that can never become
eligible, a permanent tombstone rather than the transient de-duplication it was designed to be.

**Cause (which the reporter could not determine, and which is recoverable only from this
repo):** all four are this project's own wikimem pages, named in its `CLAUDE.md` index. Someone
wanted knowledge that is true of EVERY project — Claude Code continuity settings, ESC input
semantics, plugin rollout staleness — recallable from every project, and reached for a symlink
instead of re-scoping the page. Correct intent, wrong mechanism.

## The two halves, and only one of them is reusable

**(a) The four pages are a one-off.** By the scope-routing rule they are machine-agnostic facts
true across all projects, so they belong at USER scope outright: MOVE them, do not link them.
If the janitor's own index still wants them, the link goes the other way. A decision about four
files, not a defect.

**(b) The silence is the defect, and it survives after (a) is fixed.** The reporter's sentence
is the load-bearing one: *a well-behaved abstention looks like success*. A chore that correctly
selects a page, correctly refuses it, correctly records a refusal, and correctly does not
re-dispatch emits exactly the same observable output as a chore that had nothing to do. Nothing
counts tombstones, so "4 of your pages are structurally unmaintainable" is discoverable only by
watching a chore abstain and wondering why.

This is the inverse of the owner's autonomy requirement, not an exception to it: the directive
says inform the main agent only about problems that only it can fix — and a page that no
automated pass can ever touch is EXACTLY such a problem. It is precisely the class that must be
surfaced, and it is the class currently guaranteed to be silent.

## What

1. **Re-scope the four pages** (move to USER scope, delete the symlinks, fix the PROJECT-side
   index links so nothing dangles). One-time.
2. **Surface permanent unmaintainability.** Distinguish a TRANSIENT refusal (unchanged content,
   already judged — the ledger's intended use) from a STRUCTURAL one (symlink escape, unparseable
   frontmatter, over-cap with a tier that forbids splitting — conditions no future content change
   will clear). Structural refusals get counted and reported; transient ones stay silent.
3. **Report through the findings ledger**, not a heartbeat print — same reasoning as R16 in
   TRDD-G4BCRUP7: a finding whose only sink is one drift line dies with the turn that missed it.

## Acceptance

- [ ] The four symlinks are gone and the pages are maintainable from their new scope
- [ ] A structurally-refused page produces a countable finding; a transient refusal still does not
- [ ] Test: a scope-escaping symlink yields exactly one finding, and a second pass over the
      unchanged corpus does NOT duplicate it
- [ ] #249 answered with the commit id
