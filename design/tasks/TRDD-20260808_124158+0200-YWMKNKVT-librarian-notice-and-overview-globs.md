---
trdd-id: YWMKNKVT
title: Librarian notice must not carry a machine-local path; overview pages exempt from globs
column: todo
created: 2026-08-08T12:41:58+0200
updated: 2026-08-08T12:41:58+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#243]
---

# Librarian notice channeling fix + overview-page globs exemption

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

## Acceptance

- [ ] Notice text carries no absolute machine-local path (test greps the emitted notice)
- [ ] Overview exemption + functionality-hub retention both pinned by tests
- [ ] Existing mirror notice corrected on the next pass
- [ ] #243 answered with the card id when it ships
