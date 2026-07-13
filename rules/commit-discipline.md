<!-- ai-maestro-janitor:installed-rule — copied into your rules dir by the ai-maestro-janitor
     plugin. SAFE TO REMOVE if the plugin is uninstalled; removing it never affects any MEMORY
     store, only this rule file. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active.** Check (cheap `$HOME` stats),
> where `DATA` = `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`:
> **UNINSTALLED** (`DATA` absent) → this file is an orphan the plugin could not remove: treat as
> INERT and tell the user they may delete it — but NEVER any MEMORY store, only this rule file, and
> only with their ok. **DISARMED** (`DATA/global-state/kill-switch.flag` or legacy
> `~/.claude/janitor-global-state/kill-switch.flag` exists) → the janitor is intentionally stopped:
> INERT this session. **ACTIVE** (otherwise) → apply the rule below.

# Commit discipline — record the WHY, at commit time, in two places

**Rule (applies to every agent, every project):** commit **often**, and
**after every memory write**; and capture the **WHY** of each change in
**BOTH** the **commit message** AND the **code comments** at the change
site. Put the governing **`TRDD-<8hex>`** (when there is one) in the
commit **subject**.

This is not bookkeeping for its own sake. The WHY of a change can only
be written by the agent that *made* it — that agent is the only one who
knows why the code is the way it is. The moment the change is committed
without its WHY, that knowledge is **gone**: a future session can only
*guess*, and a guessed WHY is a hallucinated WHY. So the WHY must be
recorded **now**, by **you**, at the point of change.

## The four obligations

1. **Commit often.** Small, frequent, single-purpose commits. A commit
   per logical change, not a end-of-session dump. Frequent commits are
   the granularity at which `git log -S` / `git blame` can later pin a
   fact to the exact change that introduced it.

2. **Commit after every memory write.** When you write or update a
   memory note (a wikimem page, a lesson), commit the related code +
   the memory together, or in adjacent commits, so the memory and the
   commit that justifies it are linked in time. (LOCAL/USER memory
   stores are not git repos — this obligation is about the **project
   code** and the **in-repo PROJECT memory**, persisted by commit; the
   non-repo memory stores persist by atomic write.)

3. **Write the WHY in the commit message.** Not just *what* changed —
   *why*. What was the previous behavior, what problem did it cause,
   why is the new shape correct, what alternative was rejected and why.
   The commit body is the durable, greppable record of intent.

4. **Write the WHY in the code comments too.** At the change site, a
   short comment explaining *why it must be this way* (especially for a
   fix that prevents a specific bug, or a non-obvious constraint). The
   Bug-Autopsy directive applied to every change: the comment is the
   guardrail that stops the next agent from "simplifying" the fix back
   into the bug.

Plus: **`TRDD-<8hex>` in the subject** when the change implements a
TRDD, e.g. `fix(auth): reject empty token (TRDD-9a8aba94)`. This makes
`blame → commit → TRDD` a one-grep chain, and the TRDD's
`implementation-commits:` corroborates the link from the other side.

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
