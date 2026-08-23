---
trdd-id: 5RXBI65T
title: agent-handoff.md has two independent writers and an unconditional overwrite
column: dev
created: 2026-08-22T17:43:05+0200
updated: 2026-08-23T11:08:19+0200
current-owner: janitor-main-session
task-type: bugfix
severity: high
scope: project
approval-tier: 0
release-via: publish
relevant-rules: []
npt: []
eht: []
external-refs: []
implementation-commits: []
---

# `.janitor/state/agent-handoff.md` has TWO writers and no coordination

## ⏵ STATE — READ THIS FIRST ON RESUME

**Design DECIDED, implementation not started — `column: dev` since 2026-08-23.** Filed 2026-08-22
after what was believed to be an incident: a rich handoff this session had just authored, silently
replaced mid-session. The owner ruled on the design 2026-08-23 — **option D**, see
[The design question](#the-design-question--do-not-pick-unilaterally); A/B/C are superseded.

**NEXT ACTION:** decide D's four mechanics (session key derivable by BOTH writers, reader
group-selection, per-file vs per-group concision budget, retention) and implement. An advisor was
consulted 2026-08-23 10:53; **it is NOT a gate** — three prior advisor spawns on this project sit
`stopped: true` in `pending-agents.json` and last night's ran from 22:50 without returning.
Treating a possibly-hung agent as a blocker is how `column: dev` becomes a lie.

**The forensics above are CLOSED — do not reopen them.** F1 is the writer on both days.

**IMPLEMENTED 2026-08-23 — and then largely SUPERSEDED the same day.** Option D shipped in
`0581b940` (per-write filenames via `lib/handoff_files.py`), and every writer is now migrated:

| writer | before | after |
|---|---|---|
| daemon `external_handoff_clear.py:428` | unconditional `atomic_write` on the shared path | **retired entirely** — TRDD-79LXF6PJ; it no longer composes a handoff at all |
| keyless daemon fallback | same bug verbatim on the same path | `UNKEYED` sentinel — still per-write |
| `/janitor-write-handoff` (the skill) | unconditional `Write` on the shared path | keyed name from `handoff_files.py --path`, using `in_session_key()` |

**The system-level claim is finally supportable, and it took three attempts to earn:** no writer
can now clobber another. It was asserted twice before it was true — first while the keyless
daemon branch still wrote the shared path, then while the skill still did. Both times the
narrower claim ("no *daemon* write can clobber another") was the honest one.

**SUPERSEDED BY TRDD-79LXF6PJ:** the owner's directive removed the second writer outright
(option E — *eliminate the writer*), which is strictly stronger than D. D is NOT wasted and must
not be reverted: two sessions of ONE project share a state dir, so the surviving skill-authored
writer would still destroy its own predecessor without it. **Do not close this card as "solved by
D"** — the clobber between the two ORIGINAL writers was solved by deleting one of them.

**✅ CORROBORATED 2026-08-23 10:52 — a live clobber, caught by two DIRECT reads (not mtime).**
The 2026-08-22 incident claim was rightly demoted to uncorroborated (see the superseded reasoning
below); on 2026-08-23 a fresh occurrence supplied the evidence that was missing, without relying
on any of the proxies that made the first attempt wrong:

1. `scripts/hooks/on-session-start.py:291` injects the handoff by **reading**
   `.janitor/state/agent-handoff.md`. This session's SessionStart injection — verbatim in the
   session context — is the **rich model-authored** handoff (`# Agent handoff — 2026-08-23 ~00:0x`,
   the continuity-drill session). Therefore that path held the rich text at `00:35:09`
   (`clear-observed.ts` = 1787438109).
2. `head` of the **same path** at `10:51` returns
   `# Handoff — 2026-08-23T09:16:12+0200 (auto-composed, no model turn — TRDD-PXP08ZQC)`,
   4032 B, and `idle-clear-fired.ts` = 1787469366 (`09:16:06`).

Content that provably existed at that path is provably no longer there. **THE CLOBBER IS
ESTABLISHED — and as of ~11:07 so is the WRITER (F1); the paragraphs below trace how, through
three wrong attributions.** Read 1 is the injected bytes themselves — and the injection
banner in context is byte-identical to the `print()` literal at `on-session-start.py:~301`, which
fingerprints that exact code path, so the bytes provably came from that read of that path.

