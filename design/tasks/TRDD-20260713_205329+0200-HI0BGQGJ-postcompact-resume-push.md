---
trdd-id: HI0BGQGJ
title: Push the post-compact resume so an idle session wakes in seconds not up to 30 min
column: ai_review
created: 2026-07-13T20:53:29+0200
updated: 2026-08-02T06:33:00+0200
current-owner: janitor-session
task-type: bugfix
severity: high
relevant-rules: [3]
implementation-commits: [307427a]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-13

**Problem (user-reported, verified in code):** after a context compaction, nothing was written
for ~30 min. Root cause: post-compaction resume is **pull-only**. `post-compact-resume.py` writes
`resume-after-compact.flag`; the wake is `dispatch.py::_phase_compact_resume`, which runs ONLY on
a heartbeat cron fire. An idle session demotes to the SLOW cadence floor `*/30`
(`heartbeat_cadence.py`), and a compaction returns the REPL to idle — the hook can't re-arm the
cron (only a running turn can). So the first wake is bounded by the already-armed interval → up to
30 min. Violates the "agent never stalls" guarantee (TRDD-324223a6).

**Fix (approach):** add a PUSH. The PostCompact hook, after writing the flag, fires a DETACHED
`resume_trigger.py` that types `/janitor-resume` into this session's own pane (iTerm/tmux via
`terminal_trigger`, SOFT/no-ESC) — the same mechanism `/janitor-compact-context` and
`/janitor-reload-plugins` use. `/janitor-resume` runs the dispatcher stub → the EXISTING
`_phase_compact_resume` fires immediately, consuming the flag and emitting `[janitor-resume]`.
Cron path stays as the durable fallback (headless / non-automatable terminal → NO_ITERM → cron,
no regression).

**Gated to UNATTENDED** (user-presence breadcrumb `last_user_input_epoch` within a grace → skip
the push): keeps parity for attended users (cron still resumes them) and never types into a live
input line. Opt-out `CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ENABLED` (default on); grace
`CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_GRACE_S` (default 180).

**STATUS: IMPLEMENTED + tests green (commit 307427a).** `column: testing`. Remaining before
`complete`: (1) ships on the next `publish.py` release (rides with the other unpushed commits —
do NOT push standalone); (2) one manual end-to-end confirmation in an iTerm/tmux session — trigger
`/compact`, confirm a `[janitor-resume]` turn starts within seconds (not on the `*/30` cron) and
the directive matches the recorded flag. Falsification of the attended gate was verified
(neuter → `test_push_skips_when_attended` fails; reverted).

### 2026-07-29 — e2e run; the shared criterion was stale, the delivery mechanism is proven

