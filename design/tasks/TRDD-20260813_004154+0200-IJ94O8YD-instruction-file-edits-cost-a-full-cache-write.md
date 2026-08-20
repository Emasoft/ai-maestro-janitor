---
trdd-id: IJ94O8YD
title: Editing an injected instruction file mid-session costs a full cache re-write — 150k tokens, measured
column: complete
created: 2026-08-13T00:41:54+0200
updated: 2026-08-20T18:40:00+0200
current-owner: janitor-main-session
task-type: refactor
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-B07VPT2G]
---

# The one avoidable cache cost the corpus actually shows

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Derived from TRDD-B07VPT2G's measurement (2026-08-13), which refuted its own premise and
surfaced this instead.** Filed as a card rather than a paragraph because B07VPT2G's history is
exactly what happens otherwise: the same finding was buried in a bullet, correctly identified as
buried in a bullet, and then re-buried in a section by the card that identified it.

**The measurement** (`agentlenspro get_cache_break_causes`, 412 request bodies / 16 sessions,
report at `reports/b07vpt2g/20260813_004101+0200-idle-ttl-expiry-refutation.md`): the ONLY
significant `expected=false` cause is **CLAUDE_MD_CHANGED — 150,824 cache_creation tokens**.
Actor: *"claudemd block changed at pos 1: …/.claude"*. Everything else is cold start, compaction,
or append-only growth.

**The cause is the janitor maintaining its own rules.** Files under `~/.claude/rules/` are
injected into the prompt prefix, so editing one mid-session invalidates it. On 2026-08-12 the
rules trim (`29121d8b`) and the preamble dedup (`83a68674`) each rewrote several — the very work
that BOUGHT context-floor headroom paid a full cache write to do. The work was right; only the
timing was wrong, and the timing is free to change.

### 2026-08-13 03:29 — SECOND MEASUREMENT TAKEN, AND IT REFUTES THE HEADLINE

`agentlenspro get_cache_break_causes`, 336 bodies / 16 sessions, raw JSON at
`reports/ij94o8yd/20260813_032943+0200-cache-break-causes-second-measurement.json`:

| cause | expected | cache_creation | % |
|---|---|---|---|
| COMPACTION | yes | 652,917 | 56.9 |
| **UNCLASSIFIED** | **no** | **453,881** | **39.5** |
| NORMAL_GROWTH | yes | 41,494 | 3.6 |

**`CLAUDE_MD_CHANGED` does not appear at all.** This card's headline — *"the ONLY significant
`expected=false` cause is CLAUDE_MD_CHANGED"* — does not survive its own confirmation box.

**But do NOT flip to "the first measurement was wrong".** The windows differ (412 bodies then,
336 now) and the rules edits that caused it (`29121d8b`, `83a68674`, 2026-08-12) have aged out.
Both readings are true of their windows, and together they say something the first could not:
**CLAUDE_MD_CHANGED is EPISODIC, not structural** — it appears exactly when rules are edited and
is absent otherwise. That is a much weaker basis for a standing rule than "the dominant avoidable
cost", and the acceptance boxes below must be re-scoped accordingly rather than deleted: 150k
tokens on the days it fires is still worth timing correctly; it is simply not the main event.

