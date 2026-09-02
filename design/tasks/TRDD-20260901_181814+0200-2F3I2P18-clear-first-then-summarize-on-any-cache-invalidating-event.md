---
trdd-id: 2F3I2P18
title: clear FIRST on any cache-invalidating event, then summarize — the summary source survives the clear
column: testing
created: 2026-09-01T18:18:14+0200
updated: 2026-09-02T05:16:16+0200
implementation-commits: [59e31dcb, 50856019, 3be4a950, 109cc3b9, 4181d6c5, e3299d8d]
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: user
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-1QJIZFFW, TRDD-79LXF6PJ, TRDD-PXP08ZQC, TRDD-XCJFCJUX]
---

# The clear must precede the summary, not follow it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02

### ✅ 2026-09-02 05:15 — the clear-first ORDERING is observed live; the "measured" box still waits for a prefix-invalidation event

> **The first LIVE automated clear on the 3.4.7 lane fired at 04:23:48 on AgentlensPro**
> (trigger `next-fire-misses`; context 418,505 tokens measured from the captured transcript;
> human_idle 1100 s — that trigger needs no idle floor, the next heartbeat would have missed the
> 5-min cache anyway). `external-clear.log`: `fired:` at 04:23:51, then three llm-ext attempts at
> 04:24:02 / 04:24:16 / 04:24:28 — the TRDD-2F3I2P18 clear-first ordering is observed live. The
> session re-armed at 04:24:45 and emitted its post-clear resume cue at 04:25:03 (a new session
> id; heartbeat fires continue). **But every llm-ext attempt failed identically:**
> `Remote api 'openrouter-remote' requires 'api_key' (env var $OPENROUTER_API_KEY is not set)` —
> the launchd daemon carries no such variable (the twin of TRDD-XCJFCJUX, for a credential instead
> of an option), so the chain logged `NO_SUMMARY_POST_CLEAR`, held the session on the 15-minute
> summary hold (dispatch.log 04:29/04:34/04:39) and left the resumed session to ground itself on
> the only handoff there was: the link-only `agent-handoff.md` of 22:59 (the resumed session Read
> it at 04:25:33), written BEFORE the cleared session was born (23:08) — so that session's five
> hours of work (23:08 → 04:19, 418k tokens) are covered by NO handoff; `precompact-handoff.md`
> is older still (18:48) and llm-ext wrote nothing. Filed as **TRDD-QZVAEWQH** (`design/proposals/`, USER ruling — every fix
> places a credential). Also exposed: the daemon fire path takes no `handoff_clear_verify.py
> --phase before` snapshot, so no PASS table can exist for an automated clear — **TRDD-BDZG8Y8A**
> (`todo`).

This fire was a `next-fire-misses` trigger, not a model/effort switch or reload, so the remaining
box (a cache-invalidating event costing no full prefix write) is not closed by it — watch
`external-clear.log` for `prefix invalidated (…)`. The 2026-09-02 paragraph below saying the
drill "cannot happen yet" is SUPERSEDED: XCJFCJUX shipped in 3.4.4 and the lane evaluates live.

Code is shipped and installed (3.4.3; the daemon restaged and respawned 23:43:56). The only
open item is the "measured" box: one automated clear observed under the new clear-first
ordering. It cannot happen yet — the lever is ON in `~/.claude/settings.json` but the
launchd-run daemon has no `CLAUDE_PLUGIN_OPTION_*` in its environment (measured 2026-09-02),
so it evaluates in shadow. Blocked on **TRDD-XCJFCJUX**; the drill is shared with
TRDD-1QJIZFFW (its STATE carries the runnable NEXT ACTION) and TRDD-PXP08ZQC.

## The incident (USER, 2026-09-01)

A week's quota consumed in two days by repeated cache-build writes, then three days unable to
use Claude Code at all. The user's diagnosis: on every cache-invalidating event the session
re-pays a full prefix write, and the janitor's clear arrives too late to prevent it.

## The ordering defect

`external_handoff_clear.py::main` today runs, in this order:

1. gate says clear
2. `_compose` → `run_llm_ext_summary(transcript)` — a subprocess to an external model, **minutes**
   (measured: a 12 MB transcript did not finish inside a 900 s budget)
3. if the summary is empty → decline (`NO_SUMMARY declining to clear`)
4. otherwise write the handoff, then fire `/clear`

Between (1) and (4) the session still holds its full context. Any turn taken in that window pays
the very cache write the clear exists to avoid — and on a busy session that window is where the
money goes. **The clear is gated behind the slowest step in the chain.**

