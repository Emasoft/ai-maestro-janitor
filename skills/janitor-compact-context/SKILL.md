---
name: janitor-compact-context
description: Jev-compact this session RIGHT NOW — a zero-model-turn clear-and-inject, on demand. Composes a template handoff from on-disk facts, fires /clear plus the bootstrap, and the FRESH session's own SessionStart upgrades it into a richer Jev-compacted context. The manual "do it now" button for the same operation the janitor's automatic levers already run on their own schedule. Use when context is high and the work is durably on disk, or when asked to compact, shrink, or clear. NOT /janitor-handoff-and-clear or /janitor-write-handoff, which are separate, manual-only, model-authored handoff tools this skill never calls.
---

# Janitor compact-context

## Overview

Jev compaction is the janitor's ONLY automatic shrink (TRDD-RAEGS1D5): decide, `/clear`, then
the FRESH session's own SessionStart composes and injects the compacted context out of the old
transcript on disk — no model turn spent authoring anything. `scripts/external_handoff_clear.py`
(TRDD-PXP08ZQC) composes a TEMPLATE handoff from on-disk facts (TRDD `## STATE` blocks, git log,
the findings ledger) at fire time — it does not itself call any summarizer. The FRESH (cleared)
session's own SessionStart hook then runs `scripts/summarize_previous_session.py`, which compacts
the just-cleared transcript through the janitor's own Jev scorer (`jev_compact.py`, card 3) and
upgrades the template into a richer, Jev-compacted context, all within the same short hold
window. **Nothing here costs this session a turn of authoring** — the compaction happens outside
the window it is meant to shrink.

It then reuses `clear_trigger`'s already-ratified verified injection chain to type `/clear` and
bootstrap the fresh session (`/janitor-arm`, `/janitor-resume`).

This skill is the manual trigger for the exact same chain the janitor's automatic levers already
fire on their own schedule (the Stop-boundary size trigger in `on-stop-token-meter.py`, the
heartbeat's long-idle nudge in `dispatch._phase_idle_clear_nudge`, and the stale-cache SessionStart
resume lane) — invoking it by hand just does it NOW instead of waiting for one of those to decide
it is time.

## Not a handoff tool

`/janitor-handoff-and-clear` and `/janitor-write-handoff` are SEPARATE, MANUAL-ONLY tools: the
model itself authors a rich, semantic handoff before clearing. This skill never calls either —
Jev compaction's fact record + Jev-scored transcript items are assembled entirely from disk, with
zero model tokens spent composing them. Reach for a handoff skill directly, by name, when you
want the model to author one; this skill will not do that for you.

## When to use

- Context is high and the session's live state is already durable (TRDDs, wikimem, git,
  `.janitor/state/`).
- You are about to start a long phase and want to enter it lean.
- The user asks to compact, shrink, or clear this session.

## Instructions

