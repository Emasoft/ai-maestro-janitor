---
name: janitor-write-handoff
description: Write a rich, agent-authored session handoff to .janitor/state/agent-handoff.md before a context compaction, so the post-compaction turn re-grounds from YOUR semantic account (what you were doing, the plan, the next concrete action, the traps already hit) — not just the mechanical PreCompact snapshot. Invoke for a delicate juncture where the always-on zero-cost pre-compact-handoff hook is not enough. Usually run automatically by /janitor-compact-context --handoff (which passes --then-compact so this skill chains to /compact when done); a bare /janitor-write-handoff writes the handoff and stops. Trigger with /janitor-write-handoff or by asking to write a handoff before compacting.
---

# Janitor write-handoff

## Overview

Every compaction already gets a **mechanical, zero-cost** handoff: the
`pre-compact-handoff.py` PreCompact hook writes `.janitor/state/precompact-handoff.md`
from on-disk truth (git HEAD + recent commits, working tree, in-flight TRDD `## STATE`
blocks, VERBATIM recent transcript turns). That is un-hallucinatable but **mechanical** —
it captures *what the filesystem says*, not *what you were thinking*.

This skill writes the **semantic** layer on top: a rich, agent-authored handoff to
`.janitor/state/agent-handoff.md` capturing the reasoning a snapshot can't — the plan,
the next concrete action, the load-bearing facts, the trap you already wasted time on,
the alternative you rejected and why. It is **opt-in** because authoring it costs tokens
(that is exactly why `/janitor-compact-context --handoff` is a separate, deliberate mode
— see [When to use](#when-to-use)). Reserve it for **delicate junctures**.

## When to use

- `/janitor-compact-context --handoff` invoked this skill (it typed
  `/janitor-write-handoff --then-compact` into the pane). This is the common path.
- You are at a delicate juncture — a subtle multi-step plan mid-flight, a hard-won
  mental model, a non-obvious next step — and a plain compaction summary would lose it.
- The user asks for a handoff before compacting.

Do NOT use it for routine compactions — the free mechanical handoff is enough. Do NOT
write a bloated handoff: it costs tokens to author now AND to read on resume. Be dense.

## Instructions

1. **Ensure the state dir exists** (the handoff + directive land in the project's
   janitor state dir, the same one the resume machinery reads):

   ```bash
   mkdir -p "${CLAUDE_PROJECT_DIR}/.janitor/state"
   ```

2. **Author a dense, semantic handoff** and Write it to
   `${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff.md`. Cover, in this order,
   only what a fresh post-compaction turn genuinely needs:
   - **Task + TRDD** — what you are doing and the governing `TRDD-<id8>` (so the next
     turn reads its `## STATE` block, the authoritative record).
   - **NEXT ACTION** — the ONE concrete next step, runnable as written (a command, an
     edit, a file to open). Point at durable state, never a volatile in-memory step.
   - **Plan** — the remaining steps in order, terse.
   - **Load-bearing facts / gotchas** — exact constants, the one command that works,
     the trap already hit, the rejected alternative + WHY. This is the part the
     mechanical handoff cannot produce — spend your words here.
   - **Verify** — how to confirm the work is correct (the test/lint command, the pass
     criteria).
   Keep it to what matters. Do NOT restate what `precompact-handoff.md` already has
   (git log, working tree, verbatim turns) — this handoff COMPLEMENTS that file.

3. **Record the resume pointer** so the post-compaction turn is steered to your handoff.
   Write ONE line to `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt`:

   ```text
   read .janitor/state/agent-handoff.md FIRST (rich agent handoff), then <your one-line resume tail>
   ```

   The PostCompact `post-compact-resume.py` hook reads this first line, prepends its own
   pointer to `precompact-handoff.md`, and the next heartbeat emits `[janitor-resume] …`
   — so the resumed turn reads BOTH the mechanical and the rich handoff before acting.

4. **Chain to `/compact` — ONLY if invoked with `--then-compact`.** Inspect your
   invocation arguments:
   - **Arguments contain `--then-compact`** (the hard `/janitor-compact-context --handoff`
     path): enqueue `/compact` so it runs when THIS turn ends, then stop. Run:

     ```bash
     uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py" --soft
     ```

     `--soft` (no ESC) enqueues `/compact`; no `--directive` here (step 3 already set
     the authoritative directive). Then **END YOUR TURN IMMEDIATELY** — emit one short
     line (e.g. *"Handoff written; compacting now, I'll auto-resume."*) and stop.
   - **No `--then-compact`** (a bare `/janitor-write-handoff`, or the combined
     `/janitor-compact-context --handoff --soft` where `/compact` is ALREADY enqueued
     right after this command): do NOT trigger a compact yourself. Report that the
     handoff was written and stop — if a `/compact` was enqueued behind you, it runs
     when this turn ends and reads your directive.

## Output

One short line to the user, then the turn ends. Side effects: writes
`${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff.md` (the rich handoff) and
`${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` (the one-shot resume
pointer). With `--then-compact` it also launches the detached `/compact` enqueue.

## Error handling

- `${CLAUDE_PROJECT_DIR}` unset → fall back to the git toplevel or the cwd for the
  `.janitor/state/` path; if none resolves, tell the user the handoff couldn't be
  located and stop.
- If the `compact_trigger.py` chain prints `NO_ITERM` (not an automatable terminal),
  the handoff + directive are still written — ask the user to run `/compact` manually.

## Scope

ONLY writes the rich handoff + the resume directive into THIS project's
`.janitor/state/`, and — with `--then-compact` — enqueues `/compact` on THIS session's
own pane. Does NOT compact other sessions, does NOT change plugin config, does NOT
disarm the heartbeat, does NOT overwrite the mechanical `precompact-handoff.md` (that
is written independently by the PreCompact hook and the two coexist).

## Resources

- `${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff.md` — the rich handoff this skill
  writes; read FIRST on resume, alongside `precompact-handoff.md`.
- `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` — the one-shot resume
  pointer the PostCompact hook consumes.
- `${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py` — the `/compact` trigger this skill
  chains to (`--soft`) when invoked with `--then-compact`.
- `/janitor-compact-context` — the compaction skill; its `--handoff` mode runs this skill
  first. Its `pre-compact-handoff.py` PreCompact hook writes the complementary
  mechanical handoff for free on every compaction.
