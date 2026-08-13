---
trdd-id: IJ94O8YD
title: Editing an injected instruction file mid-session costs a full cache re-write — 150k tokens, measured
column: todo
created: 2026-08-13T00:41:54+0200
updated: 2026-08-13T12:45:00+0200
current-owner: unassigned
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
- [ ] **NEW, and now the bigger prize:** localise the UNCLASSIFIED 453,881-token break
      (`msg[363] system`, 39.5% of classified breaks). Until its mechanism is known this card is
      optimising the smaller of two costs. Do NOT guess it — agentlenspro could not localise it
      from the prefix diff, so only the raw adjacent-body diff settles it.
- [ ] A stated rule for WHERE rule/CLAUDE.md edits happen, with the exception for an urgent fix
      spelled out rather than implied
- [ ] Whatever the rule is, it is enforced by something that runs — not only written down
      (this corpus's own lesson: a fix reaches the sites it is wired into, not the sites it
      claims)