1. **Fire it.** `--project-root` is required — the script cannot infer it, because a process
   that is not the session cannot see the session's environment:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/external_handoff_clear.py" \
     --project-root "${CLAUDE_PROJECT_DIR:-$(pwd)}" --force
   ```

   **`--force` is NOT a master override.** It relaxes exactly two TRIGGER terms — `idle …`
   and `no-headroom` (`external_handoff_clear.py:240`) — and its own help says *"every
   safety veto still holds."* A veto is a refusal to clear something that would be harmed
   by clearing, and forcing harder cannot and must not get past one. Add `--dry-run` to
   inspect the composed handoff without clearing anything.

   **`why=active-waiting` is the veto you will hit most, and it is CORRECT.** It means a
   resume or a BACKGROUND AGENT is in flight (`external_clear.py:983`). Clearing then would
   strand work that is running right now. The response is to WAIT for the agents to finish
   and re-run — never to look for a stronger flag. Measured 2026-08-14: a `--force --dry-run`
   on a session with live workers returned `VERDICT HOLD trigger=- why=active-waiting`,
   which is the design working, not a bug.

   Use `--on-resume` instead of `--force` for a just-loaded session: a fresh session can
   never satisfy the long-idle term, so the default gate would always refuse it.

2. **Branch on the FIRST WORD of stdout** — the script's contract is a machine-readable
   leading token:

   | token | meaning | what to do |
   |---|---|---|
   | `CLEAR_CHAIN_SPAWNED` | the chain is queued at this pane | **END YOUR TURN IMMEDIATELY** — see step 3 |
   | `VERDICT HOLD … why=active-waiting` | a resume or background agent is IN FLIGHT | **wait for them, then re-run.** Do not force — this veto is protecting running work |
   | `VERDICT HOLD … why=idle …` / `no-headroom` | a TRIGGER term, not a veto | `--force` legitimately overrides these two |
   | `VERDICT HOLD …` (any other reason) | a safety veto | report the reason; do NOT try to force past it |
   | `DRY_RUN …` | dry run; the handoff follows on stdout | show the handoff, change nothing |
   | `NO_RECORDED_PANE` | no pane breadcrumb, so it cannot bootstrap after `/clear` | do NOT clear — say the session would not come back, and stop |
   | `HANDOFF_NOT_CONCISE <reasons>` | the composed handoff is too fat to be a handoff | report the reasons; the fix is capturing state into TRDDs/wikimem, not forcing the clear |
   | `DISABLED …` | opt-in env flag unset | relay the env var the message names; do not set it yourself |
   | `NO_JANITOR_STATE <dir>` | no janitor state dir for this project | report it; the project is not armed |

3. **On `CLEAR_CHAIN_SPAWNED`, end the turn immediately.** A detached sender types `/clear`
   into this pane shortly after. Emit one short line ("Jev compaction fired — clearing and
   bootstrapping.") and call no further tools. Anything you do after this point is work the
   `/clear` is about to discard.

## Output

One short line, then the turn ends. Side effects: writes the composed handoff + resume
directive into `$CLAUDE_PROJECT_DIR/.janitor/state/`, and spawns the detached `/clear` +
bootstrap chain at this session's own pane.

## Done when

- [ ] `CLEAR_CHAIN_SPAWNED` → one line, turn ended. STOP.
- [ ] Any other token → surfaced to the user with its meaning; nothing cleared.

## Error handling

- The script never blocks; the keystrokes fire detached.
- Not in an automatable terminal (iTerm/tmux) → it reports it; ask the user to `/clear`
  manually. The handoff is still on disk, so the resume still works.
- The Jev scorer unavailable/declining → NOT an error. The on-disk template is what ships at
  fire time regardless; the fresh session's SessionStart summarizer only UPGRADES it, and its
  own fallback is that same template (unchanged if the upgrade never lands). Never treat a
  scorer outage as a reason to skip the shrink.

## Scope

ONLY this session's own pane (matched by the breadcrumb the session recorded at start —
never another pane, so concurrent Claude instances are untouched). Does not change plugin
config, does not disarm the heartbeat, does not compact other sessions.

## Resources

- `scripts/external_handoff_clear.py` — the entry point (flags: `--project-root`,
  `--dry-run`, `--force`, `--on-resume`). It composes the fire-time TEMPLATE only; the
  Jev-compacted upgrade happens later, at the fresh session's own SessionStart
  (`scripts/summarize_previous_session.py` + `scripts/lib/jev_compaction_lane.py`), not here.
- `scripts/lib/external_clear.py` — the PURE decision half (`should_clear_externally`).
- `/janitor-handoff-and-clear` — a SEPARATE, manual-only, in-session sibling (model-authored
  handoff, never called automatically). Reach for it by name when you want the model to write
  the handoff itself.
- `/janitor-write-handoff` — a SEPARATE, manual-only tool that authors a rich handoff without
  clearing. Also never called by this skill or by any automatic lever.
