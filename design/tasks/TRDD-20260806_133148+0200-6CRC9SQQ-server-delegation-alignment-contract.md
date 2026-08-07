---
trdd-id: 6CRC9SQQ
title: Janitor-server delegation has no alignment contract — a server-claimed chore can wedge for days and neither side notices
column: human_review
created: 2026-08-06T13:31:48+0200
updated: 2026-08-07T12:45:00+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# Janitor-server chore-delegation alignment contract (owner failure report 2026-08-06, item 7)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Log provenance RESOLVED — and the "contradiction" I recorded here is DISPROVED. There is no
contradiction: the daemon yields exactly as `claimed_chores()` says.** The whole thing was one
mistake — I grepped the wrong file. Item 1 is UNBLOCKED and its premise holds.

### ✔ WHICH LOG THE GLOBAL DAEMON WRITES (verified from the resolver, then from the file)

The global daemon does **not** log into any project's `.janitor/logs/`. `daemon.py:2169` runs
`os.environ.setdefault("JANITOR_LOG_DIR", str(gs.global_state_dir()))`, and `state.log_dir()`
(`state.py:166`) returns that override when present. So the daemon's log is:

```
~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log
```

Live, 9 979 lines, last written 22:51 today. It carries **9 `chore-coordination` lines**:

```
2026-08-05T20:43:07 [s:c9ae7481] yielding to active ai-maestro server: [all five]
2026-08-06T06:23:39 [s:c9ae7481] server no longer confirmed active — resuming singleton chores
2026-08-06T06:25:57 [s:c9ae7481] yielding to active ai-maestro server: [all five]
```

And since that 20:43 yield: **zero** `task '<any of the five>' starting` lines, while the chores
the daemon still owns (`fleet-stop`, `memory-guard`, `session-liveness`) run every minute. The
yield is real and it is honoured.

### ✔ `[s:...]` DOES NOT DISTINGUISH DAEMON FROM SHIM (the other wrong idea, retired)

`log_line` emits `[s:<id>]` whenever `CLAUDE_CODE_SESSION_ID` is set — and the detached daemon
INHERITS it from whichever session spawned it. `ps eww -p 30605` shows
`CLAUDE_CODE_SESSION_ID=c9ae7481…`, which is exactly the tag on its own lines. The tag means
"who spawned me", not "I am a session shim".

The 16:35:59 `version-update` line was therefore **not** the daemon: it lives in the *project*
log, tagged `[s:643908a6]` — a session id that appears **zero** times in the real daemon log. It
is the per-session shim `detectors/version-update.py`. Consistent with the daemon yielding.

### What this costs and what it buys

Everything under "the contradiction" was an artifact of one wrong path. `claimed_chores()` and
the daemon AGREE; the daemon never ran a yielded chore; no premise of this card is invalidated.

**Item 1 is UNBLOCKED and now well-motivated**: five chores are handed to the server *right now*
and nothing on our side verifies the server runs them — a watchdog would watch a NON-empty set,
which was the exact thing in doubt.

### Hypotheses eliminated (kept — all still true, none of them was the answer)

| hypothesis | result |
|---|---|
| version skew — daemon runs older code | **No.** Daemon runs `2.4.1/scripts/daemon.py` (pid 30605, up since Aug 5 20:43) |
| my probe measured different code than the daemon | **No.** `diff` of cache vs repo `harness_backend.py` → IDENTICAL, same five chores |
| stale in-memory module (imported before an update) | **No.** `harness_backend.py` mtime 19:06 predates the daemon's 20:43 start |
| memoized claim/liveness result | **No.** `server_runs_chores()` documents "No memo"; `server_capabilities()` re-reads per call |
| env override in the daemon's environment | **No.** `ps eww -p 30605` shows no `JANITOR_AIMAESTRO_*` override |
| daemon HOME / `_liveness_path()` divergence | **No.** `HOME=/Users/emanuelesabetta`, identical to the shell's |
| chore-name vs task-name mismatch | **No.** The daemon's own `_build_tasks()` + `_yielded_task_names()` return all five names exactly |

**Dead end — do not repeat:** `lsof -p <daemon-pid>` shows no log file held open, because
`state.log_line` opens/appends/closes per line. The method that worked was cheaper than any
runtime probe: **read the path RESOLVER** (`log_dir()` + its env override), not the conventional
path.

### SUPERSEDED — do NOT carry forward

- *"the yield has never handed over anything on this host"* — false; it has yielded five chores
  since Aug 5 20:43.
- *"zero `chore-coordination` lines in the daemon's whole lifetime"* — false; wrong file. The
  project-scoped `.janitor/logs/daemon.log` is written by per-session shims, not the daemon.
- *"the daemon ran `version-update` three hours after the server came up"* — false; that was the
  per-session shim `[s:643908a6]`.
