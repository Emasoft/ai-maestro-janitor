---
name: janitor-write-handoff
description: Write a rich SEMANTIC session handoff before a context compaction, composed OUT OF PROCESS by the llm-ext CLI from this session's own transcript — so the next turn re-grounds from an account of what was actually happening, not just the mechanical PreCompact snapshot, and the model spends NO tokens authoring it. Usually run by /janitor-compact-context --handoff (which passes --then-compact so this chains to /compact when done); a bare /janitor-write-handoff writes the handoff and stops. Trigger with /janitor-write-handoff, or by asking to write a handoff before compacting.
---

# Janitor write-handoff

## Overview

Every compaction already gets a **mechanical, zero-cost** handoff: the
`pre-compact-handoff.py` PreCompact hook writes `.janitor/state/precompact-handoff.md`
from on-disk truth (git HEAD + recent commits, working tree, in-flight TRDD `## STATE`
blocks, VERBATIM recent transcript turns). That is un-hallucinatable but **mechanical** —
it captures *what the filesystem says*, not *what was being worked out*.

This skill adds the **semantic** layer on top, and it is **also zero model cost**:
`scripts/compose_agent_handoff.py` summarizes this session's own transcript through the
`llm-ext` CLI, out of process, and writes
`.janitor/state/agent-handoff-<session>-<ts>-<pid>.md`.

**It used to make the MODEL author that prose, and that was the whole cost** — tokens
spent inside the very window about to be shrunk, which is the worst possible place to
spend them. Owner directive 2026-09-03 retired that: handoff, compaction and clear work
is done by scripts, via `llm-ext` where intelligence is genuinely needed, never by an
agent writing prose. The old body of this skill is what that directive was aimed at.

## When to use

- `/janitor-compact-context --handoff` invoked this skill (it typed
  `/janitor-write-handoff --then-compact` into the pane). This is the common path.
- You are at a delicate juncture — a subtle multi-step plan mid-flight, a hard-won
  mental model, a non-obvious next step — and a plain compaction summary would lose it.
- The user asks for a handoff before compacting.

**The old "reserve it for delicate junctures, it costs tokens" caveat is RETIRED** — it
described the model-authored path. One `llm-ext` call is not a reason to ration this.
The remaining reason to prefer the free mechanical handoff alone is that a routine
compaction rarely needs the semantic layer, not that asking for it is expensive.

## Instructions

1. **Compose it — ONE command, and you author nothing.**

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compose_agent_handoff.py" \
     --project-root "${CLAUDE_PROJECT_DIR:-$(pwd)}"
   ```

   The script summarizes THIS session's own transcript through the `llm-ext` CLI —
   out of process, at zero model cost — then writes the handoff to its own
   `agent-handoff-<session>-<ts>-<pid>.md` and records the resume directive. Owner
   directive 2026-09-03: handoff and compaction work is done by scripts, never by an
   agent authoring prose inside the very window it is about to shrink.

   **Never Write a handoff by hand, and never to `agent-handoff.md` itself.** That fixed
   path had several independent writers and no coordination, so one silently destroyed
   another — measured twice in two days (TRDD-5RXBI65T). The script goes through
   `handoff_files.write`, which is the only writer; readers load the whole group in write
   order, so nothing is lost by there being more than one.

2. **Branch on the FIRST WORD of stdout:**

   | token | meaning | what to do |
   |---|---|---|
   | `HANDOFF_READY <bytes>` | written, directive recorded | proceed to step 3 |
   | `SUMMARY_FAILED <reason>` | `llm-ext` absent or failing | NOT an error — the free mechanical `precompact-handoff.md` still covers the resume. Say so in one line and proceed. |
   | `NO_TRANSCRIPT` | no transcript resolved for this project | report it; nothing was written |

   **Do NOT fall back to authoring the handoff yourself on `SUMMARY_FAILED`.** That is the
   cost this skill exists to remove, and the mechanical handoff already carries git state,
   the working tree, the in-flight TRDD `## STATE` blocks, and verbatim recent turns.

3. **Chain to `/compact` — ONLY if invoked with `--then-compact`.** Inspect your
   invocation arguments:
   - **Arguments contain `--then-compact`** (the `/janitor-compact-context --handoff
     --hard` path): enqueue `/compact` so it runs when THIS turn ends, then stop. Run:

     ```bash
     uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py"
     ```

     The trigger's default is soft/enqueue (no ESC, TRDD-0GPQROC1); no `--directive`
     here (step 1's script already wrote the authoritative directive). Then **END YOUR TURN
     IMMEDIATELY** — emit one short line (e.g. *"Handoff written; compacting now,
     I'll auto-resume."*) and stop.
   - **No `--then-compact`** (a bare `/janitor-write-handoff`, or the combined
     `/janitor-compact-context --handoff` where `/compact` is ALREADY enqueued
     right after this command): do NOT trigger a compact yourself. Report that the
     handoff was written and stop — if a `/compact` was enqueued behind you, it runs
     when this turn ends and reads your directive.

## Output

One short line to the user, then the turn ends. Side effects: writes
`${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff-<session>-<ts>-<pid>.md` (the rich handoff) and
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

- `${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff-<session>-<ts>-<pid>.md` — the rich
  handoff this skill writes, one file per write (TRDD-5RXBI65T); read FIRST on resume,
  alongside `precompact-handoff.md`. `scripts/lib/handoff_files.py --path` prints the name;
  `handoff_files.newest_group()` is how readers collect a session's handoffs in write order.
- `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` — the one-shot resume
  pointer the PostCompact hook consumes.
- `${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py` — the `/compact` trigger this skill
  chains to (soft/enqueue default) when invoked with `--then-compact`.
- `/janitor-compact-context` — the compaction skill; its `--handoff` mode runs this skill
  first. Its `pre-compact-handoff.py` PreCompact hook writes the complementary
  mechanical handoff for free on every compaction.
