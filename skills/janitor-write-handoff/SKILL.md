---
name: janitor-write-handoff
description: Write a rich SEMANTIC session handoff, composed OUT OF PROCESS by the llm-ext CLI from this session's own transcript — so the next turn re-grounds from an account of what was actually happening, not just the mechanical PreCompact snapshot, and the model spends NO tokens authoring it. MANUAL-ONLY (TRDD-RAEGS1D5 card 4) — no automatic lever calls this skill, and it never chains into a compact or clear on its own — it writes the handoff and stops. Trigger with /janitor-write-handoff, or by explicitly asking to write a handoff.
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

**MANUAL-ONLY** (TRDD-RAEGS1D5 card 3 C2): this is the sole remaining place in this plugin
that still calls `llm-ext` — the automatic SessionStart summarizer
(`scripts/summarize_previous_session.py`) was rewired onto the janitor's own `jev_compact.py`
scorer and no longer touches `llm-ext` at all. Invoking THIS skill is what still spends an
`llm-ext` call; nothing automatic does.

**It used to make the MODEL author that prose, and that was the whole cost** — tokens
spent inside the very window about to be shrunk, which is the worst possible place to
spend them. Owner directive 2026-09-03 retired that: handoff, compaction and clear work
is done by scripts, via `llm-ext` where intelligence is genuinely needed, never by an
agent writing prose. The old body of this skill is what that directive was aimed at.

## When to use

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

3. **This skill NEVER chains to anything on its own** (TRDD-RAEGS1D5 card 4: the automatic
   `--then-compact` chain to `scripts/compact_trigger.py` is retired along with that script —
   the janitor never types `/compact` again, and this manual skill does not reintroduce a
   compact path). Report that the handoff was written and stop. If you separately want to
   clear or compact after writing it, invoke `/janitor-compact-context` or `/clear` yourself,
   as its own explicit step.

## Output

One short line to the user, then the turn ends. Side effects: writes
`${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff-<session>-<ts>-<pid>.md` (the rich handoff) and
`${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` (the one-shot resume
pointer). Nothing else is enqueued.

## Error handling

- `${CLAUDE_PROJECT_DIR}` unset → fall back to the git toplevel or the cwd for the
  `.janitor/state/` path; if none resolves, tell the user the handoff couldn't be
  located and stop.
- If composing the handoff fails outright, report the failure and stop — nothing is
  chained, so there is no fallback compact/clear to warn about.

## Scope

ONLY writes the rich handoff + the resume directive into THIS project's
`.janitor/state/`. Does NOT clear or compact this or any other session, does NOT
change plugin config, does NOT disarm the heartbeat, does NOT overwrite the mechanical
`precompact-handoff.md` (that is written independently by the PreCompact hook and the
two coexist).

## Resources

- `${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff-<session>-<ts>-<pid>.md` — the rich
  handoff this skill writes, one file per write (TRDD-5RXBI65T); read FIRST on resume,
  alongside `precompact-handoff.md`. `scripts/lib/handoff_files.py --path` prints the name;
  `handoff_files.newest_group()` is how readers collect a session's handoffs in write order.
- `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` — the one-shot resume
  pointer the PostCompact hook consumes.
- `/janitor-compact-context` — the (manually-invoked) Jev-compaction skill; a SEPARATE
  tool, never chained to or from this one. `pre-compact-handoff.py`'s PreCompact hook
  writes the complementary mechanical handoff for free on every harness compaction.