- The transition-flag inference built on the zero-line count (`daemon.py:2281`) — sound reasoning,
  worthless input.

### ⏵ COLUMN 2026-08-07: `dev` -> `human_review` (item 1 is RELEASED; only the owner's item remains)

`claimed-chore-stale` shipped in **v2.5.0**. Three of four acceptance boxes are ticked, and the
remaining one — the chore⇄token⇄stamp⇄bound table agreed on the #126/#111 threads — is cross-repo
negotiation only the owner can initiate.

`dev` asserted someone was developing this; nobody was. `human_review` is the true state, and it
also clears the `prose-frontmatter-mismatch` the reconciliation detector flagged (the prose said
"owner's call" while the column claimed active development). No `blocked-by:` is set because
nothing here is blocked by another TRDD — it waits on a person, which is what this column means.

### ✔ ITEM 1 SHIPPED — `claimed-chore-stale` (`1e803e47`, released in v2.5.0)

`scripts/detectors/claimed-chore-stale.py` + the pure `scripts/lib/claimed_chore_watch.py`,
hourly in the dispatch roster, the MIRROR of `global-chore-blackout`. 14 unit tests; full suite
14605 passed.

- **Evidence channel CONFIRMED FIRST.** All five claimed chores had fresh
  `~/.claude/janitor-control/<chore>.last-run.ts` stamps before a line was written, so this is
  not another guard watching an empty set.
- **Verified both ways**: silent on the healthy host; fires on a stamp frozen 4 days back
  (96h against an 11m bound) — janitor#221's exact shape.
- **Bound**: `max(3 x cadence, cadence + 600s)`. The floor matters — 3x alone gives
  `oauth-rotator-tick` a 180s window, inside normal jitter, which is the issue-#9 false-positive
  `daemon_watchdog` already paid for.
- **Unknown chore ⇒ SKIPPED, never guessed** (per-chore capability claims can name chores this
  version has never heard of).
- **`no-evidence` is itself a finding**: a claimed chore with no stamp means the watchdog is
  blind to it, and silence about that is how a guard becomes decorative.
- **SURFACE-ONLY** — no un-yield. That decision is still open (below).

### ✔ UN-YIELD DECISION: **NO — alarm only.** (recorded 2026-08-06)

The janitor MUST NOT resume a chore whose claim has gone stale. Three reasons, in order of
weight:

1. **It is the rule, not a judgement call.** TRDD-LU0C5KAR (owner directive 2026-07-17) made
   coordination BINARY: responsibility follows process liveness, a live server owns the
   absorbed set outright, and *"a server that runs without executing one of them is a SERVER
   bug to fix there, never a janitor guard to keep."* An un-yield is precisely the janitor-side
   guard that directive removed. `claude-code-plugin-rollout-staleness` records the same
   conclusion reached independently: **do NOT add a janitor-side fallback.**
2. **Two writers is a worse failure than zero.** These are machine-GLOBAL, once-only chores.
   `marketplace-refresh` running concurrently in both the server and a resumed daemon is the
   duplicated bulk `claude plugin marketplace update` that issue #7 exists to prevent; a
   double `oauth-rotator-tick` races two writers onto one credential store. A wedged chore is
   visible and recoverable; a corrupted credential store is neither.
3. **The stale-stamp signal cannot distinguish the cases that need opposite responses.** A
   stamp goes stale identically for a wedged chore, a restarting server, and a server that
   simply does not write stamps (`no-evidence`). Hysteresis narrows the third-party flap but
   cannot separate 1 from 2 — and guessing wrong un-yields against a live owner.

**What would change this:** a positive liveness signal from the claim-holder distinct from its
completion stamp (a heartbeat, or an explicit release). That is item 2's contract to negotiate,
not something to infer from staleness. Until such a signal exists, alarm-only is the correct
shape — and it is what shipped.

### ✔ REPLAY CHECK — would janitor#221 have alarmed? YES, within ~11 minutes

`oauth-rotator-tick` cadence 60s ⇒ bound `max(3x60, 60+600)` = **660s**. The #221 wedge ran
**3.7 days** (~319,000s) without a completion — 483x the bound. The detector runs hourly, so
the alarm lands at the first fire after the bound elapses: **worst case ~1 hour**, against 3.7
days of silence. The `no-evidence` branch covers the other shape (a wedge that also stops
stamping), so neither failure mode is silent.

Honest limit: this is an argument from the bound and the recorded duration, not a replay
against #221's actual stamp file — that file no longer exists, so the arithmetic is the
strongest available evidence. It is not close enough to the threshold for the difference to
matter.

### NEXT ACTION (one step) — item 2, and it is OUTWARD-FACING