## Why the inversion is SAFE — the fact that unlocks it

`llm-ext` summarizes from the **on-disk transcript**, not from live context:

```
scripts/lib/external_clear.py:528, :959
    [binary, "session-summary", "--stdout", "--transcript", transcript]
```

The transcript is an append-only `.jsonl` under `~/.claude/projects/<slug>/`. **`/clear` does not
touch it.** So clearing first destroys nothing the summary is made from: the material is on disk
before, during, and after.

**This contradicted the standing invariant** at `external_handoff_clear.py` (owner, 2026-08-28):
*"never execute the /clear unless you have already the certainty of having the summarized context
ready to be injected."*

### ✅ USER RULING 2026-09-01 — the invariant is SUPERSEDED, in the owner's own words

> *"the reason i previously said to ensure to having compacted the context via llm-ext before
> clearing, was because i worried that we could loose context informations about the previous
> session. But now i realize that we cannot loose anything, since everything is recorded in the
> jsonl projects transcriptions of claude code. so we just need to clear and wait until the
> llm-ext finish the job … and when it finished we inject that into the context. at that point
> only we can resume all the other tasks. chron, etc."*

The 2026-08-28 invariant was reasoning about a summary composed from LIVE state, where clearing
first genuinely destroyed the source. It does not bind a summary composed from an on-disk
transcript, because that source is not in the context being cleared. **Superseded, not violated.**

The safety it protected is NOT abandoned — it MOVES. The old guard asked "is the summary ready?".
The new one asks **"is the transcript path captured and readable?"**, which is answerable in
milliseconds with no network, and is the real precondition. `min-approval-requirement: user` stays
on this card because the ruling above is what authorizes it.

## The proposed order

1. **Detect** a cache-invalidating event (see the gap below).
2. **Fire `/clear` immediately.** No summary, no network, no model turn. Context drops to base.
3. **Summarize the PREVIOUS transcript** with llm-ext, in the background, from its on-disk path
   captured at step 2.
4. **Inject** the summary when it lands, via the existing resume-directive path.

Cost after step 2 is base-size by construction, so the "pause" the user asks for is not needed for
*cost* — it is needed for *continuity*: between 2 and 4 the session knows nothing. The session must
therefore be held from starting new work until the summary is injected (a resume flag the heartbeat
already knows how to honour), and — critically — the transcript path must be captured BEFORE the
clear, because after it the "newest transcript" is the new, empty one.

## Implementation plan — the exact edits, so this survives a compaction

`scripts/external_handoff_clear.py::main` currently runs compose → read-back → fire (`:398-470`).
The new order, in the SAME process, because the script outlives the `/clear` it fires:

1. **Capture and persist first.** Write `.janitor/state/summary-pending.json` holding the TARGET
   transcript path (`facts["transcript"]`, already resolved at `:236`) and its session key. This
   file is the new precondition — the analogue of the old read-back — and it is what makes the
   clear recoverable: whatever happens next, the source is named on disk.
   **Refuse to fire if the transcript is missing or unreadable.** That check replaces
   "NO_SUMMARY declining to clear" at `:402-406`, and it costs no network.
2. **Fire `/clear` immediately.** No compose, no subprocess, no model turn.
3. **Compose after the clear**, from the path captured in (1) — never from "newest transcript",
   which now resolves to the new empty one. This is the single most likely way to get this
   wrong.
4. **Write the handoff** via `handoff_files.write` (unchanged, `:438`), then **delete
   `summary-pending.json`** — its absence is the release signal.
5. **The hold.** While `summary-pending.json` exists, `dispatch.py` must not emit
   `[janitor-resume]` and must not start chores. It releases when the file is gone.
   **The hold MUST expire** (a TTL in the file) — llm-ext failing must degrade to the mechanical
   `precompact-handoff.md` and release, or one bad network turns an expensive session into a
   permanently stuck one.

The old read-back guard at `:456-470` is retired by this, and its comment must go with it rather
than be left describing a flow that no longer exists.

## USER ANSWERS 2026-09-01 — the two open decisions, settled

**Hold TTL = 15 minutes.** After that the hold releases and the session degrades to the
mechanical `precompact-handoff.md` rather than staying stuck.

**Triggers: model change, EFFORT change, `/reload-plugins`, `/reload-skills`** — all of them, not
just the two originally listed. Effort is the one this card had missed.

**Source: the agentlens CLI directly.** And it does NOT need the forthcoming cache-state verb —
that verb is an upgrade path, not a blocker, because the signal is already there today:

