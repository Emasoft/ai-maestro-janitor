---
name: janitor-handoff-and-clear
description: Harvest the session's material state into wikimem, write a CONCISE LINK-ONLY handoff (an index of [[wikimem]]/ATOM-id/TRDD links, never inlined content), then /clear this session and bootstrap the fresh one to re-arm the heartbeat and resume from the handoff. Prefer over /janitor-compact-context when the in-flight work is fully captured in TRDDs/wikimem/files already — /clear resets to base-context with NO residual summary (cheaper steady-state than /compact) but is UNRECOVERABLE, so the handoff must be complete first. Trigger with /janitor-handoff-and-clear, or by asking to hand off and clear.
---

# Janitor handoff-and-clear

## Overview

`/compact` keeps a session going across a context ceiling, but it drags a
compaction **summary** forward in the transcript forever after. `/clear` resets to
**base-context only** — no residual summary, cheaper in steady state — but it is
**UNRECOVERABLE** (no scrollback, no summary) and it **destroys the session-scoped
heartbeat cron** (only `--resume`/`--continue` restores a cron, never `/clear`).

This skill makes `/clear` safe to use as a continuity primitive: it captures
everything the next session needs into durable storage FIRST, fires `/clear`, then
types a bootstrap into the fresh pane that re-arms the cron and resumes from the
persisted handoff.

**The memory system IS the payload store; the handoff is only a short INDEX of
pointers.** The resumed session's first read is the tax this primitive pays every
time — it must not become a second bloated context. So the handoff is
**concise-but-exhaustive**: it mentions ALL material state, but every big chunk is
REPLACED with a LINK (a `[[wikimem-page]]`, an `id:ATOM-xxxx-xxxx`, a `TRDD-<id8>`,
a `#issue`) into already-harvested storage, never inlined. The resumed session pulls
each detail on demand via `memgrep recall` only when it actually needs it.

## When to use

- The in-flight work is **already fully captured** in TRDD `## STATE` blocks, wikimem
  pages, and files — so a `/clear` loses nothing that a link can't recover.
- You want the cheaper steady-state of base-context (no compaction summary riding
  forward) and the work is durably written down.

Prefer `/janitor-compact-context` instead when there is **live scratch reasoning not
yet durably written** — `/compact` keeps a summary; `/clear` does not. If in doubt,
compact. `/clear` is unrecoverable: once it runs there is no second chance to recover
missed state.

## Instructions

### 1. PRECONDITION — harvest material state into wikimem FIRST

This step is not optional. A link to an atom that does not exist yet is not a
pointer, it's a **lost fact** — the handoff would be concise but no longer exhaustive.
Before writing any handoff, ensure every piece of material session state is captured
into durable storage:

- **Decisions made this session, non-TRDD facts, hard-won mental models, rejected
  alternatives + why** → capture as wikimem atoms/pages now, via `/janitor-memory-write`
  (or `/janitor-memory-record-recent` to harvest recent changes). RECALL first
  (`/janitor-memory-recall`) so you UPDATE the page that owns the subject rather than
  duplicate it.
- **In-flight task state** → it belongs in the governing TRDD's `## STATE` block
  (authoritative, and already surfaced on the next SessionStart by
  `on-session-start-trdd-state.py`). If the STATE block is stale, update it now.
- **Pending questions for the user, open issues** → a wikimem note or a GitHub `#issue`.

If material state is NOT yet harvested and you cannot harvest it now, **STOP and use
`/janitor-compact-context` instead** — `/compact` preserves a summary, so it is the
safe choice when knowledge isn't durably written yet.

### 2. Write the CONCISE, LINK-ONLY handoff

Author a short index and Write it to
`${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff.md`. Rules:

- **Link, never inline.** Every big chunk of information is a LINK to where it durably
  lives: `[[wikimem-page]]`, `id:ATOM-xxxx-xxxx`, `TRDD-<id8>`, `memgrep recall
  "<symptom>"`, `#issue`. A line like *"decided X because Y — see ATOM-xxxx-xxxx"* is
  correct; pasting the full Y reasoning inline is NOT, even if Y is short.
- **Exhaustive by REFERENCE.** Omit nothing material — every open issue, pending
  decision, and in-flight task gets a line: what it is + a pointer to the detail. The
  detail is read on demand; the handoff is the table of contents.
- **Do NOT duplicate TRDD `## STATE` blocks.** They are already surfaced on the next
  SessionStart. Point at the `TRDD-<id8>`; don't restate its STATE.
- **Cover, terse:** the in-flight TRDD id(s) + one line each; the ONE concrete NEXT
  ACTION (runnable as written, pointing at durable state); each open issue + its
  pointer; any decision/fact NOT already in a TRDD/file → its wikimem link.
- **Target a few hundred bytes to low KB** — never the tens-of-KB a compaction summary
  runs. `clear_trigger.py` WARNS on stderr if the handoff is over-budget, has no
  references, or inlines a large fenced block.

### 3. Snapshot ground truth for the cross-/clear verification

