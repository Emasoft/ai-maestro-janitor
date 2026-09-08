---
trdd-id: 74AA4PAL
title: compacted sessions are neither woken nor told a handoff exists — two independent gaps
column: testing
created: 2026-09-04T18:48:19+0200
updated: 2026-09-05T13:19:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: user
labels: [continuity, hooks, compaction, handoff, owner-reported]
relevant-rules: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-2F3I2P18]
---

# Compacted sessions are neither woken nor told a handoff exists

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-04

> **2026-09-05 13:28 — correction to ff6a7810's message, after reading `resume_trigger.py`
> myself:** its only pre-fire check is flag presence (`:81`, `any(Path(p).is_file() …)`) plus
> the pane `send_self_command` resolves; there is no session-identity check on EITHER path —
> confirmed, not inherited from the worker. The residual "orphaned pusher" risk (a pane whose
> session changed while its `resume-after-compact.flag` survives) is bounded by the NEXT
> HEARTBEAT that consumes the flag (`dispatch.py:1198`) or reports it orphaned — NOT "by the
> flag's lifetime" as the commit says: on an unarmed session no heartbeat fires and the flag
> survives indefinitely, which is exactly the case GAP 1 above documents. Same risk on both
> paths; unchanged by the deferred push.
>
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

`post-compact-resume.py::_maybe_push_resume` (`:374`) skips the `/janitor-resume` push whenever
`_user_recently_active` (`:302`) is true: a keystroke within `_PUSH_GRACE_DEFAULT_S = 20`s
(`:258`) **or** a genuine prompt within `_PUSH_PROMPT_WINDOW_DEFAULT_S = 300`s (`:270`).

**MEASURED DIRECTLY — two greps, no join, no attribution: 63 of 115 push decisions were
SUPPRESSIONS** (52 fired + 63 suppressed, across 19 distinct sessions in
`post-compact-resume.log`). **That number alone motivates both cards** and depends on nothing
below.

**INDICATIVE ONLY — a trigger-attributed join** (each push line matched to the nearest
preceding `pre-compact-handoff.log` entry in the same session, ≤600 s):

| compaction trigger | push SUPPRESSED | push fired | suppression rate |
|---|---|---|---|
| **auto** | **45** | 23 | **66%** |
| manual | 18 | 29 | 38% |

**Why "indicative" and not "measured": the join's error may CORRELATE with the very variable it
attributes.** The two logs do not pair 1:1 — a PreCompact hook timeout, or a compaction whose
push line never landed, breaks the pairing and the join has no 1:1 check — and an
auto-compaction firing mid-turn under load is precisely when a hook is most likely to time out.
So both numerator and denominator can move, and not proportionally. An earlier version of this
card called the ratio "the finding" while disowning the counts it is computed from; that was
keeping a conclusion after discarding its inputs. **Neither fix depends on which trigger
dominates**, so nothing is lost by labelling it honestly.

**⚠ Numbers to trust, because the first committed version of this card got them wrong.**
115 is *push decisions*, not compactions — `pre-compact-handoff.log` records **207** actual
compactions (104 auto / 102 manual / 1 unknown), and the two logs do not pair 1:1: a PreCompact
timeout, or a compaction whose push line never landed, breaks the pairing, and the join has no
1:1 check. The first version said "113 compactions, 8 sessions" — both wrong (the tally sums to
115, and the log holds 19 distinct sessions). **The 66%-vs-38% ratio is the finding; the
absolute counts are a join over two logs that were never designed to be joined.**

The gate's own justification is *"an attended user is left alone (**the cron still resumes
them**)"*. **That fallback is unsound**, on one measured and one inherited ground:

- the cron can be **absent entirely** — **MEASURED**: this session ran **2h53m with no cron at
  all** (`CronList` → "No scheduled jobs"), because an arm was reported without being performed;
- an idle session's heartbeat demotes to the `*/30` **slow floor** — up to 30 min to the next
  wake. **INHERITED from the janitor-arm skill's prose, NOT measured this session.** Verify
  before relying on it.

