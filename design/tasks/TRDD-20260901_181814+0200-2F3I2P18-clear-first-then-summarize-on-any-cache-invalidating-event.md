---
trdd-id: 2F3I2P18
title: clear FIRST on any cache-invalidating event, then summarize — the summary source survives the clear
column: todo
created: 2026-09-01T18:18:14+0200
updated: 2026-09-01T18:29:00+0200
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
external-refs: [TRDD-1QJIZFFW, TRDD-79LXF6PJ, TRDD-PXP08ZQC]
---

# The clear must precede the summary, not follow it

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
- [ ] the transcript path is captured BEFORE the clear and passed explicitly to llm-ext — never
      re-resolved as "newest" afterwards
- [ ] `/clear` on a cache-invalidating event fires with NO network call preceding it
- [ ] model change, EFFORT change, /reload-plugins and /reload-skills are detected and treated as
      cache-invalidating — model+effort from `agentlenspro statusline-history raw`, reloads from
      the janitor's own reload-acked stamps
- [ ] the session is held from new work between clear and injection, with a **15-minute TTL**
      (USER, 2026-09-01); on expiry it degrades to `precompact-handoff.md` and releases
- [ ] measured: a cache-invalidating event costs no full prefix write on the next turn
- [ ] `uv run pytest -q` + ruff + mypy

## Notes and lessons learned

- **Do NOT delete the no-summary refusal — MOVE it.** Under the new order there is nothing to
  refuse (the clear already happened); the equivalent safety is that the transcript path is
  captured and the handoff is retried, so a failed summary costs context, never the transcript.
- **Do NOT let the hold become a deadlock.** llm-ext failing must release the session with a
  degraded handoff (the mechanical `precompact-handoff.md` already exists), or a bad network turns
  one expensive session into a stuck one.
- The measurement that motivates all of it: the externalized path costs **0 Claude-side tokens**
  (TRDD-79LXF6PJ box 5) — so every write it prevents is pure saving, and every minute it is
  gated behind is pure loss.
