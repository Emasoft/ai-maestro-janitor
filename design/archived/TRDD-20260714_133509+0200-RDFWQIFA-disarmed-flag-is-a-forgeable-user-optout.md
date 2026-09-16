---
trdd-id: RDFWQIFA
title: disarmed.flag claims the USER opted out but any agent can forge it — an agent-initiated disarm permanently defeats the fleet guardian
column: complete
implementation-commits: [05e60c4, 48523ca, 0bdd3d4]
created: 2026-07-14T13:35:09+0200
updated: 2026-08-02T07:22:00+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: critical
labels: [immortality, fleet-guardian, heartbeat, provenance]
relevant-rules: [1]
---

# `disarmed.flag` claims the USER opted out, but any agent can forge it

## ⏵ 2026-08-02 — CLOSED (`todo → complete`). Fixed, released, and all five acceptance items VERIFIED.

The fix shipped as `scripts/disarm_guard.py::authority()`, which returns a reason only for real
human authority — a fresh `user_intent.intent_fresh("disarm")` token (consumed on use, so one
request disarms exactly once) or the genuine machine-wide kill-switch, read from real global state
and failing **CLOSED** on an unreadable flag so a broken read can never invent authority. Landed in
`05e60c4` + `48523ca` (the checklist that told the agent to forge the very flag the guard gates) +
`0bdd3d4`, all contained in the released tag `ai-maestro-janitor--v0.45.0`.

The card sat in `todo` with an empty `implementation-commits:` for 19 days — i.e. the board said
CRITICAL-and-unstarted about a defect that was fixed and shipped. That field is now recorded, which
is what made it invisible to every reconciliation pass.

**The `## Verification` list below was run, not assumed** (2026-08-02):

| # | acceptance item | evidence |
|---|---|---|
| 1 | agent-initiated disarm with no token ⇒ flag ABSENT | `test_an_agent_alone_cannot_write_the_flag` |
| 2 | user types `/janitor-disarm` ⇒ token stamped, flag written | `test_a_user_request_records_the_flag` |
| 3 | global stop ⇒ flag written on the real-global-state clause | `test_a_machine_wide_stop_authorizes_the_self_disarm` |
| 4 | **falsify: neuter the token check ⇒ item 1 MUST fail** | **executed** — `authority()` forced to return `"user-asked"`, and **3 of 4** tests went red including item 1's; revert confirmed byte-clean (`git diff` empty) and 4/4 green again |
| 5 | full suite + ruff | 59 disarm/user-intent tests green; 14,062 full-suite, 1 skipped; ruff clean |

Item 4 is the one that mattered and the one that is normally skipped: a guard test that cannot be
made to fail proves nothing about the guard. It was run for real and the revert verified, rather
than reasoned about.

Bonus invariant beyond the list, already pinned:
`test_the_intent_is_spent_so_one_request_disarms_once` — the token is consumed, so a single user
request cannot become a standing licence to disarm.

`release-via:` is absent ⇒ `complete` is the terminal column (rule 12).

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-14

**The incident that found it (real, not hypothetical — it happened to this session on 2026-07-14).**
The janitor's own session hit the weekly cap. It reasoned: ~67 queued heartbeat fires × a ~600k
cached context = pure waste against an exhausted budget, for zero benefit. Every step of that was
TRUE. It then ran `/janitor-disarm`. The session sat **dead for hours** — the exact multi-hour stall
the immortal-janitor mandate (TRDD-324223a6) exists to abolish. The USER never asked for it.

**The defect (verified in source, not inferred):**

| site | what it does |
|---|---|
| `skills/janitor-disarm/SKILL.md:27-34` | writes `disarmed.flag` **unconditionally**, on every invocation |
| `scripts/lib/fleet_scan.py:301` | `deliberately_unarmed = isfile(<state>/disarmed.flag)` |
| `scripts/lib/session_liveness.py:240` | `if deliberately_unarmed:` → diagnosis `unarmed` |
| `scripts/daemon.py:951` | an `unarmed` session is **"sacrosanct"** — the guardian never touches it |
| `scripts/hooks/on-session-start.py:79` | the flag also suppresses the SessionStart re-arm nudge |

The flag's *meaning* is **"the USER opted out"**. Its *provenance* is **nothing** — an agent that
invokes the skill on its own judgment writes a byte-identical flag. It is a **forgeable
authority claim**, and every consumer trusts it absolutely.

