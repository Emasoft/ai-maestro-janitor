---
trdd-id: KXZJOZBQ
title: Janitor-typed text stranded by an earlier send blocks every later injection
column: human_review
status: tasked
created: 2026-10-18T11:11:22+0200
updated: 2026-10-18T12:08:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T11:11:22+0200
---

# Janitor-typed text stranded by an earlier send blocks every later injection

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-18
2026-10-18 12:09 WAITING FOR THE OWNER: options A/B/C below. This block supersedes the 12:08 line in the Approval log, whose option A overstated two things. Corrected: the stuck-field log line ('inject clear:') comes with 59c6a5ac and exists only once that is released (the running v3.8.11 does not log it); and after 8dae3e5e and 59c6a5ac a strand is far less likely to form and is reported when it does — not impossible: a near-one-row command read half-drawn, a remainder that is not our own suffix, iTerm (unmeasured), and everything the released version strands until a release can still leave text. Findings (review and measure 2026-10-18): a crumb-based clear at rule 1 would not have fixed 10-13 (crumb epoch ~13:41, TTL 7200 s, blocked /clear from ~16:40); it can delete an owner who retypes or pastes the janitor's goal and pauses; it amends the owner's verbatim rule 1 of 2026-08-02. Options: (A) keep rule 1 and rely on the stuck-field log after a release; (B) record the exact leftover when _clear_ours gives up and clear only a byte-identical field (after space normalization) with nobody typing — no TTL dependence, never matches an owner retyping a goal from its start, does not cover text stranded by the released version; (C) the crumb design with the owner-retype risk accepted. Recommendation: A after a release; B only if stuck-field reports appear.


Split from TRDD-S8BZI761 (review of its round-2 plan, 2026-10-18). S8BZI761's fix clears a wrapped field only inside the send that typed it. Text already stranded before a send (a crash, a give-up mid-clear, the released version) stays: on 2026-10-13 the next sends were /clear, which only waited on field not empty for hours. A fix must recognise text the janitor itself typed recently (the user_intent machine-typed crumb, TTL 2 h, looked up by ANY recent machine-typed command, not the current one) at the start of a send, and clear it with the same suffix-of-our-own-text rule, never touching user text. TO DO FIRST: read user_intent.note_machine_typed and its readers, and how inject_until_sent's rule 1 (field not empty) could consult them.

## Approval log

- 2026-10-18T11:11:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-18 12:08 OWNER DECISION NEEDED. Investigation: reports/board/20261018_120633+0200-KXZJOZBQ-investigate.md. A crumb-based clear at rule 1 was designed and rejected by review and measure: (1) it would NOT have fixed 10-13 — the crumb is rewritten only when typing, so after the 13:41 strand it kept that epoch and expired at ~15:41 (TTL 7200 s), an hour before the blocked /clear sends began ~16:40; (2) it can delete the owner's own text — an owner who retypes or pastes the janitor's goal and pauses matches the crumb exactly (no minimum length for exact matches); (3) it amends the owner's verbatim rule 1 of 2026-08-02 (inject only into an EMPTY field; never delete what the user typed), on every inject_until_sent path. Options for the owner: (A) keep rule 1 unchanged and rely on reporting the stuck state, already logged since 59c6a5ac ('inject clear:'), plus the strand no longer forming after 8dae3e5e and 59c6a5ac; (B) a narrower 'stranded record': when _clear_ours gives up, record the exact leftover text, pane and time; rule 1 clears only a field byte-identical (after space normalization) to that record and only with nobody typing — no TTL dependence, an owner retyping a goal from its start never matches a recorded tail, but text stranded by the released version is not covered; (C) the crumb design with the owner-retype risk accepted explicitly. Recommendation: A now, B only if stuck-field reports appear after a release.
- 2026-10-18T12:08:56+0200 — column → human_review. owner decision on rule 1 (options A/B/C on the card)