**⚠ The first version of this block over-reached and is corrected here.** It said *"the only
writer in between is the unconditional `atomic_write` of F1"* and called the file's own header
stamp a direct read. Both were wrong, in the card's own signature way: a **self-declared header
was read as a writer's identity**, which is the same error family as mtime-as-identity, merely
better dressed. What the logs actually say (2026-08-23 ~10:55):

| probe | result |
|---|---|
| project `.janitor/logs/external-clear.log` | no 2026-08-23 entry (mtime Aug 20) — but this is the WRONG log, see next row |
| DATA `global-state/external-clear.log` | fires today at `09:21:12`, `09:22:21`, `09:26:17`, all `[s:cf997868]` |
| `cf997868` — POSITIVE id | `~/.claude/projects/-Users-…-Code-EMASOFT-INTEGRATOR-AGENT/cf997868-f2fe-…`. **It is the session the WATCHER RUNS UNDER — NOT the target.** The target is the `transcript=` field, and on 08-22 `[s:cf997868]` lines name **this project's** `d30bf250-….jsonl`. The daemon is machine-wide: it logs under its own project while acting on another |
| `ls` mtime of `agent-handoff.md` | `09:22` |
| the file's own header stamp | `09:16:12` |
| any `.janitor/logs/` line at 09:16 | none |

**The "~6 minute skew" was NOT an anomaly — it is the summary call, and recording it as a mystery
was itself an error.** Read in source: `external_clear.py:286` captures `now_iso` on entry to
`_compose`; the LLM summarization runs *inside* `_compose` (`:309` log lambda, `:317` degrade
path — that is what emits `summary: ok on attempt 1`); `external_handoff_clear.py:430` writes
`fired:` only after `_compose` returns and `:428` has written the file. So the header stamps
**compose start** and the log line stamps **compose end**, and the interval between them simply
*is* the model call. Header-vs-log disagreement is the design, not a symptom.

**✅ CLOSED — F1 wrote it, and the "impossible ordering" was one more proxy read.** The argument
that nearly stood here was: `idle-clear-fired.ts` = `09:16:06` PRECEDES the header's `09:16:12`,
yet `external_handoff_clear` stamps that file via `_fire()` (`:369`) called at `:429`, i.e. AFTER
the write at `:428` — so it cannot have produced that order, and `dispatch.py:2348` must have.
Which then collided with TRDD-FB84YUGT (no heartbeat fired here between `00:35:42` and
`10:55:32`, and `dispatch.py` runs from a heartbeat).

**Both horns dissolve on one line of source.** `main()` captures `now = int(time.time())` at
**`:390`**, on ENTRY — before `_decide`, before `_compose` — and passes that same integer down to
`_fire(…, now)` → `mark_clear_fired(sd, now=now)`. So `idle-clear-fired.ts` holds the RUN'S ENTRY
TIME even though it is WRITTEN minutes later. The mistake was **reading a stamped value as its
write time** — the identity-by-proxy family again, one level further in.

A single run accounts for every artifact, with nothing left over:

| `:390` | entry, `now` = `09:16:06` → later written verbatim into `idle-clear-fired.ts` |
|---|---|
| `_compose` | stamps `now_iso` = `09:16:12` into the header (~6 s later, after `_decide`) |
| inside `_compose` | the LLM summary — the ~6 minutes |
| `:428` | `atomic_write` of `agent-handoff.md` → mtime `09:22` |
| `:429`→`:369` | writes `09:16:06` (the entry value) |
| `:430` | `fired:` logged at `09:22:21` |

No heartbeat is required, no second writer is required, and FB84YUGT's gap is untouched. **F1 —
`external_handoff_clear.py:428` — is the writer on 2026-08-23, as it is on 2026-08-22.**

**The `cf997868` row was itself repaired once, and the repair is the lesson.** It first read
*"this project's session ids today are `9248f90c`, `fdde8723` — `cf997868` is neither"*, sourced
from `session-start.log` + `heartbeat-fires.log`. That basis is UNSOUND, and the same full read
that confirmed it also destroyed it: `session-start.log` for 2026-08-23 contains **only**
`fdde8723`, yet `9248f90c` fired eight heartbeats that same day. A log that omits a session which
was demonstrably alive cannot be used to prove a third session was not. The conclusion survives
only because a *different*, wider probe supports it — `cf997868` appears in **no** file under
this project's `.janitor/logs/`. Same shape as every other error on this card: **absence from
the files I happened to grep, read as absence from the world.** A zero-hit grep is evidence about
the search term before it is evidence about reality.