Run the `before` phase — it records the current cron id, live context size, the
handoff's byte size + `[[link]]` list, and the log tails into
`.janitor/state/handoff-clear-verify.json`, which SURVIVES `/clear`. This is what
lets the resumed session PROVE (not infer) that `/clear` destroyed and re-armed the
cron, collapsed the context, and left a recoverable handoff:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/handoff_clear_verify.py" --phase before
```

### 4. Fire the trigger

`clear_trigger.py` persists the resume state (writes `resume-directive.txt` AND the
`resume-after-clear.flag` marker), validates the handoff, then injects the two-phase
keystroke sequence into THIS pane. Give it a `--directive` whose FIRST instruction is
to run the verification `after` phase (so the proof completes automatically on
resume), then to read the handoff and resume:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/clear_trigger.py" \
  --directive "run handoff_clear_verify.py --phase after FIRST, then read .janitor/state/agent-handoff.md (link-only handoff) and continue TRDD-<id8> — read its STATE block"
```

Read the result:
- `DIRECTIVE_WRITTEN` + `CLEAR_MARKER_WRITTEN` → the resume state is persisted (this
  is what survives `/clear`).
- `CLEAR_FIRED` → `/clear` is queued at your pane, and the bootstrap (`/janitor-arm`
  then `/janitor-resume`) is queued to land after `/clear` completes. Proceed to
  step 5.
- `USER_PRESENT` → you are at the keyboard; nothing was typed (it would clobber your
  input and wipe your session). The resume state is still recorded — run `/clear`
  then `/janitor-arm` yourself when ready.
- `NO_ITERM` → this session is not in an automatable terminal (iTerm or tmux), so
  self-trigger isn't available. Tell the user: *"Handoff written — please run `/clear`,
  then `/janitor-arm` to re-arm the heartbeat."* The resume state is recorded, so a
  manual clear + re-arm still auto-resumes.
- `HANDOFF_MISSING` / `HANDOFF_NOT_CONCISE` (stderr) → you skipped step 2 or wrote a
  bloated handoff. `/clear` is unrecoverable — go back and fix the handoff before it runs.

### 5. END YOUR TURN IMMEDIATELY

This is critical, and it is also an INPUT-SAFETY requirement (wikimem
`claude-code-esc-input-semantics`): a slash-command typed into a BUSY pane buffers
and floods later, so `/clear` must land on an IDLE line. The trigger fired a
*detached, soft* keystroke sender (no ESC, no Ctrl+C) — `/clear` runs the moment
this turn ends, so stopping now is what makes it land on an idle prompt. Emit one
short line like *"Handoff written; clearing now, I'll re-arm and auto-resume."* and
stop. Do NOT do more work: the next thing that must run is `/clear`.

## What happens after /clear (the resume, unattended)

1. `/clear` starts a fresh session; `SessionStart` fires (`source: "clear"`), whose
   unconditional re-arm nudge tells the model to arm the cron — but a shell hook cannot
   call CronCreate, so on an unattended machine the **bootstrap keystroke is what drives
   the re-arm turn**, not a human.
2. The bootstrap types `/janitor-arm` (re-arms the destroyed cron) then `/janitor-resume`
   (runs the dispatcher stub → `dispatch.py::_phase_clear_resume` reads
   `resume-after-clear.flag` → emits `[janitor-resume]` + the handoff directive).
3. The directive's FIRST instruction runs `handoff_clear_verify.py --phase after`,
   which reads the `before` snapshot (it survived `/clear`) and emits a PASS/FAIL table
   to `reports/continuity-build/` — proving the cron was destroyed+recreated, the
   context collapsed, and every handoff link resolves.
4. The fresh session reads `.janitor/state/agent-handoff.md` and reconstructs the
   issues/needs by following its wikimem/TRDD links (`memgrep recall`) on demand.

## Scope

ONLY writes the resume state into THIS project's `.janitor/state/` and types `/clear`
+ the re-arm/resume bootstrap into THIS session's own pane (matched by
`$ITERM_SESSION_ID` UUID in iTerm, or `$TMUX_PANE` in tmux — never other panes, so
concurrent Claude instances are untouched). Does NOT change plugin config, does NOT
disarm the heartbeat, does NOT clear other sessions.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/clear_trigger.py` — backing script (persists the
  resume marker, validates the handoff, fires the detached `/clear` + bootstrap;
  `--dry-run` prints the plan and fires nothing).
- `${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff.md` — the link-only handoff this
  skill writes; read FIRST on resume, then follow its links.
- `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-after-clear.flag` — the pre-clear resume
  marker `dispatch.py::_phase_clear_resume` consumes on the re-armed cron's first fire.
- `${CLAUDE_PLUGIN_ROOT}/scripts/handoff_clear_verify.py` — the cross-/clear
  verification harness (`--phase before` snapshots ground truth; `--phase after`
  proves it and writes the PASS/FAIL report). The snapshot lives at
  `${CLAUDE_PROJECT_DIR}/.janitor/state/handoff-clear-verify.json` (survives /clear).
- `/janitor-memory-write` / `/janitor-memory-record-recent` / `/janitor-memory-recall`
  — the harvest surfaces the step-1 precondition uses.
- `/janitor-compact-context` — the `/compact` alternative; prefer it when live scratch
  reasoning isn't durably written down yet.