```
$ agentlenspro statusline-history raw
time +0200  session   model   effort  ctx%  ctx     $
18:27:33    08be725e  Opus 5  high    69    686.9k  127.92
```

**`model` and `effort` per turn, per session, newest first.** A change between consecutive rows
for one session IS the cache-invalidating event, with no new API required. Verified by running
it, not from the help text.

Already wired and usable now: `agentlenspro cache-expired` (feeds the existing `cache_expired`
term — note its contract: exit 2 with EMPTY stdout for cannot-answer, never `false`) and
`agentlenspro last-compact`. Follow that same tri-state discipline for the new triggers: an
unreadable signal must leave the other triggers exactly as they were, never synthesize a `False`.

`/reload-plugins` and `/reload-skills` are not in the statusline series; they need their own
signal (the janitor already writes `reload-acked.ts` / `skills-reload-acked.ts` in
`.janitor/state/`, which is the cheapest place to look first).

## The detection gap — the user named events we do not watch

`should_clear_externally` triggers on: measured cache expiry (agentlensPro), predicted
next-fire miss, and long idle. It has **no input for**:

- **model change** — a different model is a different prefix; the next turn pays a full write
- **plugin reload** (`/reload-plugins`) — CLAUDE.md, skills, MCP schemas all re-enter the prefix
- **settings/rules edits** that alter the injected prefix

Each is a moment where the prefix is *already* dead, so a clear is strictly free at that instant
and strictly expensive one turn later. These are the cheapest possible wins and they are currently
invisible to the gate.

## Acceptance

- [x] USER rules on inverting the 2026-08-28 "never clear blind" invariant — RULED 2026-09-01,
      quoted verbatim above: superseded, because the jsonl transcript is not in the cleared context
- [x] the transcript path is captured BEFORE the clear and passed explicitly to llm-ext — never
      re-resolved as "newest" afterwards (`59e31dcb`: `_capture_summary_source` +
      `pending["transcript"]` at the compose site)
- [x] `/clear` on a cache-invalidating event fires with NO network call preceding it (`59e31dcb`:
      the only work between gate and `_fire` is naming the transcript on disk)
- [x] model change, EFFORT change, /reload-plugins and /reload-skills are detected and treated as
      cache-invalidating — model+effort from `agentlenspro statusline-history raw`
      (`109cc3b9`: `prefix_invalidated`), reloads from the janitor's own reload-acked stamps
      (`4181d6c5`: `reload_invalidated`, cursor-consumed, 10-min freshness window)
- [x] the session is held from new work between clear and injection, with a **15-minute TTL**
      (USER, 2026-09-01); on expiry it degrades to `precompact-handoff.md` and releases
      (`50856019`: `summary_hold_active` honoured in `dispatch.py`)
- [ ] measured: a cache-invalidating event costs no full prefix write on the next turn — awaits
      the first LIVE event; watch `external-clear.log` for the `prefix invalidated (…)` lines
- [x] `uv run pytest -q` + ruff + mypy — full suite GREEN 2026-09-01 19:30: 15,939 passed,
      0 failed (the 2 pre-existing failures the 19:00 run surfaced — the `_state` alias hiding
      `branch_protection_lib.py:485` from the git-locks guard, and the gh_issues_monitor
      time-bomb fixture — were fixed in `e3299d8d`)

## Notes and lessons learned

- **UPGRADE PATH (2026-09-01, USER):** the "no new API needed / poll the statusline" premise
  was already stale when written — Claude Code 2.1.251 (installed: 2.1.252) added
  `PreModelSwitch`/`PostModelSwitch` HOOK events, a first-party model-change signal, and gives
  SessionStart resume hooks the session staleness + estimated re-cache cost. TRDD-GK35MOXU
  adopts them; the statusline poll built here becomes the pre-2.1.251 fallback.

- **Do NOT delete the no-summary refusal — MOVE it.** Under the new order there is nothing to
  refuse (the clear already happened); the equivalent safety is that the transcript path is
  captured and the handoff is retried, so a failed summary costs context, never the transcript.
- **Do NOT let the hold become a deadlock.** llm-ext failing must release the session with a
  degraded handoff (the mechanical `precompact-handoff.md` already exists), or a bad network turns
  one expensive session into a stuck one.
- The measurement that motivates all of it: the externalized path costs **0 Claude-side tokens**
  (TRDD-79LXF6PJ box 5) — so every write it prevents is pure saving, and every minute it is
  gated behind is pure loss.
