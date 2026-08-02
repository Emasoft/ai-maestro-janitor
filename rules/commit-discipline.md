<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

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

1. **Commit often.** Small, frequent, single-purpose commits — one per
   logical change, not an end-of-session dump. That is the granularity
   at which `git log -S` / `git blame` can later pin a fact to the exact
   change that introduced it.

2. **Commit after every memory write.** Commit a memory note (a wikimem
   page, a lesson) together with the code that justifies it, or in
   adjacent commits, so the two are linked in time. This binds the
   **project code** and the **in-repo PROJECT memory**; the LOCAL/USER
   stores are not repos and persist by atomic write.

3. **Write the WHY in the commit message.** Not just *what* changed —
   *why*. What was the previous behavior, what problem did it cause,
   why is the new shape correct, what alternative was rejected and why.
   The commit body is the durable, greppable record of intent.

4. **Write the WHY in the code comments too.** At the change site, a
   short comment on *why it must be this way* — especially a fix that
   prevents a specific bug, or a non-obvious constraint. It is the
   guardrail that stops the next agent from "simplifying" the fix back
   into the bug.

Plus: **`TRDD-<8hex>` in the subject** when the change implements a
TRDD, e.g. `fix(auth): reject empty token (TRDD-9a8aba94)`. This makes
`blame → commit → TRDD` a one-grep chain, and the TRDD's
`implementation-commits:` corroborates the link from the other side.

## Why, in one sentence — and where the rest lives

The WHY you write at commit time is the **provenance substrate** the memory maintainer
reads: it demotes an obsolete fact to a dated lesson *without inventing the reason*, sourcing
it from `memory.commits:` → `memory.trdd:` → `implementation-commits:` → `git show <sha>`.
Skip it and that chain dead-ends, so a memory becomes un-prunable rather than merely
unexplained.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/commit-discipline-full.md`
> — the provenance chain in full, what this rule does NOT change (it never loosens
> `never-git-add-all.md`, never authorizes pushing), and the anti-pattern catalogue.