### GAP 2 — the knowledge: the compact path NEVER injects the handoff

`on-session-start.py:304` defines `_inject_post_clear_handoff` (called at `:529`), gated on
`resume-after-clear.flag`. **There is no compact equivalent.** After a compaction the handoff
is written to disk and the agent is left only `resume-after-compact.flag` — it learns a handoff
exists ONLY if a nudge arrives telling it to read the file.

**How this was established — and it took THREE attempts, the first two of which tested the
wrong thing.**
- *Attempt 1 (unearned):* one `grep … | head -25` of a single file. An unbounded negative from a
  truncated search — `on-session-start.py` is **1035 lines**, so the truncation hid 97% of it.
- *Attempt 2 (still unearned):* `grep -rnE "def _?inject|_inject_post" scripts/`. **This tests a
  NAMING CONVENTION, not the mechanism.** A SessionStart hook injects context by writing to
  **stdout** (or `hookSpecificOutput.additionalContext`) — no function named `inject*` is
  required. Proof in this session: `on-session-start-trdd-state.py` injected the in-progress-TRDD
  banner with a bare `print(...)` at `:253`, and that file matches the pattern nowhere.
- *Attempt 3 — by mechanism, and this one holds:*
  1. **Flag reachability.** Every `resume-after-compact` reference in `scripts/` lives in
     `dispatch.py`, `resume_trigger.py`, `hooks/pre-tool-token-budget.py`,
     `hooks/post-compact-resume.py`, `hooks/on-session-end.py`, `lib/orphaned_resume.py`,
     `lib/orphaned_memory_maint.py`, `detectors/orphaned-resume-flag.py`. **None of the four
     `on-session-start*.py` files is in that list** — a SessionStart hook cannot gate on a flag
     it never reads.
  2. **Flag-free branch ruled out too** (the file already knows how to find a handoff without a
     flag — `_emit_manual_clear_pointer:258` uses `handoff_files.newest_group`): `grep -n
     "compact" scripts/hooks/on-session-start.py` over all 1035 lines returns **six hits, every
     one a comment** (`:142`, `:463`, `:478`, `:928`, `:998`, `:1005`). No compact branch exists.
  3. **All 12 `print()` sites in the file enumerated**; the only handoff one is the
     `_inject_post_clear_handoff(state)` call at `:529`, inside the clear-flag branch.
  The flag's other references **write** it (`post-compact-resume.py:238-239`), **consume** it
  into a heartbeat cue (`dispatch.py:1198`, surfaced `:3493`), or report it **orphaned**
  (`lib/orphaned_resume.py:129`).
**And the fix is cheap because the hook ALREADY RUNS after a compaction** — `:998-1005` states
it outright: *"`clear` and `compact` re-enter SessionStart inside the SAME process"*, measured
there on 2026-08-11. Nothing needs to be newly wired; a branch needs to be added.
*Precisely, then:* the compact path's ONLY delivery is the heartbeat **cue** — which does carry
a pointer to the handoff file (this session received exactly such a cue at 18:05) — and that cue
is gated behind GAP 1. Injection at SessionStart, which needs no nudge at all, exists only for
`/clear`.

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

## Adversarial review resolution (2026-09-05) — recheck-guard question

**Deviation from the original plan, recorded verbatim:** the re-entry sentence in the
original plan was unsatisfiable; a bounded detached recheck child (60 s cadence, 15 min
cap — `_defer_push`/`_run_deferred_recheck`, `scripts/hooks/post-compact-resume.py:434-503`)
supersedes "no new timer" for this path.

**Review question:** does the recheck re-validate the SESSION (not just the flag and the
pane) — the same identity check `resume_trigger.py` applies on the direct path?