That absence argument was then replaced by a **positive identification** —
`cf997868`'s transcript lives under the `EMASOFT-INTEGRATOR-AGENT` slug — and **that was wrong
too, in the same family, for the third time on this row.** Locating the session id told me which
project the *writing process* runs under; I read it as which project the fire *acted on*. For a
**machine-wide daemon those are different things**, and row 62 above has the disproof: the target
is the `transcript=` field, and on 08-22 `[s:cf997868]` lines name this project's
`d30bf250-….jsonl`. So the daemon logs under its own session while acting on another project's
state dir, and F1 is a live candidate again.

Three attempts, three variants of one mistake — **writer identity read as target identity**
(header stamp → writer; wrong log's silence → absence; owning slug → target). Worth stating
plainly because the *third* one arrived while explicitly trying to avoid the first two.

What none of the three could have caught, and which still stands as method: a session that
**started before midnight and was still alive** at 09:21 writes no `2026-08-23` SessionStart line
at all, so no date-filtered grep of `session-start.log` could ever have ruled it out.

### This directly answers mechanic 1 — and it is a trap, not a detail

`state.py:890-905`: `log_line` tags each line `[s:<8-char>]` from **`CLAUDE_CODE_SESSION_ID`**,
the env var of the **writing process**. That is precisely why the daemon's lines carry
`cf997868` while acting on this project — the tag names the writer, never the target.

**So D's session key MUST be the TARGET session's, and the external writer MUST NOT use its own
`CLAUDE_CODE_SESSION_ID` to name the file.** If it did, it would write
`agent-handoff-<watcher>-<ts>.md` into the target's state dir, and the target session — which
looks for its own key — would never find it. The reader would be structurally blind to exactly
the handoff that matters, which is the current bug wearing a new costume: today's failure is a
lost write, that one would be an unreadable write.

The external writer already resolves the target (the `transcript=` field it logs, and
`fleet_restart.recorded_terminal`), so the key is available on both sides — it just is not the
variable the logging convention reaches for by default.

**None of this weakens the card.** The fix does not depend on the writer's name: F1's `:428` is
unconditional on a shared path, read directly in source, and a shared path with two or more
writers is the defect whoever holds the pen.

**The hazard was always sufficient on its own**, and still is: F1 — `atomic_write` at :428 is
unconditional, no read-before-write, no merge, on a path shared with `/janitor-write-handoff` —
is read directly in source and justifies the fix, the acceptance boxes and the priority with or
without an incident. The corroboration raises severity, it does not create the case.

**SUPERSEDED — do NOT carry forward:** the header of this block previously read *"THE INCIDENT IS
UNCORROBORATED"*, and F2 below is still presupposition, not evidence — it is left standing only
as the worked example of the mistake. The 2026-08-22 reasoning that produced it (mtime-as-writer,
"no log surface mentions agent-handoff", "nothing establishes a victim") was **sound for the
evidence available that night** and is retained as method, not as a current verdict.

### F1 — the overwrite is unconditional (certain, read in source)

`scripts/external_handoff_clear.py:428`

```python
state.atomic_write(sd / "agent-handoff.md", text)
```

No guard, no read-before-write, no merge. That path is **also** where the
`/janitor-write-handoff` skill writes the model-authored handoff — the expensive one, authored
deliberately at a delicate juncture to carry exactly the reasoning a mechanical snapshot cannot
produce. The skill's own docs describe the rich handoff and the mechanical
`precompact-handoff.md` as complementary files that "coexist"; nothing anticipated a **third**
writer aimed at the rich one's path.

So the cheap automatic artifact destroys the costly deliberate one, and the loss is silent —
there is no `.prev`, and `.janitor/state/` is gitignored, so nothing recovers it.

### F2 — and the replacement was already stale when written (PRESUPPOSES F1's incident — see the correction above)

| fact | value |
|---|---|
| file mtime | `2026-08-22 17:38:10 +0200` |
| header stamp inside it | `2026-08-22T16:48:21+0200` |
| what it says about TRDD-4GQ94FNJ | `` `dev` `` |
| what that card actually said, since 17:04 | `column: human_review` (`07d3bb2e`) |

Written at 17:38 carrying a card snapshot from 16:48 that had been wrong for 34 minutes. The
clobber traded current information for stale information.

**⚠ RETRACTED 2026-08-22, SAME DAY, BY THE LOG. The section below was headed "MECHANISM PINNED
DOWN — read in source, no instrumentation needed". That heading was wrong twice over: the card
had said "do NOT guess it; instrument it", and I answered it with a better-sourced guess, then
committed it as fact (`2994469a`).**

**The settling evidence: `.janitor/logs/external-clear.log` contains ZERO lines dated
2026-08-22** (file mtime 2026-08-20T08:21). **F2's premise — that the clobbering write came from this script — is UNSUPPORTED. That is the
whole claim; the stronger "it did NOT write" is NOT provable from these logs and is not asserted.**
F1's attribution inherits the same doubt: the unconditional `atomic_write` at :428 is real and
dangerous, but nothing positively places it at 17:38 on 08-22.

**⚠ VOID 2026-08-23 — THE SETTLING EVIDENCE ABOVE WAS A DEAD LOG.** `.janitor/logs/
external-clear.log`'s **last line is dated `2026-08-20T08:21:29`**; the daemon writes to
`~/.claude/plugins/data/…/global-state/external-clear.log` instead. Silence in a log nobody
writes bounds nothing, so the `:428`/`:429`/`:430` reasoning above is void at its premise — not
at its logic. The live log carries **143 entries for 2026-08-22**, ending:

```
[16:58:21] attempt 1 [transient] timed out after 600s | transcript=…/-Users-…-ai-maestro-janitor/d30bf250-….jsonl
[17:08:27] attempt 2 …  [17:18:35] attempt 3 …  [17:28:54] attempt 4 …
[17:38:10] summary: ok on attempt 5
[17:38:10] fired: trigger=next-fire-misses
```

`17:38:10` **is F2's file mtime to the second**, and `transcript=` names THIS project. So F2's
premise is not merely re-supported, it is confirmed — and the 40-minute `16:58`→`17:38` span is
the same compose-latency that produced the ~6-minute gap on 08-23, at ten times the scale.
**F2 and the 08-22 incident are REINSTATED; the "HAZARD-only" framing is retired.**

*What the silence does and does not bound* (corrected — the first version of this paragraph said
silence proves the script "never reached the write", which is off by two statements in the
direction that matters): `fired:` is at **:430**, `atomic_write` at **:428**, `_fire` at **:429**
in between. So silence proves only that no run reached **:430**. A run that wrote at :428 and then
died inside `_fire` — which spawns a chain against a resolved pane, an entirely ordinary place to
raise — produces EXACTLY the observed evidence: a clobbered file, no `fired:` line, untouched log
mtime. That scenario is F1 verbatim, so this evidence cannot exclude it.

*What narrows it further, from the other logged surfaces:*
- `handoff degraded to template` (:317) and the `summary:` progress lines are emitted **inside
  `_compose`, BEFORE the write**. Zero on 08-22 ⇒ no run reached the summary branch that day.
  The residual hole is a run with `use_llm_ext()` false or an empty transcript, which skips that
  branch and logs nothing pre-write.
- The daemon ran task **`cold-cache-clear` 190 times on 08-22** — including 17:34:48→17:34:55 and
  17:39:55→17:40:02, which BRACKET the 17:38:10 mtime without covering it. **190 `starting` lines
  but only ~183 `done in Ns` — 7 starts have NO logged completion**, and an unmatched start is
  exactly the killed-or-detached case, so that hole has candidate instances rather than being
  merely theoretical. Of the runs that DID log completion, all took 3-11 s, against ~15-25 min for
  the one real fire on 08-20.
- **Independent of `_LOG` entirely:** `_fire` (:351) writes its directive as
  "…(link-only handoff, auto-composed…"; the `resume-directive.txt` found on disk read
  "(rich agent handoff)". Different text ⇒ that directive was not written by `_fire`. Limit: a
  crash between :428 and :429 would leave a prior writer's directive intact, so this evidences
  :429, not :428. *(Restored after being wrongly discarded — it had been rejected on the grounds
  that `_fire` sits on "the path shown never to have run", which used the disputed conclusion to
  throw out the one piece of evidence that did not depend on it.)*

**What survives, and is now EMPIRICAL rather than deduced:** the compose-blocks-for-tens-of-
minutes mechanism is real, measured on 08-20, with **both ends logged by the launcher** so no
back-dating inference is needed:

```
cold-cache-clear.log  07:55:48  watcher started (blocking)
external-clear.log    08:05:48  summary: transient — timed out after 600s; retrying in 6s
external-clear.log    08:21:29  summary: ok on attempt 2   →   fired:
cold-cache-clear.log  08:21:29  watcher exited rc=0 — session start released
```

**The compose-blocked figure is 15m41s — the two `summary:` lines.** That is the one with a proof
behind it: those lines come from the `log=` callback passed *into* `summarize_with_retry` from
inside `_compose`, so everything between them is provably on that call stack, with `now_iso` and
the cards already captured. **25m41s is the WATCHER's lifetime**, not `_compose`'s: a "watcher
started (blocking)" / "watcher exited rc=0" pair that a session start waits on is a supervised
child process, and its span CONTAINS `_compose` plus startup, gathers, `_fire` and teardown. The
bigger number was reached for and it lost the tighter proof.

So the staleness hazard below is genuine; only its use to explain the 17:38 observation is
withdrawn.

Two further proxy reads in the retracted reasoning, worth keeping as guardrails: I quoted
`DEFAULT_SUMMARY_DEADLINE_S = 2600` as the effective value when `summary_deadline_s()` prefers
`$CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_SUMMARY_DEADLINE_S`; and I never confirmed the
`if ec.use_llm_ext() and transcript:` branch was taken. The 2 989 s vs 2 600 s shortfall I booked
as "unmeasured residue" also had a better candidate sitting in the same file — the deadline is
checked BETWEEN attempts, so a final attempt starting just under it runs a further
`LLM_EXT_TIMEOUT_S = 600` and overshoots.

**The code shape below is still accurately read; treat it as the hazard's description, not as an
explanation of the 17:38 event.**
`_compose` and `atomic_write` are adjacent in `main()` (compose at :416, write at :428), so the
delay is not between them — it is INSIDE `_compose`, and it is by design:

```
external_handoff_clear._compose
  :278  _gather_cards(root)          ← the card snapshot is taken HERE
  :286  now_iso = time.strftime(…)   ← the header is stamped HERE
  :306  ec.summarize_with_retry(…, deadline = now + ec.summary_deadline_s())
                                      ← BLOCKS up to DEFAULT_SUMMARY_DEADLINE_S = 2600 s (43m20s)
  :318  ec.compose_handoff(…, now_iso=now_iso, tail=ec.recent_messages(transcript))
```

The cards and the stamp are captured BEFORE a retry loop budgeted at four 600 s llm-ext attempts
plus backoff. Observed gap 16:48:21 → 17:38:10 = **2 989 s**; the deadline alone accounts for
2 600 s of it, with the remainder plausibly `recent_messages()` + `compose_handoff()` parsing a
multi-MB transcript (that residue is NOT yet measured — do not assert it as fact).

**The fix is a move, not a redesign:** take `_gather_*` and `now_iso` AFTER the summary returns,
immediately before `compose_handoff`. `summarize_with_retry` consumes only `transcript`, so
nothing else depends on the current ordering. Keep `facts["idle_seconds"]` / `["context_tokens"]`
at DECISION time — those justified the fire and are correctly historical; only the material the
next session reads as current state must be write-time.

**This is independent of the A/B/C question below** — the stale stamp is wrong under every one of
the three options, so it can land first without pre-judging the design decision.

### Why this is the same defect class we have hit twice already

A shared resource with independent writers that cannot see each other — recorded on
TRDD-YWMKNKVT (the USER-scope MOVED notice, 247 redirect lines of churn) and TRDD-KVS6K7P9
finding 3 (the USER memory root). The twist here is that **both writers are the janitor's own**,
in one process tree, so this one is entirely ours to fix.

## The design question — do NOT pick unilaterally

Both files answer the same question ("what does the next turn read first"), so a second path is
not obviously right either.

| option | cost | objection |
|---|---|---|
| **A** — external writes `agent-handoff-auto.md`; readers read both | touches `clear_trigger.py`, `dispatch.py`, `handoff_clear_verify.py`, which all name the filename | two files to keep ordered; a reader that forgets one gets half the story |
| **B** — preserve: rename the existing file to `.prev` before writing | one file, one function | the pointer still says read `agent-handoff.md`, which no longer has the rich content — preserves the bytes, not the usefulness |
| **C** — merge: keep the auto index, append the prior model-authored handoff below it under a marked heading | one file, one function, nothing lost | collides with the concision contract (`HANDOFF_NOT_CONCISE`), which is a **ratified** constraint and must not be quietly widened |

C looks right on the merits — the contract's target is not inlining what a pointer can resolve,
and a handoff the model chose to write is not that. But the contract is ratified, so widening it
is a decision, not an implementation detail. **Consult the advisor and confirm with the USER
before building.**

### ✅ DECIDED 2026-08-23 by the USER — option **D**, none of A/B/C

Asked to pick A/B/C, the owner declined all three and specified a fourth:

> each handoff file should have a datetime stamp in the filename, and if an handoff is for the
> same session it should have the same session hash in the filename. in this way the janitor
> resume handoff will automatically load all handoff of the same session using the hash, and it
> will use the datetime to decide the order of injection/loading of the handoffs.

**D — one file per WRITE, never one shared path.** Filename carries a session key plus a
timestamp; the reader loads every file sharing the key, injecting in timestamp order.

Why it beats the three that were offered: A, B and C all keep a single canonical path and then
negotiate over who gets to own it — so each one is a *policy* preventing a clobber that remains
*structurally possible*. D removes the shared path, so there is no write to lose and no
coordination to get wrong. It also subsumes their benefits: nothing is lost (C), ordering is
explicit rather than implied by two filenames a reader must remember (A), and the pointer keeps
resolving to real content (B).

**Two honest limits on D, so nobody implements it believing more than it delivers:**

- **It does not delete the failure, it MOVES it** — from "a writer clobbers another writer" to
  "the reader selects the wrong group". That is a strictly better failure (it is recoverable —
  the bytes still exist on disk) but it is not *no* failure, and reader-selection is now the
  load-bearing part. This is advisor mechanic 2.
- **"No collision" needs a tiebreak to be true.** Same key + same-second timestamps still
  collide at 1 s granularity, so the filename needs a pid or counter component. A design whose
  whole claim is "no shared path" must not reintroduce one at the second boundary.

**Contract-neutrality is the INTENT, not yet a finding.** D is *intended* to leave
`HANDOFF_NOT_CONCISE` untouched — multiplicity replaces merging, so each file should stay inside
the ratified per-file budget. Whether the budget is per-file or per-group is **advisor mechanic
3, still open**; asserting neutrality before that answer would be pre-answering my own
outstanding question, which is how the A/B/C round went wrong.

**A, B and C are superseded — do not carry them forward as live options.** The table above stays
only to record what was weighed.

## Acceptance

- [ ] a model-authored `agent-handoff.md` survives an external `external_handoff_clear` fire
      (test: write a rich handoff, fire the composer, assert the rich content is still reachable)
- [ ] the auto-composed text's card columns match the cards on disk **at write time** — the F2
      staleness is instrumented and closed, not assumed away
- [ ] whichever option lands, `/clear` recoverability is unchanged (the handoff is the only thing
      that survives a clear, so a regression here is unrecoverable by construction)

## Notes and lessons learned

**Three proxy reads in one session, on ONE question, each one the fix for the last.** Worth the
space because the shape survived every correction and only changed disguise:

1. **A code comment for the code.** F2's original mechanism guess, taken from `dispatch.py`'s
   prose about who consumes what.
2. **An absence of log lines for the absence of an event.** The retraction that replaced (1)
   asserted "the script did not write the file" from silence in `_LOG` — while the log call sits
   at :430 and the write at :428, so the silence could not speak to the write at all. *A
   retraction is not automatically sounder than what it retracts.*
3. **A script name for a task name.** Checking whether the daemon was a second launcher, I ran
   `grep -c "external_handoff_clear\|external-clear" daemon.log` → **0**, and read that as "the
   daemon never launches it". The daemon names the chore **`cold-cache-clear`** — **380 hits**,
   190 invocations on the day in question. Enumerating the distinct `task '<name>'` values found
   in one command what grepping for the name I expected could not.

4. **A file's mtime for a writer's identity** — the one underneath all three, unexamined for four
   commits because each correction argued about *which code* wrote at 17:38 instead of whether
   17:38 establishes a clobber at all. A correction that stays inside the previous claim's frame
   cannot reach the assumption that built the frame.

**THE RULE — this is the transferable part:** *a zero-hit grep (or an empty log, or an absent
line) is evidence about your search term before it is evidence about the world.* Ask what the
system would have to have written for your search to hit, and confirm it writes that at all —
`.janitor/logs/` turned out to contain no `agent-handoff` mention on ANY date, so searching it for
one proved nothing until that was known.

The `grep -o "task '[a-z-]*'" | sort -u` recipe is one illustration of the rule against one log's
format, discovered after the fact — not the rule itself.

The operational lesson, which applies before any code changes: **`.janitor/state/agent-handoff.md`
is not durable storage.** It is gitignored and has an automatic second writer. Anything that must
survive belongs in a TRDD or the wiki. This card exists because a flake roster and a
memorize-nudge ruling were parked there and evaporated within the hour; the gate analysis
survived only because it had also been written into TRDD-4GQ94FNJ's own `## Gate` section.
