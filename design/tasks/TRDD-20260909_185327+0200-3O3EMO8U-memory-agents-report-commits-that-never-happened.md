---
trdd-id: 3O3EMO8U
title: The memory subconscious agent reports commits that never happened
column: todo
created: 2026-09-09T18:53:27+0200
updated: 2026-09-09T18:53:27+0200
current-owner: session
task-type: bugfix
scope: project
min-approval-requirement: none
---

# The memory subconscious agent reports commits that never happened

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-09

Finding is VERIFIED first-hand by diff, not relayed. Nothing fixed yet. No code read yet.

NEXT ACTION: read the agent's commit path (`janitor-memory-subconscious-agent` +
the memgrep write verbs it drives) and determine whether it (a) never calls git,
(b) calls git and swallows a failure, or (c) commits to somewhere that is not the
working tree. Then either make it commit, or make it stop claiming it did.

Uncommitted work is still sitting in the working tree at the time of writing —
5 pages, +25/-5. Decide whether to commit it before touching the agent.

## What was measured

Two background dispatches of `ai-maestro-janitor:janitor-memory-subconscious-agent`
ran against PROJECT-scope memory on 2026-09-09:

| dispatch | self-report |
|---|---|
| atomize (~2.7 h, 61 tool uses, 285k tokens) | "5 pages atomized (20 new atom markers), PROJECT scope, **all commits clean (0 retries)**, validate NONE / lint no ERRORs" |
| repair (~5 min, 46 tool uses, 264k tokens) | "12 atom `desc:` props trimmed to <=200 chars across 4 pages (**4 transactions, all verify PASS**)" |

Verified by `git status` + `git diff` after both reported completion:

- `git log` HEAD **had not moved** since before either dispatch.
- 5 PROJECT memory pages dirty in the working tree, `+25 / -5`.
- The 25 insertions are 20 atom-marker lines + 5 bumped `lmd:` lines; the 5
  deletions are the 5 superseded `lmd:` lines. Nothing else.
- All 20 atom `desc:` values measure 158-199 chars — under the 200 cap, clustered
  just beneath it, which is the signature of a real trim-to-cap pass.

So **the curation work is real and correct**; only the commit claim is false.

## The defect

"all commits clean (0 retries)" is not a statement about git. Either the agent
never commits and the phrase describes its internal transaction core, or it
attempts a commit and the failure is swallowed. Both are bugs, and they differ
only in where the fix goes.

Why it matters beyond tidiness:

- PROJECT memory is git-tracked and pushed. Uncommitted curation is invisible to
  every other clone and dies with an unlucky checkout.
- `~/.claude/rules/commit-discipline.md` requires a commit after every memory
  write, precisely so the WHY is captured while the agent that knows it still exists.
- The false claim is **self-concealing**: a session that relays the self-report
  (as this one initially did) records "committed, clean" and never looks. The
  work stays uncommitted indefinitely and nothing reports a problem.

## Acceptance

- [ ] Root cause identified: does the agent call git at all, and if so what happens?
- [ ] The agent either commits its writes, or its report stops claiming it did.
- [ ] The word "transaction" in its report is distinguished from a git commit, in
      whatever text a future session will read.
- [ ] A test that fails if the agent reports a commit that git does not show.
- [ ] The 5 currently-dirty pages are committed (separately, before the fix).

## Notes

Caught only because a review fork challenged the relay of a sub-agent self-report
(`~/.claude/rules/decide-on-facts.md`). The generalizable lesson — an agent's
report is evidence that it RAN, never evidence that it SUCCEEDED — belongs in the
memory corpus, not in this card.
