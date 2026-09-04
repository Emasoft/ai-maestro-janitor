---
trdd-id: 74AA4PAL
title: compacted sessions are neither woken nor told a handoff exists — two independent gaps
column: todo
created: 2026-09-04T18:48:19+0200
updated: 2026-09-04T18:48:19+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: user
labels: [continuity, hooks, compaction, handoff, owner-reported]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-2F3I2P18]
---

# Compacted sessions are neither woken nor told a handoff exists

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-04

> **OWNER REPORT (2026-09-04, verbatim intent):** *"all claude code sessions were idle after
> compaction, and I was forced to type the command to resume. and even so they were unaware of
> any handoff."* The owner also recalled asking for the handoff to be fully scripted via
> `llm-ext` from the session JSONL, costing zero tokens, and believed the post-compaction hook
> had been removed.
>
> **THE PREMISE IS WRONG AND THAT MATTERS: NOTHING WAS REMOVED.** `PreCompact` and
> `PostCompact` are wired in `hooks/hooks.json:231-252`, in the repo **and** in the installed
> 3.4.14 cache; `pre-compact-handoff.py`, `post-compact-resume.py` and `resume_trigger.py` all
> exist, and **both hooks demonstrably fire** — `pre-compact-handoff.log` records a handoff
> written on every compaction (22,702 bytes at 13:20 today), `post-compact-resume.log` records
> the resume flag written every time. The zero-token composition the owner asked for is also
> built (`agent-handoff-compose.log`; this session's SessionStart said *"auto-composed with no
> model turn"*; card TRDD-PXP08ZQC, `testing`).
>
> **⇒ THE FAILURE IS IN DELIVERY, AND IT IS TWO SEPARATE BUGS. Fixing one leaves the other.**

### GAP 1 — the wake: the push is suppressed on most auto-compactions

`post-compact-resume.py::_maybe_push_resume` skips the `/janitor-resume` push whenever
`_user_recently_active` is true (`:300-371`): a keystroke within `_PUSH_GRACE_DEFAULT_S = 20`s
(`:258`) **or** a genuine prompt within `_PUSH_PROMPT_WINDOW_DEFAULT_S = 300`s (`:270`).

**MEASURED 2026-09-04** by joining `post-compact-resume.log` to the nearest preceding
`pre-compact-handoff.log` entry in the same session (113 compactions, 8 sessions):

| compaction trigger | push SUPPRESSED | push fired | suppression rate |
|---|---|---|---|
| **auto** | **45** | 23 | **66%** |
| manual | 18 | 29 | 38% |

The gate's own justification is *"an attended user is left alone (**the cron still resumes
them**)"*. **That fallback is unsound**, and both halves were measured today:

- an idle session's heartbeat demotes to the `*/30` **slow floor** — up to 30 min to the next
  wake; and
- the cron can be **absent entirely** — this session ran **2h53m with no cron at all**
  (`CronList` → "No scheduled jobs"), because an arm was reported without being performed.

### GAP 2 — the knowledge: the compact path NEVER injects the handoff

`on-session-start.py:304` defines `_inject_post_clear_handoff`, gated on
`resume-after-clear.flag`. **There is no compact equivalent.** After a compaction the handoff
is written to disk and the agent is left only `resume-after-compact.flag` — it learns a handoff
exists ONLY if a nudge arrives telling it to read the file.

**So the two gaps compound**: suppress the nudge (GAP 1, the majority case on auto-compaction)
and the agent gets neither the wake nor the knowledge. This is exactly the owner's second
sentence — *"even so they were unaware of any handoff"* — and no amount of fixing GAP 1 answers
it, because a woken agent with no handoff still does not know what it was doing.

### What is NOT established

- **That these specific suppressions are the panes the owner saw idle.** The 45 auto-suppressions
  span sessions `d30bf250`, `f30d785b`, `9cce454c`, `ee8f1ca7`, `71542cad`, `fdd47fb6`; nothing
  ties them to the owner's observation. **The dead cron above is a second, sufficient cause of
  the same symptom.** Both are real; which hit which pane is unknown.
- Two claims I published to the owner before measuring, **both wrong**, recorded so they are not
  re-derived: (a) *"the 5-minute window bites hardest on MANUAL compaction"* — inverted, auto is
  suppressed at 66% vs manual's 38%; (b) *"all pre-compact entries say `trigger=manual`"* — that
  was a 10-line tail; the real split is **104 auto / 102 manual**. A raw "63 suppressed" tally is
  also uninformative on its own: a suppression on a genuinely attended pane is the gate working.

## NEXT ACTION — two changes, not one; they fix different halves

1. **Inject the handoff on compaction**, mirroring `_inject_post_clear_handoff` but gated on
   `resume-after-compact.flag`. **Zero tokens** — the file is already composed with no model
   turn — and it makes the agent INFORMED even when no nudge ever fires. This is the only one
   that answers "unaware of any handoff".
2. **Defer the push instead of cancelling it**: when the pane is attended, re-arm ~60 s later
   rather than dropping it. Preserves the "never type under live fingers" floor (the whole
   reason the injector is allowed to exist) while removing "never wakes at all".

**Rejected option, and why:** shrinking `..._PROMPT_WINDOW_S` to ~30 s is a zero-code env fix,
but it weakens the do-not-type-under-live-fingers floor on precisely the manual path where the
user demonstrably just had their hands on the keyboard. Deferral fixes the idleness without
trading that away.

## Acceptance criteria

- [ ] A session that AUTO-compacts has the handoff in its context without any nudge firing.
- [ ] An attended pane still receives no keystroke during the grace window, but does receive
      the push once the pane goes quiet.
- [ ] Both verified from the logs on a real compaction, not only by unit test.
- [ ] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports` and
      `uvx --with pyright pyright` all clean.

## Notes

- `min-approval-requirement: user` because change 2 alters when the janitor TYPES KEYSTROKES
  into a live pane. That is the property the gate exists to protect; loosening it is the owner's
  call, not an agent's.
- Evidence commands are in the STATE block above rather than in a gitignored report, so this
  card survives a `git clean`.