Only item 2 remains: the chore⇄token⇄stamp⇄bound table, agreed on the #126/#111 threads. That
is cross-repo negotiation and the owner's call to initiate. The janitor-side half is shipped and
its bounds are now concrete enough to propose as the table's first column.

### Item 2 is OUTWARD-FACING and cannot be closed here

The chore⇄token⇄stamp⇄bound table must be *agreed on the #126/#111 threads* — cross-repo
negotiation, owner's call to initiate. The janitor-side half (item 1) is buildable alone and is
no longer blocked.

## WHY (three incidents, one shape)

When the ai-maestro server CLAIMS a janitor-daemon chore, the janitor stops running it —
and today nothing verifies the server actually RUNS what it claimed:

- **janitor#221**: the server-absorbed rotator tick stopped COMPLETING for 3.7 days
  (wedged between two slot captures); rotation was OFF; the owner rotated by hand. The
  janitor's side had zero alarm — `daemon_watchdog` covers only the janitor's OWN tasks.
- **ai-maestro#111**: a merely-alive server suppressed chores it never claimed — six
  chores unowned for 10-14 days (fixed on our side by claim-aware yield d45a843a, but
  the fix only checks the CLAIM, not the EXECUTION).
- **Today (item 5's evidence)**: `user-plugins-update` + `version-update` yielded to the
  server under the claim; the janitor's own user-scope pin did not converge for a day.

The claim handshake answers "who owns this?" but not "is the owner doing it?" — and a
claimed-but-wedged chore is strictly worse than an unclaimed one, because the fallback
(our daemon) is suppressed exactly then.

## The task (both halves, RECEIVE-model only — never call in)

1. **Janitor half — watch the claim-holder's completion stamps.** For every chore the
   yield hands to the server, the janitor keeps a staleness watchdog on that chore's
   completion evidence (the `~/.claude/janitor-control/<task>.last-run.ts` stamps
   ai-maestro#111 asked the server to write, or the server's own status files it
   already deposits). Claimed + stale past 3x cadence ⇒ a LOUD finding (ledger +
   heartbeat), and — decision needed — whether the janitor may RESUME a chore whose
   claim has demonstrably gone dead (un-yield on proof, with hysteresis so a restart
   blip doesn't flap ownership).
2. **Contract half — pin the vocabulary with the server.** One documented table:
   chore name ⇄ capability token ⇄ completion-stamp path ⇄ staleness bound. Today the
   mapping is implicit in two codebases. Route through ai-maestro#126 item 1 (the
   chore-claim inventory ask, already filed) + #111; the janitor's ARCHITECTURE.md gets
   the table, the server repo mirrors it.
3. **Escalation shape**: claimed-and-stale findings must reach the human via the normal
   channel (findings ledger + notify), naming WHICH side owns the fix — the #221 wedge
   would then have surfaced in hours, not days.

## Acceptance

- [ ] the chore⇄token⇄stamp⇄bound table exists in ARCHITECTURE.md and is agreed on the
      #126/#111 threads — OUTWARD-FACING, owner's call to initiate
- [x] watchdog fires on claimed-but-stale within 3x cadence (test: freeze a stamp) —
      `claimed-chore-stale` (`1e803e47`); verified silent on the healthy host and firing on a
      stamp frozen 4 days back. Bound is `max(3 x cadence, cadence + 600s)`; the floor is
      documented in `claimed_chore_watch.DEFAULT_MIN_GRACE_S` and is not a widening of the 3x
      headline, it is what makes 3x usable at a 60s cadence
- [x] un-yield-on-dead-claim decision recorded — **NO, alarm only**, with why (see STATE):
      TRDD-LU0C5KAR made coordination binary and removed exactly this guard; two writers on a
      machine-global chore is worse than zero; and a stale stamp cannot distinguish a wedge
      from a restart from a server that never stamps. Revisit only if the claim-holder
      publishes a liveness signal distinct from its completion stamp — that is item 2's
      contract, not something to infer from staleness
- [x] replay check: **YES, within ~1h** — `oauth-rotator-tick`'s bound is 660s against #221's
      3.7-day wedge (483x), detector cadence hourly. Argued from the bound and the recorded
      duration, NOT replayed against #221's actual stamp file (it no longer exists) — the
      margin is far too large for that gap to change the answer

## Pointers

- Claim machinery: `lib/harness_backend.py` (`claimed_chores`, `server_owns_every_chore`,
  `orphaned_chores`), daemon yield (`_task_yielded_to_server`, d45a843a).
- Existing one-sided watchdog: `lib/daemon_watchdog.py` (per-session shims for OUR tasks).
- Incidents: janitor#221, ai-maestro#111, janitor#134; sync ask: ai-maestro#126 item 1.
- Memory: [[janitor-daemon-handover-unowned-chores]], [[janitor-two-runtime-backends]].