**Finding (verified from source, no gap):** `resume_trigger.py`'s direct (2 s) path carries
**no stronger session-identity check than flag presence** — it does not compare a stored
session id, pid, or transcript path anywhere. Pane targeting is `$TMUX_PANE` /
`$ITERM_SESSION_ID`, env vars set once by the terminal and inherited unchanged down every
child process (`scripts/lib/terminal_trigger.py:1478-1494`) — stable for the *pane*, blind to
which process currently occupies it, on BOTH paths equally. So "mirror the direct path's
session check" has nothing extra to mirror; what the direct path actually relies on is the
flag's existence, re-checked at multiple independent layers:
1. `_run_deferred_recheck` itself re-reads `resume-after-compact.flag` before calling
   `_fire_push` (`post-compact-resume.py:481-484`).
2. `resume_trigger.py:81` re-checks the same flags at its own fire time (called fresh by
   `_fire_push`, not cached from the deferred child).
3. `send_self_command`'s `abort_unless_any` is threaded into the DETACHED TYPER CHILD's own
   `--__send` payload (`terminal_trigger.py:1388,1601,1672`) and re-checked again at TYPE
   time, in a process separate from both (1) and (2).

So the deferred path performs a **strict superset** of the direct path's checks (three
re-checks of the same guard vs. the direct path's one), not a weaker one. Conclusion:
**no additional guard needed** — verdict is CONFIRM, not FIX. Gates re-run clean:
pytest 42/42, ruff clean, mypy clean, pyright 0/0. Full command output:
`reports/board-drain/20260905_131900+0200-74AA4PAL-recheck-guard.md`.

## NEXT ACTION — two changes, not one; they fix different halves

**⇒ CHANGE 1 IS NO LONGER THIS CARD'S WORK — it is `TRDD-OES0NN3F`, `column: todo`,
`min-approval-requirement: none`, blocked on nobody.** Bundling an unapproved keystroke-timing
change with an unblocked injection fix made this card's original `column: todo` a claim that
half of it could be picked up and worked, which was false — the same "column that lies" defect
this session flagged on 12 other cards. **THIS card is now the deferred-push change alone**, and
it is `blocked` until the owner decides.

1. ~~Inject the handoff on compaction~~ → **SPLIT OUT as `TRDD-OES0NN3F`.** (Mirror
   `_inject_post_clear_handoff` gated on `resume-after-compact.flag`; zero tokens; makes the
   agent INFORMED even when no nudge ever fires. The only fix that answers "unaware of any
   handoff".)
2. **Defer the push instead of cancelling it**: when the pane is attended, re-arm ~60 s later
   rather than dropping it. Preserves the "never type under live fingers" floor (the whole
   reason the injector is allowed to exist) while removing "never wakes at all".

**Rejected option, and why:** shrinking `..._PROMPT_WINDOW_S` to ~30 s is a zero-code env fix,
but it weakens the do-not-type-under-live-fingers floor on precisely the manual path where the
user demonstrably just had their hands on the keyboard. Deferral fixes the idleness without
trading that away.

## Acceptance criteria

- [ ] A session that AUTO-compacts has the handoff in its context without any nudge firing.
- [x] An attended pane still receives no keystroke during the grace window, but does receive
      the push once the pane goes quiet.
- [ ] Both verified from the logs on a real compaction, not only by unit test.
- [x] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports` and
      `uvx --with pyright pyright` all clean.

## Notes

- `min-approval-requirement: user` because change 2 alters when the janitor TYPES KEYSTROKES
  into a live pane. That is the property the gate exists to protect; loosening it is the owner's
  call, not an agent's.
- Evidence commands are in the STATE block above rather than in a gitignored report, so this
  card survives a `git clean`.

## Approval log

- 2026-09-05T10:38:00+0200 — APPROVED by main-session under the USER's standing autonomous-drain permission (memory ATOM-CCRI-ZRT2, 2026-09-03; re-issued as today's session goal): the deferred-push change (defer ~60 s instead of cancelling when the pane is attended). It preserves the no-typing-under-live-fingers floor that the rejected alternative (shrinking `_PROMPT_WINDOW_S`) would have weakened, and it answers the one hard number on the card — 63 of 115 push decisions SUPPRESSED, measured directly. The trigger-attributed split (auto 66% / manual 38%) stays INDICATIVE, as the card itself labels it, and does not bear on the approval. Column restored to `todo`; this is now startable code work.
