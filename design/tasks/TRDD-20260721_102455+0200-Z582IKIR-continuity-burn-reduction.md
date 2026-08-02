---
trdd-id: Z582IKIR
title: Heartbeat continuity + burn reduction — reload-churn guard, giant-session pump-down, rotation-masks-burn escalation, cheap handoff+clear primitive
column: backburner
created: 2026-07-21T10:24:55+0200
updated: 2026-07-21T16:20:00+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
scope: project
severity: high
relevant-rules: [6.1]
related-trdd: [3KDN6O9Z, X92VBFNF, FENWWB4E, TKNSTP82, EUWIHP0G, D3PROACT]
implementation-commits: [224da88, c3bde7d, 75b2860, 28c1777]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**PARTIALLY IMPLEMENTED (2026-07-21).** P1 (handoff+/clear primitive) shipped in `224da88`.
F1 (reload-churn guard) shipped in `c3bde7d` **then its HOOK HALF was REMOVED in `75b2860`** — the
UserPromptSubmit `reload-guard` hook (meant to block a human-typed `/reload-plugins` above a context
threshold) was a CONFIRMED NO-OP: a built-in `/reload-plugins` fires ZERO hook events of any kind
(MEASURED — the `claude-code-hook-types` memory `^no-plugin-reload-hook`; UserPromptSubmit fires for
PROSE only, and `/reload-plugins` is a CLI action that never expands into a prompt, so
UserPromptExpansion doesn't apply either). The premise was refuted in the corpus the SAME DAY the
guard shipped — a recall-before-building miss. **What SURVIVES from F1** = the dispatch auto-defer
(`_phase_plugin_reload` defers the janitor's OWN `[janitor-reload]` at high context — needs no hook) +
the shared `reload_guard_should_block` predicate/threshold. A human-typed `/reload-plugins` is
simply NOT guardable (no hook sees it); the auto-defer is the only place the churn is prevented.
**AGENT-side guard added (`28c1777`):** F1's INTENT — don't reload at high context — was moved to
where the agent actually sees it. A skill's DESCRIPTION is always surfaced to the agent's context
(a hook or a plugin command is not), so `/janitor-reload-plugins` + `/janitor-reload-skills` now
WARN (description + a dedicated body section) not to reload at ≥350k context used (shrink first via
`/janitor-handoff-and-clear`, then reload — a broken cache re-bills the whole window at 1.25×), and
`/janitor-compact-context` steers to PREFER `/janitor-handoff-and-clear` over `/compact`. This
guards the AGENT; a HUMAN typing the raw built-in stays unguardable by design.
The standalone [[TRDD-GRHP2YHP]] resume-push fix is a sibling of the same continuity work.
F0 (beacon age-trigger), F2 (giant-session pump-down), F3 (rotation-masks-burn escalation) remain
DESIGN-ONLY — do not code those without a follow-up approval to move them out of `backburner`.

**INCIDENT that motivates this TRDD:** a ~400k-token main session, kept alive
by the janitor's 15-min heartbeat, burned all 3 of the owner's Claude accounts
over 2 days. AgentlensPro root-cause: (1) the heartbeat re-bills the full
context every fire; (2) each `[janitor-reload]` → `/reload-plugins` breaks the
prompt-cache prefix → a full cache-CREATE at 1.25× instead of a 0.1× cache-read;
(3) the OAuth rotator masked the runaway by feeding it all 3 credentials in
turn instead of surfacing the anomaly. Evidence:
`reports/token-attribution/20260702_144812+0200-burn-math-impl.md` and the
AgentlensPro diagnosis referenced there (no separate `burn-investigation/`
report exists in this repo — token-attribution is the closest prior art).

**R1 VERIFIED (2026-07-21, PASS)** — gates P1 below. Full evidence:
`reports/continuity-trdd/20260721_102438+0200-r1-clear-sessionstart-verification.md`.
Summary: `/clear` DOES fire `SessionStart` (source=`"clear"`, per
code.claude.com/docs/en/hooks) and DOES destroy the session-scoped heartbeat
cron (per code.claude.com/docs/en/scheduled-tasks: "starting a fresh
conversation clears all session-scoped tasks"; only `--resume`/`--continue`
restores it). But `on-session-start.py`'s re-arm nudge
(`_cron_liveness_nudge`) is **unconditional on `source`** — it fires on every
SessionStart, `clear` included — so the freshly-cleared session is told to
`CronList` + `/janitor-arm` on its very first turn. The primitive is
wireable: P1 is UNBLOCKED.

**NEXT ACTION (when promoted out of backburner):** split into 4 per-component
implementation TRDDs (F1, F2, F3, P1 below), each depth-1 with its own
npt/eht, `blocked-by: [Z582IKIR]` pointing back here for shared context. Do
NOT implement all 4 in one PR — they touch different hooks/detectors and
have independent test surfaces (rule: one atomic task per TRDD).

**Tension flagged, not resolved here:** F2 (drop to MAINTENANCE on a giant
session) reads as a compaction-adjacent policy, and the owner has a
standing "backstop-only compaction" rule (auto-compact/enforcement should be
the last resort, not routine). F2 does NOT compact anything — it only skips
DETECTOR work on a fire, which is a strictly cheaper action than compaction.
The two are compatible in principle but this needs an explicit owner
sign-off before F2 leaves backburner, because "shrink what happens on a
giant-context fire" is close enough to the compaction topic to warrant it.

## Motivation (compressed)

Three independent burn amplifiers on top of the base heartbeat cost
(`cost ≈ turns × per-turn-context`, per `~/.claude/rules/token-economy-agents-and-scenarios.md`):

1. A large session's heartbeat fire re-bills its ENTIRE context every ~15 min
   regardless of whether anything drifted (`dispatch.py` full mode).
2. Every `[janitor-reload]` forces `/reload-plugins`, which breaks the
   prompt-cache prefix — the NEXT turn (heartbeat or user) pays a
   cache-CREATE (~1.25×) instead of a cache-READ (~0.1×) on the WHOLE
   context. On a 400k-token session this is a ~500k-token tax per reload,
   and reloads recur every time any plugin updates.
3. The OAuth rotator's job is to keep the session ALIVE across account
   limits — which is correct behavior for a legitimately busy session, but
   is exactly the WRONG behavior for a runaway: it silently spread the burn
   across 3 accounts instead of surfacing "this session is burning
   anomalously fast" to the human who could have killed it after account 1.

## F1 — reload-churn guard (highest priority)

**Problem:** `[janitor-reload]` unconditionally asks the session to run
`/reload-plugins`, paying the full cache-break tax regardless of context size.

**Design:** the dispatcher stub (`scripts/dispatcher-stub.py`) already
auto-rolls the HEARTBEAT itself to the newest cached `dispatch.py` on every
fire — the session-level `/reload-plugins` only refreshes hooks/skills, not
the heartbeat's own code path. So on a LARGE session, `[janitor-reload]` is
mostly redundant work bought at cache-break price. Gate it: read the live
context size (reuse `token_meter.resolve_context`, the same reader
`pre-tool-context-usage.py` uses) at the point `dispatch.py` would emit
`[janitor-reload]`; above a threshold (config knob, default candidate: the
same 60% band `pre-tool-context-usage` treats as ADVISORY), DEFER instead of
emit — re-check on the next fire rather than force the reload now. Below the
threshold, behavior is unchanged.

**Open design questions to resolve before dev:**
- Defer-forever risk: a session that never drops below threshold never picks
  up hook/skill updates. Cap the defer (e.g. force-reload after N consecutive
  deferred fires, or at the NEXT natural cache-cold boundary — a rate-limit
  recovery, a `/clear`, a `/compact` — since those already pay a cache
  rebuild, so riding the reload on top is nearly free).
- Must stay fail-soft (PRRD S6.1): a broken context-size read must fall back
  to today's unconditional-reload behavior, never to silent no-reload.

## F2 — heartbeat-pump-on-giant-session

**Problem:** above a certain context size, a FULL heartbeat fire (running all
due detectors) re-bills the whole context for marginal drift-detection value,
when the session is already the dominant cost driver on the account.

**Design:** reuse the existing FULL/MAINTENANCE/STOP heartbeat mode machinery
(`dispatch._resolve_heartbeat_mode`) — add a size-based trigger alongside the
existing global-stop/pause triggers: above a context threshold, a fire
auto-drops to MAINTENANCE (cache-refresh only, no detector fires, no daemon
chores) instead of FULL, without requiring `/janitor-maintenance-mode` to be
invoked by anyone. Must be strictly LOCAL to the giant session (never a
global mode) — this is a per-session cost decision, not a fleet one, per the
per-project channeling invariant (TRDD-X92VBFNF).

**See STATE block above — the compaction-adjacency tension is unresolved and
blocks promotion out of backburner.** Candidate mitigation to evaluate at
design time: MAINTENANCE mode already exists and does NOT touch context size
— it only skips detector work — so F2 is arguably orthogonal to the
backstop-only compaction rule (which governs shrinking context, not skipping
heartbeat chores). Get explicit sign-off before implementing.

## F3 — rotation-masks-burn

**Problem:** the OAuth rotator's job (stay alive across account limits) is
antagonistic to burn visibility when the CAUSE of hitting a window's cap is
an anomalous, not a legitimate, burn rate — rotating silently spreads a
runaway across every account instead of stopping it after the first.

**Design:** at the rotation decision point (`oauth_rotator/rotator.py`
`cmd_auto`/`cmd_tick`, or the daemon's `task_oauth_rotator_tick`), when a
rotation fires BECAUSE a window hit its cap, cross-check the existing
`window-burn-rate` detector's burn-ratio classification
(`lib/token_burn.py::evaluate_trips`, already used by
`detectors/window-burn-rate.py`) for that account/window at the same moment.
If burn is ALSO anomalous (ratio ≥ the detector's existing threshold) at the
rotation moment, escalate via the existing human channel
(`lib/notify.py::push`, TRDD-4649ZLE0 — Tier 1 desktop notification,
sev-gated, deduped, capped) INSTEAD OF / IN ADDITION TO rotating silently.
Reuse existing plumbing end-to-end — no new notification channel, no new
burn-math, just a cross-check at the rotation decision point.

**Open design question:** should an anomalous-burn rotation be `HOLD-FOR-ACK`
(rotate only after human ack) or merely `ESCALATE` (rotate as today, but push
loudly)? Holding risks stalling a legitimately busy session that the human
is asleep for; escalate-only risks the same 3-account drain repeating before
the human sees the push. Recommend escalate-only for v1 (matches every other
`notify.py` caller's fail-open posture) with a v2 follow-up TRDD for
block-pending-ack once push reliability is proven in the field.

## P1 — handoff + `/clear` + resume-on-fresh-session continuity primitive

**Gated on R1 — PASS, see STATE block. Design may proceed.**

**Problem:** `/compact` is the current continuity mechanism across a
context ceiling or a planned pause, but its steady-state cost is
base-context + a compaction SUMMARY riding forward in the transcript
forever after. A `/clear` resets to base-context ONLY, with no residual
summary — cheaper in steady state IF the resumed session can cheaply
recover what it needs to continue.

**HARD REQUIREMENT (owner directive, verbatim intent): the handoff MUST be
as CONCISE AS POSSIBLE.** The resumed session's first read is the tax this
primitive pays every time it's used — it must not become a second bloated
context. `/clear` is UNRECOVERABLE (no compaction summary, no scrollback) —
the handoff must be COMPLETE before firing, because there is no second
chance to recover missed state afterward.

**DESIGN PRINCIPLE — CONCISE-BUT-EXHAUSTIVE (owner directive, verbatim
intent):** the handoff must mention ALL things relevant to the future
session — omit nothing material — BUT every big chunk of information is
REPLACED with a LINK to the wikimem atom(s) (by `id:ATOM-xxxx-xxxx`) or the
whole wikimem page, instead of being inlined. **The memory system IS the
payload store; the handoff is only a short INDEX of pointers.** The resumed
session reads each chunk on-demand via `memgrep recall`/`find` when (and
only when) it actually needs that detail. This is how the handoff stays
cheap to read yet loses nothing: exhaustive COVERAGE by REFERENCE, never by
inclusion. Concretely: a line like "decided X because Y, see
`ATOM-xxxx-xxxx`" is correct; pasting the full Y reasoning inline is not,
even if Y is short — the link is the payload, the handoff is the table of
contents.

**DERIVED REQUIREMENT — harvest-before-handoff (EHT on P1's implementation
TRDD):** authoring a concise-but-exhaustive handoff PRESUPPOSES the
relevant knowledge has already been HARVESTED into wikimem — a link to an
atom that does not exist yet is not a pointer, it's a lost fact. So the
primitive's write step is two ordered sub-steps, not one:
(a) ensure every piece of material session state (decisions, in-progress
reasoning, non-TRDD facts) is captured as wikimem atoms/pages FIRST — this
is exactly the janitor's existing memory-write discipline
(`~/.claude/rules/markdown-memory-recall.md`'s "WRITE / UPDATE AFTER
SOLVING" contract, and the `janitor-memory-subconscious-agent` /
`/janitor-memory-write` surfaces already shipped in this plugin);
(b) only THEN emit the handoff itself, as a short list of ATOM-id / page
links into that already-harvested corpus. P1 therefore has a hard
dependency on the janitor memory subsystem being current at handoff time —
if step (a) is skipped or incomplete, step (b) produces links to nothing
and the concise-but-exhaustive property silently fails (concise, but no
longer exhaustive). The implementation TRDD must make (a) a precondition
check, not an assumption — e.g. reuse `memorize-nudge`'s
code-outran-the-wiki detection to refuse/warn before firing `/clear` on a
session with un-harvested material state.

**Design sketch (to be detailed at dev time, not fully specified here):**
1. Reuse `/janitor-write-handoff` (`.janitor/state/agent-handoff.md`) as the
   payload location — it already exists and is agent-authored, not a new
   file format.
2. Concision contract: the handoff is NOT a transcript digest. It is:
   (a) the in-progress TRDD id(s) + one line each (their `## STATE` blocks
   are ALREADY the authoritative detail — `on-session-start-trdd-state.py`
   already surfaces those on next SessionStart, `clear` included per R1 §3,
   so the handoff must NOT duplicate STATE-block content, only POINT at it —
   this mirrors the existing compact-handoff dedup logic in
   `on-session-start-trdd-state.py` that already avoids doubling STATE
   blocks after a fresh `precompact-handoff.md`, TRDD-498LEWZ4);
   (b) any fact NOT already captured in a TRDD/file (a decision made this
   session, a pending question for the user); (c) nothing else. Target: a
   few hundred bytes to low KB, not the tens-of-KB a compaction summary runs.
3. Sequencing is `/janitor-write-handoff` → verify it landed → `/clear` →
   the R1-verified re-arm nudge brings the cron back → the TRDD-STATE hook +
   the handoff pointer bring the fresh session up to speed on its FIRST
   turn, cheaply.
4. Secondary finding from R1 (see the verification report): `reload-acked.ts`
   / `skills-reload-acked.ts` are seeded only on `source in (startup,
   resume)`, not `clear` — confirm at dev time whether a `/clear` mid-session
   needs the same re-seed, or whether leaving them stale is harmless (a
   stale ack just means a `[janitor-reload]` that was already correctly
   pending stays pending — likely benign, but verify, don't assume).

**THE CANONICAL P1 FLOW (owner directive, verbatim intent — resolves the R1
open gap "what triggers the first post-clear turn, unattended"):** restore
the cron after every `/clear` via the hooks, exactly the janitor's EXISTING
pattern — `resume-directive.txt` + `agent-handoff.md` +
`precompact-handoff.md` — adapted from `/compact` to `/clear`. Any janitor
info that `/clear` would otherwise lose is kept in a PERSISTENT TEXT FILE;
the moment the janitor is next running a turn, the cron/dispatch READS that
file and resumes. Concretely, in order:
1. Write the concise-but-exhaustive, link-only handoff (§ above) AND a
   `resume-directive.txt`-shaped pointer to persistent files — this is not
   new machinery, it is the SAME two files (`agent-handoff.md`,
   `resume-directive.txt`) the compact-resume path already writes, just
   authored before `/clear` instead of before `/compact`.
2. Fire `/clear`.
3. `SessionStart` fires with `source: "clear"` (R1, PASS) → the existing
   unconditional re-arm nudge (`_cron_liveness_nudge`) restores/re-arms the
   heartbeat cron for this project.
4. The re-armed cron's FIRST fire reads the persisted handoff/resume-directive
   files (the same read `dispatch.py` already does for the rate-limit and
   post-compact resume flags) → emits `[janitor-resume]` → the session
   resumes from the link-only handoff, pulling any deeper detail from
   wikimem on demand via `memgrep`.

**CRITICAL DESIGN NOTE — the step-3→4 bootstrap gap.** A `SessionStart`
hook is a SHELL script; it cannot itself call `CronCreate` (that is a MODEL
tool, only callable from inside a model turn). So step 3's "re-arm nudge"
is only TEXT injected as context — it still requires a MODEL TURN to run
and actually invoke `/janitor-arm`. On a genuinely unattended machine
(nobody at the keyboard to trigger that turn), WHAT causes that turn to
happen is the open question this design must resolve before P1 can be
implemented. Candidate bootstraps, to choose among at implementation time:
- **(a) harness auto-turn post-`/clear`** — the platform itself runs a
  model turn immediately after `/clear` to process the SessionStart-injected
  context (the same way a fresh `startup`/`resume` session's first turn
  processes hook context without a human prompt). **STATUS: UNVERIFIED —
  this is the fact still to confirm** (distinct from R1, which only proved
  the HOOK fires, not that a turn auto-runs afterward). If true, this is
  sufficient on its own and needs no extra machinery.
- **(b) daemon-injected `/janitor-arm` (fallback, uses infra already
  shipped)** — the global daemon's fleet scanner
  (`lib/fleet_scan.py`/`session_liveness.py`) detects a session that is
  `/clear`-fresh (tiny transcript, no matching armed cron) and injects the
  literal command via the EXISTING `lib/fleet_inject.py` +
  `lib/terminal_trigger.py` machinery (the same soft/enqueue injection path
  `janitor-compact-context`, `janitor-reload-plugins`, and the fleet-stop
  beat already use — TRDD-0GPQROC1's soft-by-default policy applies here
  too). No new injection channel; only a new DETECTION rule
  ("cleared-but-unarmed") feeding the existing injector.
- **(c) hybrid** — try (a) implicitly (it costs nothing extra if the
  platform already does it); treat (b) as the guaranteed backstop so P1
  does not silently depend on an unverified platform behavior. **Recommended
  default assumption until (a) is verified: design for (b) as the
  load-bearing mechanism, with (a) as a free bonus if it turns out to be
  true** — this keeps P1 correct even in the worst case (no auto-turn) and
  avoids a second R1-style verification blocking implementation.

This bootstrap question is a hard NPT on P1's implementation TRDD: (a) must
be verified (or (b) built and proven) BEFORE P1 ships, or the whole
handoff+clear primitive silently degrades to "works only if a human happens
to send the next prompt" — indistinguishable from just not having the
primitive at all on a truly unattended run.

**Explicitly out of scope for this TRDD:** deciding WHEN to prefer
handoff+clear over `/compact` — that's a policy call (probably: prefer clear
when the in-flight work is fully captured in TRDDs/files already, prefer
compact when there's live scratch reasoning not yet durably written down).
Leave that policy to the implementation TRDD once F1-F3 have established
what "giant session" and "reload-churn" thresholds actually are in practice
— P1 benefits from the same context-size reader F1/F2 use.

## Derived-task check (per the DERIVED-tasks directive)

Evaluated consequences of each component above; the ones that produce
follow-on obligations are already folded in as "open design questions" /
NPT-candidates within F1-F3-P1 rather than spawned as separate TRDDs yet,
because this TRDD is still `backburner` (pre-approval, pre-split). At
promotion time, each of the following becomes an explicit NPT or EHT on its
component's child TRDD:
- F1's defer-forever risk needs a cap mechanism BEFORE F1 ships (NPT).
- F2's compaction-adjacency needs owner sign-off BEFORE F2 ships (NPT,
  blocks the whole component).
- F3's block-vs-escalate choice needs the escalate-only v1 to ship with a
  measured false-positive rate before block-pending-ack is even proposed
  (EHT, follow-up TRDD, not this one).
- P1's reload-ack staleness-after-clear needs a verify-or-fix pass (EHT,
  folded into P1's own implementation TRDD rather than spawned separately —
  it's a one-line consequence of the SAME hook file P1 already touches).

## Notes and lessons learned

[^1]: [id:ATOM-CLEAR-CRON-KILL, status:valid, keywords:"clear kills heartbeat cron session-scoped tasks cleared fresh conversation continuity primitive", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT assume `/clear` merely resets context like `/compact` does, BECAUSE
  `/clear` starts a genuinely fresh conversation and destroys ALL
  session-scoped scheduled tasks (per code.claude.com/docs/en/scheduled-tasks)
  — only `--resume`/`--continue` restores them, not `/clear`. DO rely on the
  SessionStart re-arm nudge (verified unconditional on `source` in
  `on-session-start.py`) to recreate the cron on the next turn instead of
  assuming it survives.
