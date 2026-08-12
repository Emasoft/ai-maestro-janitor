---
trdd-id: IJ94O8YD
title: Editing an injected instruction file mid-session costs a full cache re-write — 150k tokens, measured
column: todo
created: 2026-08-13T00:41:54+0200
updated: 2026-08-13T00:41:54+0200
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

## The tension to resolve — do NOT assume the obvious fix

"Never edit rules mid-session" is unworkable as stated: the janitor edits its own rules as a
normal part of its job, and a rule fix that waits for a session boundary is a rule fix that does
not ship. The real question is WHERE the edit happens:

  - a **subagent** has its own prefix, so its edits cost the parent nothing — but the parent must
    not then read the edited file back, or it pays anyway;
  - a **session-start** window is free but arrives on someone else's schedule;
  - a **detector/script** edit is free of any model prefix — the best case, and the one the
    janitor already uses for `rules_installer`.

## Acceptance

- [ ] The cost is confirmed a second time (a rules edit in a live session, measured before/after
      with `get_cache_break_causes`) — one measurement is a finding, not a law
- [ ] A stated rule for WHERE rule/CLAUDE.md edits happen, with the exception for an urgent fix
      spelled out rather than implied
- [ ] Whatever the rule is, it is enforced by something that runs — not only written down
      (this corpus's own lesson: a fix reaches the sites it is wired into, not the sites it
      claims)