**The main event is something this card never considered:** ONE avoidable break, 453,881 tokens
($2.84), in ONE session — actor `usertext block changed at pos 515: msg[363] system`. A `system`
block MUTATING mid-prefix, nothing to do with instruction files. agentlenspro could not localise
it (that is what UNCLASSIFIED means), so the mechanism is **UNKNOWN, not assumed** — a
lean-worker is diffing the adjacent captured bodies now. Candidates to confirm or rule out: a
`<system-reminder>` task list that re-renders when tasks change, a hook `additionalContext`
injection stripped retroactively (issue #79's documented mechanism), or a compaction artifact.

**Method note — why this measurement had to run HERE.** The card's own reasoning says a subagent
has its own prefix; a subagent measuring live cache breaks would measure its own. The forensic
diff is different: it reads bodies ALREADY captured on disk, so it delegates safely. Measure
live, analyse anywhere.

## The tension to resolve — do NOT assume the obvious fix

"Never edit rules mid-session" is unworkable as stated: the janitor edits its own rules as a
normal part of its job, and a rule fix that waits for a session boundary is a rule fix that does
not ship. The real question is WHERE the edit happens:

  - a **subagent** has its own prefix, so its edits cost the parent nothing — but the parent must
    not then read the edited file back, or it pays anyway;
  - a **session-start** window is free but arrives on someone else's schedule;
  - a **detector/script** edit is free of any model prefix — the best case, and the one the
    janitor already uses for `rules_installer`.

## ⏵ 2026-08-13 12:45 — A THIRD WINDOW WAS AVAILABLE AND COULD NOT BE MEASURED

A natural experiment landed today: `~/.claude/rules/proactive-delegation.md` was edited MID-SESSION
(the USER revoked the "no subagents unless requested" line and the revocation was recorded in that
file). That is precisely this card's trigger — an injected instruction file, rewritten inside a
live session, at a known time — so a third `get_cache_break_causes` window would test the EPISODIC
claim directly: `CLAUDE_MD_CHANGED` should reappear, and should be roughly the size of one rules
file's worth of prefix.

**It could not be taken.** `agentlenspro get_cache_break_causes` fails with
`cannot reach http://localhost:4316/mcp: read ECONNRESET` — the MCP server is not up in this
session. Recorded rather than worked around: the card's own method note says this measurement must
run in the MAIN session (a subagent would measure its own prefix), so there is no delegation that
substitutes for it, and an estimate would be exactly the kind of unmeasured claim the second
window already refuted once.

**Next time the server is up, this is a free measurement** — the edit is already in git
(`~/.claude/rules/` is outside the repo, but the session and its timing are known), so the window
only has to be sampled before it ages out, the way the first window's rules edits did.

## Acceptance

- [x] The cost is confirmed a second time — **TAKEN 2026-08-13 03:29, RESULT NEGATIVE.**
      `CLAUDE_MD_CHANGED` is absent from the second window entirely; the box did its job by
      refuting the law rather than blessing it. Revised finding: the cost is EPISODIC (fires on
      rules-edit days, ~150k tokens) and is NOT the dominant avoidable cause. See the dated
      section above and the raw JSON in `reports/ij94o8yd/`.
- [x] **The UNCLASSIFIED 453,881-token break — ANSWERED 2026-08-13, recorded 2026-08-16.** The
      forensic diff completed and its report
      (`reports/ij94o8yd/20260813_forensics-unclassified-cache-break.md`) sat unread for three
      days while this box still said "do not guess it". Verdict, in the order that matters:

      1. **The pinned incident: CANNOT DETERMINE.** `~/.agentlens/otel-bodies/` had rotated to
         empty, `break_cause`/`culprit_fingerprint` are 100% NULL across all 5,730 `api_calls`
         rows (the classifier computes them transiently and never writes them back), and no row
         carries 453,881 cache_creation tokens. The box asked for the exact call and the exact
         call is gone.
      2. **A COMPARABLE break in the same session was fully diffed**, reconstructed from the
         surviving CAS store: 553,919 cache_read → 535,371 cache_creation across two calls 51 s
         apart, with parts 0–815 of 925 byte-identical. The first divergence is one message whose
         VISIBLE TEXT IS IDENTICAL in both — the only delta is that
         `"cache_control":{"type":"ephemeral","ttl":"1h"}` present on it in the earlier request is
         absent in the later one (762 → 714 bytes, exactly the annotation's length).
      3. So the mechanism is a **FOURTH** one, none of this card's three hypotheses: **sliding
         `cache_control` breakpoint relocation** — the marker is carried by the currently-last
         message and moves off the old one as the conversation grows. **Not ours to fix.** It is
         client-side behaviour of Claude Code itself, not the janitor editing instruction files.
      4. **`msg[N]` fingerprints are partly an artifact.** Scanning for `messages[363]` found 786
         "changes" across 59 sessions, and a direct sha check showed the earlier body's
         `messages[363]` reappearing UNCHANGED at `messages[364]` in the later one — the array
         grew, so absolute-index diffing reports a change on ordinary turns. Treat any
         `msg[N] <block>` actor string as suspect until corroborated.

      **What I did NOT verify first-hand, stated so it is not read as settled:** the causal step
      in (3). The report proves the annotation was removed; it says the marker was *"presumably"*
      placed on the new last message and did not confirm where it went. If Claude Code keeps more
      than one breakpoint, removal alone would not orphan the prefix, and the true cause would
      still be open. The byte-level diff is solid; the causal attribution built on it is not.

      **ATTEMPT 1 (2026-08-13 ~12:3x–13:2x) — ABANDONED, no result.** A background lean-worker
      was dispatched to diff the captured bodies. It ran ~45 min without returning and was
      STOPPED, not left to spin. Its own final line on being stopped was *"Waiting for the
      background analysis job to finish before proceeding"* — so it had spawned a CHILD job and
      was blocked on it, never returning a result of its own; an earlier progress line showed it
      reading the agentlenspro CLI help, i.e. reaching for the LIVE tool that is down this
      session (`ECONNRESET`, recorded above) instead of the on-disk bodies the task specified.
      A worker that sub-delegates and then waits is indistinguishable from a working one from
      outside, which is why 45 min elapsed before anyone looked. Recorded as a failed attempt
      rather than quietly re-dispatched: the delegation itself is the thing that needs
      correcting, since the card's own method note says the on-disk diff is what delegates
      safely. NEXT ATTEMPT must hand the worker the concrete body-file PATHS, not the tool name,
      and must not depend on agentlenspro being reachable.

      **THE PATHS, established 2026-08-13 13:3x so no future attempt rediscovers them.** The
      data is on disk; the live server is NOT required:
      - `~/.agentlens/store/bodies/` — **3221** captured request bodies, 62M. (`otel-bodies/` is
        EMPTY and is a red herring; `store.old-v0/bodies/` holds 342 older ones.)
      - `~/.agentlens/forensics.db` — 20M SQLite; tables `api_calls`, `call_content`,
        `call_injections`, `index_state`. Dump `.schema` before querying — do not guess columns.
      - `~/.agentlens/requests.log`, `requests.log.1`

      CAVEAT measured at the same time: **0 bodies are newer than 6h**, so retention may already
      have rotated the 03:29 window away. If it has, "the bodies are gone" is the correct
      finding and closes this box as UNMEASURABLE — it is not a licence to estimate.

      **ATTEMPT 2 dispatched** with those paths and the two constraints attempt 1 violated: do
      not sub-delegate, and do not touch the live agentlenspro surface.

      **ATTEMPT 2 RESULT (2026-08-13 14:0x) — the pinned incident is UNMEASURABLE; the MECHANISM
      is now known.** Report:
      `reports/ij94o8yd/20260813_forensics-unclassified-cache-break.md`.

      *The pinned 453,881 / `msg[363]` incident: CANNOT DETERMINE.* Verified first-hand in
      SQLite, not taken on the agent's word: `api_calls` holds **5730 rows with 0 non-null
      `break_cause` and 0 non-null `culprit_fingerprint`** — the classifier's fingerprint string
      is computed transiently by the agentlensPro server and **never written back**, so it exists
      nowhere on disk. **Zero rows** carry `cache_creation_tokens = 453881`. `otel-bodies/` is
      empty. This box therefore closes as unmeasurable exactly as the caveat above anticipated —
      no estimate substituted.

      *But a REAL, byte-diffed break was localised from the surviving CAS store, and it is the
      more useful result.* Session `c8a95d7e…`, two consecutive calls 51 s apart: cache_read
      553,919 → 21,409 while cache_creation went 709 → **535,371** (row verified present).
      Aligning both bodies' part sequences, **indices 0–815 are byte-identical** (~92% of the
      body); the first divergence is at `messages[406]`, where the visible text is IDENTICAL and
      the ONLY difference is that `"cache_control":{"type":"ephemeral","ttl":"1h"}` is present in
      the prior request and **absent** in the breaking one (762 → 714 bytes, exactly the
      annotation's length).

      **MECHANISM: sliding ephemeral-cache breakpoint relocation.** Claude Code tags the
      currently-last message with `cache_control`; appending a new message strips that tag from
      the old last message. The prompt cache requires an exact byte match of the whole prefix up
      to and including the marker, so relocating it invalidates the prefix that was cached under
      it. **This is not the janitor's doing and not a rules-edit** — which reframes the card
      again: the dominant avoidable cost is a HARNESS behaviour, not instruction-file hygiene.
      Candidate (a) — a re-rendering `<system-reminder>` — is NOT what this diff shows.
- [ ] A stated rule for WHERE rule/CLAUDE.md edits happen, with the exception for an urgent fix
      spelled out rather than implied — **RE-SCOPED 2026-08-16, and deliberately not built yet.**
      Both surviving boxes were written when this card believed instruction-file edits were the
      dominant avoidable cost. Two measurements later that is false: the cost is EPISODIC (~150k
      on rules-edit days, absent otherwise) and the larger break is a client-side mechanism the
      janitor cannot influence. Enforcement machinery for the smaller, self-limiting cost is not
      obviously worth its own maintenance burden — that is a scope judgement, and building it
      first and asking later is how a card outgrows its evidence.
- [x] **DECIDED 2026-08-20 — the rule is stated, and it is deliberately NOT enforced by
      machinery.** See **THE SCOPE CALL** below. The box was gated on a decision, not on
      effort; leaving it open indefinitely was itself the failure mode.
- [x] Whatever the rule is, it is enforced by something that runs — **ANSWERED: nothing new
      needs to run, because the free path already runs.** See below.

## THE SCOPE CALL — 2026-08-20

**The rule.** Edits to injected instruction files (`~/.claude/rules/*.md`, `CLAUDE.md`) belong
in the **script path** — `rules_installer`, which the janitor already uses and which runs
outside any model prefix, so the edit costs zero cache. A **hand edit mid-session is
explicitly allowed for an urgent fix**; it costs approximately one prefix rewrite (~150k
tokens on the days it happens), and that is an acceptable price for a rule that would
otherwise not ship. What is NOT acceptable is a batch of cosmetic rules edits made
mid-session for tidiness — that is the 2026-08-12 shape (`29121d8b`, `83a68674`) which paid a
full cache write to buy context headroom.

**No enforcement machinery, and the reason is the evidence, not laziness.** A hook that
blocked or warned on Edit against `~/.claude/rules/` would:

- fire on exactly the case the rule permits (the urgent fix), so it would be trained away;
- carry permanent maintenance and per-tool-call cost;
- to defend a cost that two measurements show is EPISODIC — ~150k on rules-edit days,
  entirely absent otherwise — and self-limiting, since the edit that causes it is also the
  edit that ends it.

Weighed against the janitor's own token-economy law (the 46k repo-map was deleted from
CLAUDE.md for costing far less than this per day), building a standing guard against an
occasional 150k is not worth its own footprint. The rule is written where it is read on
demand rather than injected into every turn — for the same reason.

### The third window could not be taken, AGAIN — stop trying

The 2026-08-13 12:45 note promised the third measurement was "free next time the server is
up". Retried 2026-08-20: the server answers `200` on `http://localhost:4316/mcp` and
`agentlenspro get_cache_break_causes --out …` then **hung past a 20-minute timeout and wrote
no file**. That is the second failed attempt by a different failure mode (first: `ECONNRESET`).

Recorded so the next session does not spend another 20 minutes on it: **the reachability of
the server does not predict that this tool call completes**, and if it is attempted again it
must be backgrounded, never run inline. More importantly, the decision above does not depend
on it — a third window could only sharpen an EPISODIC claim that two windows already agree
on, and no plausible result flips a "don't build machinery" call.

## Approval log

- 2026-08-20T18:40:00+0200 — COMPLETE by janitor-main-session. Both surviving boxes were
  gated on a scope judgement the card had deferred twice; the judgement is now made and
  recorded with its reasoning, rather than leaving the card open as a standing invitation to
  build a guard the evidence does not support.
