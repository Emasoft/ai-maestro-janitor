---
trdd-id: UQW5IOAE
title: An idle keep-warm session should be forced through handoff-and-clear to shrink its prefix
column: todo
created: 2026-08-02T14:19:42+0200
updated: 2026-08-02T14:32:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
blocked-by: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started. FABLE-ADVISOR VERDICT RECEIVED 2026-08-02 — it RE-SCOPES this card. Read the
verdict section below BEFORE the design notes further down, which were written on a premise that
turned out to be false.**

### ⚠️ THE PREMISE WAS WRONG — diagnose before building

I filed this card assuming the janitor's own heartbeat drove the 92 s keep-warm fires. **It
cannot have.** Verified first-hand: the cadence tiers are FAST `*/5` = **300 s**, MID `*/15` =
900 s, SLOW `*/30` = 1800 s. A 92 s median gap is **faster than the fastest tier**, so something
other than the janitor cron drove those turns.

**STEP 1 IS THEREFORE DIAGNOSIS, NOT IMPLEMENTATION:** read that session's transcript tail and
establish what actually triggered each turn. Building an auto-clear mechanism on the assumption
it was our cron would be a fix aimed at a cause that does not exist — and it would appear to
work, because clearing the context reduces the cost of whatever the real driver is too.

### Verdict: NOT as external injection — a SELF-NUDGE, and probably not yet

- **Do not let the daemon (or any outside actor) type `/clear` into another session.**
  `clear_trigger.py` is built as a SELF-trigger: it resolves the pane from its OWN
  `$ITERM_SESSION_ID`, validates a handoff the MODEL authored that turn, and writes resume state
  synchronously because there is no PostClear hook. An external `/clear` has none of that —
  nobody authored a fresh handoff, and `/clear` with a stale or absent one is unrecoverable loss.
- **The safe owner is the session's OWN dispatch, and the safety then comes free.** A session
  parked on `ExitPlanMode`/`AskUserQuestion` or mid-long-tool cannot end its turn, so its cron
  never fires. A heartbeat-owned nudge therefore *structurally cannot* clear a blocked or busy
  session — the property the acceptance list below was trying to buy with tests.
  Mechanism: dispatch emits a marker → the model writes a FRESH handoff that turn → it invokes
  the existing skill, which runs `clear_trigger` with its own presence gate. **Never a
  `fleet_inject` keystroke path for `/clear`.**
- **`/compact` + the SLOW tier may already capture most of the win.** The idle burn is dominated
  by the ~308 k install floor (measured 343,007 → 308,644), so `/clear` reloads the same base
  prefix and beats `/compact` only by the summary + residue — a modest slice of ~507 k/fire.
  Cutting FIRES (`*/30` = 6× fewer) dwarfs cutting per-fire size.
- **The asymmetry is the whole answer:** being wrong that compact suffices costs measurable
  dollars, checkable in `token-meter.jsonl` after a week. Auto-`/clear` misfiring ONCE on a
  session with real in-flight state is unrecoverable.

**Owner directive reconciliation:** the directive said *force the agent to run
`/janitor-handoff-and-clear`*. The verdict does not refuse it — the agent still runs exactly that
skill. It changes only WHO pulls the trigger: the session's own heartbeat rather than keystrokes
typed in from outside. That preserves the intent and removes the unrecoverable failure mode.

**OWNER DIRECTIVE (2026-08-02, verbatim):** *"when that happens, you should force the agent to
run `/janitor-handoff-and-clear`, so to reduce the context to a minimum."*

**"When that happens" — the MEASURED trigger, not a hypothetical.** `agentlenspro
investigate_burn` on 2026-08-02 named `IDLE_FLEET_KEEPWARM` as a top culprit: ONE background
session (`~/Code/EMASOFT-ASSISTANT-MANAGER`) fired every **~92 s median for 2.9 h** with no user
present, re-reading its full prefix on every fire. Window total that day: **38.1M
input-equivalents, ~$203**, of which cache-READ was 324.3M tokens against only 4.5M cache-write.

## Why this is not the same as the cold-cache compact already shipped

TRDD-EUWIHP0G ships `/compact` on a COLD cache (the ≥1 h gap case) — the cache is already dead,
so the expensive rewrite is unavoidable and compaction makes every LATER resume cheap.

This is the opposite regime: the cache is **WARM and being kept warm**, so each fire is billed at
the cheap 0.1× cache-READ rate — but on a ~510 k prefix, 39 fires/hour, forever. Nothing is
broken, nothing looks wrong, and the session is doing no work. **Compaction may not be enough**:
it shrinks toward a learned floor that is still large. `/clear` reduces the prefix to
approximately nothing, which is the directive's "to a minimum".

That difference is the whole reason this is its own card and not a knob on EUWIHP0G.

## The danger, stated before the design

`/clear` is **irreversible** and the handoff is the ONLY survivor. Clearing a session that was
actually mid-something destroys real work with no undo. So the preconditions matter more than
the mechanism, and at least these must hold — this list is the question put to the advisor, not
a settled answer:

- the user is genuinely absent (`user_intent.user_is_present` / `injection_allowed`);
- the session is NOT blocked on a human (`fleet_scan.awaiting_user_decision` — an unanswered
  `ExitPlanMode`/`AskUserQuestion` looks identical to idle by every other signal; this is the
  exact trap TRDD-8IZ8COQ8 documented, where a guardian typed into an approval dialog);
- the session is NOT mid-long-tool (an unanswered `tool_use` also means a 20-min Bash is still
  running — the `ATOM-8IZ8-BROAD` lesson);
- the prefix is actually large enough for the trade to pay;
- the handoff was WRITTEN and VERIFIED before `/clear` is typed — `clear_trigger.py` already has
  `check_handoff_concise`; a `/clear` that outruns its handoff is pure data loss.

## Reuse, do not reinvent

`scripts/clear_trigger.py` (the two-phase `/clear` + bootstrap plan, and the handoff contract
check), `cold_cache_compact.py` (threshold/cooldown/floor-learning shape), `user_intent`,
`fleet_scan.awaiting_user_decision`, `fleet_recovery.gate` (cooldown + attempt accounting),
`terminal_trigger` (soft-vs-hard injection).

**Open question for the advisor, recorded so it is not lost:** which layer owns the trigger — the
DAEMON's fleet beat (it can see other projects' sessions, which is where the measured culprit
was) or the session's OWN heartbeat (it can see its own context size cheaply, and never types
into a pane it does not own)?

## Acceptance

- [ ] Advisor verdict read and its objections either implemented or explicitly refused in writing.
- [ ] A gate whose neuter is measured: disabling it must let a protected case through in a test.
- [ ] A test proving a session blocked on `ExitPlanMode` is NEVER cleared.
- [ ] A test proving `/clear` is not typed unless a verified handoff exists on disk.
- [ ] Default-OFF until observed working on a real idle session, then flipped deliberately.
