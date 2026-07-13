---
name: janitor-resume
description: Resume the current Claude Code session NOW after a compaction or rate-limit, without waiting for the next heartbeat cron fire. Runs the janitor dispatcher stub immediately and handles its stdout per the janitor-heartbeat-protocol rule, so a pending [janitor-resume] cue fires in seconds instead of up to 30 min (the SLOW cron floor). Invoked automatically by the PostCompact push (scripts/hooks/post-compact-resume.py), or by typing /janitor-resume to force a resume / fire a heartbeat on demand. Trigger with /janitor-resume, or by asking to resume now.
---

# Janitor resume

## Overview

After a context compaction (or a rate-limit clear) the REPL returns to **idle**. The
only thing that wakes an idle session is the janitor heartbeat cron fire — and on an
idle session that cron has demoted to the SLOW floor `*/30`, so the first wake can be
**up to 30 minutes** away. `scripts/hooks/post-compact-resume.py` records *what* to
resume (`resume-after-compact.flag`), but the *wake* waited for that slow cron. This
skill is the push: it runs the dispatcher stub **now**, which re-enters the existing
`dispatch.py::_phase_compact_resume` — the flag consumer — so the `[janitor-resume]`
cue fires in seconds.

It adds **no resume logic of its own**: running the stub runs the exact same code the
cron fire would have run (the resume phases, the pending-background-agent listing, the
marker-mimicry sanitization). It just runs it sooner.

## When to use

- The **PostCompact push** injected `/janitor-resume` into this pane (the common,
  automatic case — an unattended session that just compacted).
- You type `/janitor-resume` to force a resume immediately, or to fire a heartbeat on
  demand (with no pending resume flag it degrades to a normal heartbeat — harmless).

## Instructions

1. **Run the dispatcher stub** and handle its stdout per the janitor-heartbeat-protocol
   rule (in `~/.claude/rules/`), exactly as a `[janitor-heartbeat]` cron fire would:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py" 2>&1
   ```

2. **Act on the stub's output per the heartbeat protocol.** The relevant case here is a
   bare `[janitor-resume]` line followed by a directive line — resume the pending task
   named by the directive (read its STATE block / the `precompact-handoff.md` first, as
   the directive says). If the stub prints nothing, there was nothing pending: reply
   with the empty string (the zero-output contract) and stop. Surface any other marker
   lines verbatim and act on them per the protocol.

If the janitor-heartbeat-protocol rule is not loaded, still run the stub and act on a
line that is exactly `[janitor-resume]` (resume the pending task; the next lines carry
the directive); warn that the rule is missing.

## Output

Whatever the resume cue directs (typically: continue the pending TRDD / re-ground from
the handoff), or nothing when the stub was quiet. This skill starts a fresh working
turn; it writes no files of its own (the stub consumes and clears the resume flag).

## Scope

ONLY runs the dispatcher stub for THIS session and acts on its markers. Does NOT change
any plugin config, does NOT disarm the heartbeat, does NOT touch other sessions. The
backing injector that TYPES `/janitor-resume` into the pane is
`${CLAUDE_PLUGIN_ROOT}/scripts/resume_trigger.py` (fired detached by the PostCompact
hook); this skill is what runs once that command lands.

## Resources

- `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` — the auto-rolling stub this skill runs.
- `${CLAUDE_PLUGIN_ROOT}/scripts/resume_trigger.py` — the detached injector the
  PostCompact hook fires to type `/janitor-resume` into this pane.
- `scripts/hooks/post-compact-resume.py` — records the resume directive + fires the push.
- `~/.claude/rules/janitor-heartbeat-protocol.md` — the marker-handling protocol.
