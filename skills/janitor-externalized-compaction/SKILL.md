---
name: janitor-externalized-compaction
description: Shrink this session by running the EXTERNAL (zero-model-turn) handoff-and-clear — a template handoff composed from on-disk facts, optionally upgraded by the llm-externalizer CLI, then /clear plus the verified bootstrap chain. The skill surface over scripts/external_handoff_clear.py. Cheaper and more detailed than /janitor-handoff-and-clear because the handoff is COMPOSED OUTSIDE the model (no tokens spent authoring it) and the summary comes from llm-ext rather than from this session's own window. Use when context is high and the work is durably on disk, or when asked to compact, shrink, or externally clear.
---

# Janitor externalized compaction

## Overview

The three legs of a shrink are DECIDE, COMPOSE, TYPE. `/janitor-handoff-and-clear` spends
model tokens on COMPOSE — this skill does not. `scripts/external_handoff_clear.py`
(TRDD-PXP08ZQC) composes the handoff from on-disk facts (TRDD `## STATE` blocks, git log,
the findings ledger) and, when the `llm-ext` CLI is available, upgrades the prose through
it. **Neither path costs this session a turn of authoring**, which is the whole point: the
summary is produced outside the window it is meant to shrink.

It then reuses `clear_trigger`'s already-ratified verified injection chain to type `/clear`
and bootstrap the fresh session.

## When to use

- Context is high and the session's live state is already durable (TRDDs, wikimem, git,
  `.janitor/state/`).
- You are about to start a long phase and want to enter it lean.
- The user asks to compact, shrink, or externally clear.

Prefer this over `/janitor-compact-context` (which fires `/compact`, keeps a lossy
auto-summary and costs the model a full re-read) and over `/janitor-handoff-and-clear`
(same `/clear`, but the handoff is authored IN-session at model cost). Reach for
`/janitor-compact-context` only when live scratch genuinely cannot be written to disk first.

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
   into this pane shortly after. Emit one short line ("Externalized compaction fired —
   clearing and bootstrapping.") and call no further tools. Anything you do after this point
   is work the `/clear` is about to discard.

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
- `llm-ext` absent → NOT an error. The on-disk template is what ships; the CLI only upgrades
  the prose. Never treat a missing `llm-ext` as a reason to skip the shrink.

## Scope

ONLY this session's own pane (matched by the breadcrumb the session recorded at start —
never another pane, so concurrent Claude instances are untouched). Does not change plugin
config, does not disarm the heartbeat, does not compact other sessions.

## Resources

- `scripts/external_handoff_clear.py` — the entry point (flags: `--project-root`,
  `--dry-run`, `--force`, `--on-resume`). Its module docstring mentions a `--llm-ext`
  flag that argparse does NOT define; the llm-ext upgrade is internal, so do not pass it.
- `scripts/lib/external_clear.py` — the PURE decision half (`should_clear_externally`).
- `/janitor-handoff-and-clear` — the in-session sibling (model-authored handoff).
- `/janitor-compact-context` — the `/compact` path; last resort, see "When to use".