This card shared EUWIHP0G's acceptance test ("relaunch a >270k session; `/compact` fires; the
session auto-resumes"). **Its 270k trigger is superseded** — the 2026-07-18 owner directive made
the threshold harness-relative (716_000 here; unreachable-by-design when
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` is unset). Full table and reasoning in EUWIHP0G's STATE block —
not restated here.

**What this card actually needed proving was the PUSH, and it is proven.** The load-bearing gotcha
below — "the hook-spawned child inherits the hook's env, so the detached child finds the right
pane" — was reasoned from `$ITERM_SESSION_ID` being present, never executed. It now has been, in a
real tmux pane: `state.terminal_kind()` resolved to `tmux` from **genuine process ancestry**
(unforced), the detached child **survived its parent's exit**, and the keystrokes landed — counted,
2 fires → 2 landings, dry-run → 0. The SessionStart join then produced **exactly one** landing for
its one fire, with `resume-directive.txt` written only on that fire. Presence gate left intact
throughout (it passed on its own; no bypass).

**Still not claimable:** the final hop — cron fire → `[janitor-resume]` → the agent actually
continuing — was not driven end-to-end here. It is covered at its seams by
`test_post_compact_resume_hook.py` (flag write) and `test_dispatch_cold_cache.py` (emission).

### 2026-08-02 — THE FINAL HOP RAN, in this repo's own session. Mechanism proven; the LATENCY claim is not.

Observed live, not constructed. Timeline from the logs and the filesystem, all
`s:e804d2c9`:

| when | what | evidence |
|---|---|---|
| 05:56:50 | PreCompact captured the ground-truth handoff | `precompact-handoff.md` "Captured (local)" |
| 05:58:45 | PostCompact wrote the flag **and fired the push** — the attended gate PASSED, it did not skip | `post-compact-resume.log`: `resume flag written…` then `resume push fired (/janitor-resume)` |
| ~06:29 | `/janitor-resume` ran in this pane → dispatcher stub → **`[janitor-resume]` + the directive** | the stub's own stdout this turn |
| ~06:30 | flag consumed; the agent read the handoff, then this STATE block, then continued | `resume-after-compact.flag` is GONE; this entry is the continuation |

So `flag → stub → marker → directive → the agent actually continuing` is now observed, which is
exactly the hop the paragraph above says was covered only at its seams. `307427a` is contained in
the released tag `ai-maestro-janitor--v0.45.0`, so remaining item (1) is satisfied too.

**What this run does NOT prove — and the number will look like a failure if this is not read.**
The push fired at 05:58:45 and the command executed ~31 minutes later, which is no better than the
`*/30` cron this card exists to beat. That is **not** a defect and not a slow push: the session was
never idle. It spent that whole window inside one long board-triage turn, and a SOFT (no-ESC)
injection ENQUEUES — by design, so it can never interrupt a live turn. The latency win is defined
against an **idle** session, so demonstrating it needs a compaction that lands while the REPL is
actually idle. This run demonstrates the MECHANISM, not the SPEED.

**One thing to read correctly:** the directive named `TRDD-HI0BGQGJ` — this card — while the work
actually in flight was the kanban triage. That is the documented design, not a mismatch: the hook's
own docstring says it does "NOT auto-continue the task that was interrupted", and names the newest
in-flight board TRDD as a **zero-discipline fallback**. The acceptance criterion was that the
emitted directive match the recorded flag, and it does. Nobody should read a resume cue as "the
janitor knows what you were doing".

**NEXT ACTION:** none blocking. To reach a terminal column this needs the one thing above:
a compaction while the REPL is genuinely idle, showing the `[janitor-resume]` turn starting in
seconds rather than on the `*/30` cron. Staying in `ai_review` until then — moving it now would
claim a latency benefit that has not been measured.

**Load-bearing facts / gotchas:**
- The hook-spawned `resume_trigger.py` inherits the hook's env; the iTerm/tmux session was
  launched with `$ITERM_SESSION_ID` / `$TMUX_PANE`, which the `claude` process (and its hooks)
  inherit — verified `$ITERM_SESSION_ID` present this session. So the detached child finds the
  right pane. If absent (odd env) → NO_ITERM → cron fallback.
- No double-resume: the pushed stub-run unlinks the flag, so a later cron fire sees no flag.
- SOFT (no ESC) is correct: the compaction already ended the turn; SOFT never interrupts.
- Fail-safe: flag written FIRST; the whole push is wrapped so a fault never breaks compaction.

**SUPERSEDED — do NOT carry forward:** nothing yet (new TRDD).

## Files
- `skills/janitor-resume/SKILL.md` — new (model: `skills/janitor-reload-plugins/SKILL.md`).
- `scripts/resume_trigger.py` — new (mirror `scripts/reload_trigger.py`; types `/janitor-resume`).
- `scripts/hooks/post-compact-resume.py` — edit: `_record_resume_directive` returns whether it
  wrote the flag; new gated, detached, fail-safe push after it.
- `tests/test_resume_trigger.py` — new; `tests/test_post_compact_resume_hook.py` — extend.

## Reused (no change)
- `scripts/lib/terminal_trigger.py::send_self_command`
- `scripts/dispatch.py::_phase_compact_resume` (the resume path `/janitor-resume` re-enters)
- `scripts/lib/state.py` user-presence helpers (`user_presence_path`, `is_truthy_env`)

## Verification
- `uv run pytest tests/test_resume_trigger.py tests/test_post_compact_resume_hook.py -q`
- Falsify each gate (attended / no-flag / disabled → no push; each MUST fail if its gate removed).
- `uv run pytest -q` full green; `uv run ruff check`.
- Manual (iTerm/tmux): `/compact` → `[janitor-resume]` turn starts within seconds, not on `*/30`.