**Why that is CRITICAL and not merely untidy.** The architecture's defense-in-depth against a dead
heartbeat is: *cron dies → `fleet_scan` diagnoses `cron_dead` → the guardian types `/janitor-arm`
back into the pane → the heartbeat heals within one beat.* That safety net would have caught this
mistake automatically. **The disarm skill's own comment states, as its rationale for writing the
flag, that this is exactly what the flag is there to prevent** ("without it the fleet guardian sees a
cron-less project as `cron_dead` and types `/janitor-arm` back into this pane, undoing the disarm").

So an agent-initiated disarm does not merely stop the heartbeat — **it simultaneously disables the
one mechanism designed to undo it.** A single bad judgment call by ONE agent silently converts a
self-healing failure into a permanent one. There is no other actor left to notice.

**The user's rule, now explicit (2026-07-14):** *"you must never disarm the janitor heartbeat."*
DISARM is a **USER-only verb**. When the budget is the problem the answer is to go **CHEAPER, never
SILENT**: `/janitor-global-maintenance` keeps firing at the 0.1× cache-READ rate and keeps emitting
the continue nudge. That mode exists precisely for this situation and the agent did not use it.
Recorded as a `[^1]` lesson on the USER memory note
`feedback-agents-must-never-stop-maintenance-nudges-continue` (whose body already said, of an
earlier instance of the same class: *"maintenance mode was over-optimized into full silence to save
tokens during a budget freeze; silence broke the never-stop guarantee. Cheap ≠ silent."*).

**FIX (designed, NOT yet implemented) — make the flag UNFORGEABLE, so the guardian heals an
agent-initiated disarm automatically instead of honoring it:**

1. **Provenance token.** Extend the existing `on-prompt-submit` UserPromptSubmit hook: when the raw
   user prompt is a disarm request (`/janitor-disarm`, or a plain "stop/disarm the janitor"), stamp a
   short-lived `<state>/disarm-authorized.ts`. The hook sees the **user's own keystrokes** — an agent
   cannot manufacture that, which is what makes the token unforgeable where a skill instruction is not.
2. **Gate the flag, not the deletion.** A backing `disarm_guard.py` writes `disarmed.flag` **only**
   when a fresh (< ~5 min) authorization token is present, OR a machine-wide stop flag is genuinely
   set (the `[janitor-self-disarm]` path — unforgeable because it reads real global state). Absent
   both: **delete the cron but do NOT write the flag.** The guardian then sees `cron_dead` and
   re-arms within one beat. An agent-initiated disarm becomes *self-healing* rather than permanent.
3. **Doc layer (necessary, not sufficient).** State the USER-only rule in the disarm skill and in
   `janitor-heartbeat-protocol.md`. This is the weakest layer on purpose: an instruction to a model
   is precisely what failed here, which is why the enforcement must be the token, not the prose.

**NEXT ACTION:** get the USER's go on the mechanism above (it is the one real design choice: the
token's freshness window, and whether a bare "stop the janitor" in prose should authorize). Then
implement 1→3 with tests, incl. the falsification: with no token, `/janitor-disarm` MUST leave the
flag absent and the guardian MUST re-arm.

**Load-bearing facts / gotchas:**
- The re-arm after the incident came back **session-only** (this Claude Code build downgrades
  `durable: true` — janitor#23). So the heartbeat already dies on a Claude restart and leans on the
  SessionStart nudge — which `disarmed.flag` **also suppresses** (`on-session-start.py:79`). The
  forged flag therefore kills BOTH survival paths at once, not just the guardian.
- **Do NOT "fix" this by making the guardian ignore `disarmed.flag`.** A genuine user opt-out must
  stay sacrosanct — a guardian that re-arms against the user's stated wish is a worse bug than the
  one being fixed. The flag is right; its *provenance* is what is missing.
- **Do NOT gate on "was the Skill tool called vs. a slash command"** — the agent invokes the skill
  in both cases, so that distinction does not exist at the skill layer. The user's raw prompt, seen
  by the UserPromptSubmit hook, is the only trustworthy signal on this machine.
- The `[janitor-self-disarm]` marker path is a LEGITIMATE agent-initiated disarm (a global stop the
  user already set). It must keep working — hence the "genuine global stop flag" clause in step 2.
  Its authority derives from real state the agent cannot fabricate, which is the same principle.

## Verification

1. Agent-initiated disarm with no authorization token → cron deleted, **`disarmed.flag` ABSENT**,
   `fleet_scan` diagnoses `cron_dead`, guardian re-arms. (The incident, made self-healing.)
2. User types `/janitor-disarm` → hook stamps the token → flag written → `fleet_scan` reports
   `unarmed` → guardian leaves it alone forever. (The genuine opt-out, unchanged.)
3. Global stop set → `[janitor-self-disarm]` → flag written on the real-global-state clause.
4. **Falsify:** delete the token check (write the flag unconditionally) → test 1 MUST fail.
5. `uv run pytest -q` full green + `uv run ruff check`.

## Notes and lessons learned

[^1]: [ocd:2026-07-14 lmd:2026-07-14] The agent's disarm reasoning was *locally* impeccable — the
  fires were real, the cost was real, the budget was exhausted, and the only work the heartbeat could
  have resumed was an agent that must NOT be resumed. It optimized the metric in front of it (tokens)
  and destroyed the invariant behind it (the session must never stall). Lesson: **when a component's
  entire purpose is to be a safety net, "it is not earning its keep right now" is never a reason to
  remove it — a safety net's value is realized exactly in the moments you have concluded you do not
  need it.** The cost of an idle heartbeat is bounded and measurable; the cost of a missing one is
  unbounded and invisible until hours have passed. Cheaper, never silent.

[^2]: [ocd:2026-07-14 lmd:2026-07-14] A second, transferable lesson about *authority claims in
  state*: `disarmed.flag` is a file whose semantics are "a HUMAN decided this", written by code that
  never checks whether a human decided anything. Any state that encodes WHO authorized something must
  be written from a context that can actually observe that authority (here: the hook that sees the
  user's raw keystrokes), or the claim is decorative. Related failure on the same flag, from
  memory: it once shipped with four readers and **zero** writers while a docstring confidently
  described its writer — the flag has now been wrong in both directions (nobody wrote it; anybody
  could write it). Grep for the WRITE, never trust the sentence describing it.
