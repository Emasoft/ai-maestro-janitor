# Commit discipline — full reference

The normative rule is `~/.claude/rules/commit-discipline.md`. This file holds the
rationale and the anti-pattern catalogue, moved here so the always-loaded rule corpus
stays under its context-floor cap (the ratchet in `tests/test_rules_installer.py`).
Nothing here is optional reading when you need the WHY — it is simply not needed on
every turn of every session.

## Why this rule exists — it is the memory system's provenance substrate

The janitor's autonomous memory maintainer (the wikimem conflict /
fact-verification pass) must, when it finds a memory whose fact is
**obsolete**, demote that fact to a dated `[^N]` lesson carrying its
**WHY** — *without ever inventing the WHY*. It sources the WHY from,
in order:

`memory.commits:` → `memory.trdd:` → that TRDD's
`implementation-commits:` → `git show <sha>` (message **+** diff **+**
the code comments at the change site).

Every link in that chain is something **you** wrote at commit time. If
you skip the WHY in the commit message and the code comments, the chain
dead-ends and the maintainer can only **demote with an empty WHY** (it
will *never* fabricate one). So this rule is the difference between a
memory system that explains its own history and one that just says
"this used to be true, reason unknown."

It is also what lets the conflict pass distinguish a **false** memory
(no trace anywhere in git history → delete) from a **superseded** one
(traceable to the commit that changed it → demote, never delete). No
git trace, no provenance ⇒ the maintainer must NOT delete — so the
absence of your commit discipline makes memories *un-prunable*, not
just un-explained.

## What this rule does NOT change

- It does **not** loosen `~/.claude/rules/never-git-add-all.md` — stage
  files **by name**, never `git add -A`/`.`/`--all`.
- It does **not** authorize pushing — committing often is local; pushing
  follows each project's own release/PR discipline.
- It does **not** ask for verbose, robotic commit prose — a WHY is one
  or two honest sentences, not a corporate template. Human-readable, like
  a senior dev would write in a real PR.

## Anti-patterns

- A one-line `fix bug` commit with no WHY and no code comment. Six months
  later nobody — human or agent — can reconstruct what bug or why that
  fix. The memory maintainer demotes the related memory with a blank WHY.
- Batching a day of unrelated changes into one commit. `git blame` then
  points every line at the same opaque mega-commit; the provenance chain
  resolves to noise.
- Writing the WHY in the commit message but not the code (or vice-versa).
  The two are read at different times by different tools — the maintainer
  reads `git show` (both), a developer reading the file reads only the
  comment. Record it in both.
