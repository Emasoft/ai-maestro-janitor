---
trdd-id: 0BVF4K7E
title: handoff-and-clear types blind 2s and 10s after its only presence check, so it can splice and submit a user's draft
column: todo
created: 2026-08-02T15:53:36+0200
updated: 2026-08-02T15:53:36+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
blocked-by: []
relevant-rules: []
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Not started. The defect is VERIFIED by code reading; the FIX is designed but NOT approved.**
The owner must choose between the chained-child design and the documented "leave at rules 1+2"
fallback — the advisor is explicit that a naive middle path is *worse than the status quo*.

**NEXT ACTION:** put the two options below to the owner, then implement the chosen one.

### The defect (verified in `scripts/clear_trigger.py`, 2026-08-02)

`/janitor-handoff-and-clear` checks the pane **once**, at t=0, via
`terminal_trigger.wait_until_pane_free` (owner's rules 1+2: empty field + 8 s of no keystrokes).
It then fires **two independent wall-clock timers**, both of which type **blind**:

| t | phase | types | presence re-checked? |
|---|---|---|---|
| 0 s | gate | — | yes, once |
| 2 s | A (`--delay`) | `/clear` | **no** |
| 10 s | B (`--delay + --clear-settle`) | `/janitor-arm`, `/janitor-resume` | **no** |

`_fire_phase` passes `respect_user_presence=False` **deliberately** — so that a user appearing in
the settle window cannot clear the session and then block the re-arm, stranding it unarmed. That
reasoning is sound and must be preserved by any fix; it is not the bug.

**The bug is that rule 3 (read back, verify, only then Enter) never runs here.** A user who
starts typing at t=1 s has their draft spliced with `/clear` and **submitted** — the exact harm
the owner's three rules exist to prevent. All three commands are slash commands, so a *clean*
mangle would fail harmlessly; a *spliced* one does not — it becomes a full prose model turn
carrying the user's partial text.

Window is small (2 s / 10 s) but the failure is a submitted turn the user did not write, in the
one command whose whole purpose is being triggered by a user at their keyboard.

### Why rule 3 is not wired here (the real constraint)

`inject_until_sent` reads the pane back after typing. `clear_trigger` cannot: it must type into
**the session that is running it**, so it types from a detached, delayed child and there is
nothing left in-process to verify. Only rules 1+2 can run synchronously, and they run at t=0.

### Option 1 — chained detached child (advisor-recommended)

One child, one sequence, one timer:

- new `--__inject` verb beside the existing `--__send` in `terminal_trigger.py`, spawned via
  `sys.executable` + resolved path (spawn-now children read the script at exec, so the ephemeral
  plugin-cache GC is not a hazard for them — only for later-invoked registrations);
- `flock` singleton in `.janitor/state/` so re-invocation cannot stack children → double `/clear`;
- eager imports at child start (the lazy `import user_intent` inside the typing probe defers its
  first disk read past the delay, into the cache-GC window);
- verified `/clear` submit → poll a **fresh-session gate** → verified `/janitor-arm` → `/janitor-resume`;
- short give-up (~10–15 min, **not** the 3600 s default), and on give-up **delete the flags** and
  `state.log_line` the outcome.

**The killer constraint, and why a per-phase retrofit is worse than doing nothing:** once phase A
can *defer* (rule 2, up to `_inject_giveup_s()`), phase B's wall-clock timer **decouples**. B's
`/janitor-resume` then lands in the **un-cleared** session, the dispatcher consumes
`resume-after-clear.flag`, and the eventually-landing `/clear` yields a stranded, unarmed,
**unresumable** session. B must chain on A's *verified submit*, never on a clock.

Use a SessionStart-hook artifact mtime as the fresh-session gate, not pane parsing — `/clear`
fires SessionStart, so the artifact is a positive signal; a parsed pane is a guess.

### Option 2 — leave at rules 1+2, and say so

Shrink `--clear-settle`'s blind window and document the residual splice risk in the skill. Honest,
cheap, and does **not** close the phase-B splice. Choose this only if Option 1's complexity is
judged not worth a 2 s/10 s window.

### ⚠ SUPERSEDED — do NOT carry forward

- *"`main()` writes the resume flags before firing, so a give-up recreates the issue-#105
  orphaned-flag regression."* **False for the code as it stands** — the writes happen at step 3,
  strictly AFTER `wait_until_pane_free` returns free, and the file documents this invariant. The
  hazard is REAL but only *under Option 1*: a child that gives up after `main()` has written the
  flags would recreate #105. So Option 1 MUST move the flag writes into the child, immediately
  before the verified phase-A submit. Recorded because the advisor stated it as a present-tense
  fact and it is not one.

### Other detached-only failure modes to fix under Option 1

- **Silent give-up.** `_fire` sets `stdin/stdout/stderr=DEVNULL`, so `inject_until_sent`'s
  `(sent, why)` reaches nobody. Must `state.log_line`.
- **One transient read kills it.** `inject_until_sent` aborts the whole procedure when `reader`
  returns `None` once (a single iTerm osascript timeout). Bound-retry instead of aborting.
- **Self-deferral.** The child's own phase-A submit may bump the presence breadcrumb via
  `on-prompt-submit`, so rule 2 defers on *our own* keystrokes. Bounded (~8 s/phase) — verify
  empirically rather than assuming.
- **Autocomplete overlay.** Verify `prompt_field_shows_only("/clear")` against a live pane with
  the slash-command autocomplete menu open, before trusting the verify loop. Cheapest early
  falsification of the whole design.

## Provenance

Found while wiring the owner's three injector rules (`a335622`). Advisor (Fable 5) consulted on
the design; its verdict is incorporated above, including the one claim of its that I verified and
rejected. The defect itself is confirmed by reading `clear_trigger.py::main` (steps 2–5),
`_fire_phase`, and the `--delay` / `--clear-settle` defaults (2.0 / 8.0).
