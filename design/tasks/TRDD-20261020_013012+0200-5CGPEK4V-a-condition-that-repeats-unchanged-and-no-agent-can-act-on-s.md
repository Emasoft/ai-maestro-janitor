---
trdd-id: 5CGPEK4V
title: A condition that repeats unchanged and no agent can act on should escalate once and stay quiet
column: todo
status: tasked
created: 2026-10-20T01:30:12+0200
updated: 2026-10-20T01:30:12+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T01:30:12+0200
---

# A condition that repeats unchanged and no agent can act on should escalate once and stay quiet

THE OWNER'S ASK, verbatim, 2026-10-20: "you must find a way to avoid/prevent such things to happen. think a more intelligent solution." The subject of "such things" was a janitor alert that repeats on every heartbeat fire and that no agent can act on.

WHY THE RELEASE IS NOT THE ANSWER. The fix for the specific instance (the owner-only rotator condition re-raising itself every 5 minutes) is already written and is recorded on TRDD-PWL9GD4E, which is about the unreleased 599 commits. But shipping it is a one-shot unblock of an incident that has already happened. It changes nothing about the layer where the repetition occurs, so the NEXT owner-only condition, or the NEXT detector with the same shape, repeats the same way. This card is the prevention layer, and it is the part of the owner's ask that outlives the incident.

THE MECHANISM, stated plainly. Every heartbeat fire runs the detectors, collects their stdout lines, and hands them to a model turn. A line is printed on EVERY fire whenever its underlying condition holds, regardless of whether anything changed since the last fire, and regardless of whether the reader can act on it. So a STANDING condition — one that persists for days — produces a fresh actionable-looking line every fire. The two properties that make it noise rather than signal are: (a) the condition is unchanged since last time, and (b) no agent can resolve it, because it needs the owner (a credential, a commercial decision, a physical action).

THE DESIGN, in the terms the janitor already has. The findings ledger (scripts/lib/findings_ledger.py) already records every dropped advisory with a severity, and already has a pull model with a cursor and a surfaced-to-human marker. The rotator alert module (scripts/lib/rotator_alert.py) already splits URGENT from ADVISORY and already dedupes advisories by a signature digest against a per-project stamp. What neither does is count REPETITION of an un-actionable condition. The mechanism to add: for a condition that (1) has fired on N consecutive fires with an UNCHANGED signature, and (2) is classified owner-only, emit it ONCE as a fresh line, then thereafter emit at most one line carrying a COUNT and a pointer to the ledger entry ("still waiting on the owner: N fires since <time>"), and then stay silent until the signature changes or the condition clears. The first occurrence is the loud one; repetition is not urgency, it is the opposite.

WHY THE CLASSIFICATION MUST EXIST FIRST, or the mechanism cannot be built. "No agent can act on it" is not currently a property anything in the code records. The repo's rotator_alert module has _AGENT_VISIBLE_CONDITIONS = frozenset({"tick-stalled"}) and an advisory predicate (_is_advisory) that covers spare-stale and capture-refused:*; the general detector path has no equivalent, and the quiet filter treats every dropped advisory line alike (sev="LOW"). So the agent-actionable vs owner-only distinction is currently a property of a handful of rotator conditions, not a general capability. A general repetition-escalation needs that classification to be general, and a general classification is a bigger change than the escalation itself. The honest scoping: this card is the escalation MECHANISM, and it depends on a classification that must be landed first or together with it. The measurement below says how wide that is.

WHAT IS MEASURED, on this host, for the shape of the problem. Over 3,610 heartbeat turns in this project's token-meter.jsonl, 20 turns exceeded 2M weighted tokens and four exceeded 7M, the largest at 14,396,446 (2026-10-08 16:42, 66 assistant messages in one turn). The heavy tail is the ordinary shape of a long agent session, so the cost of a repeated drift line is small in tokens and LARGE in attention: a standing condition re-raised every 5 minutes trains the model to read the channel as noise, which is exactly what makes a genuinely urgent line get missed. The cost that matters is not per-line tokens; it is that repetition degrades the channel for everything else on it.

THE BOUNDARY THIS MUST NOT CROSS. Escalation is for conditions no agent can act on. A condition an agent CAN act on must keep printing every fire until it is acted on, because silence would hide a live problem. The existing urgent/advisory split (commit f795816c, TRDD-JWIGGMH0) already encodes most of this distinction for rotator conditions; this card generalises the REPETITION half of it, it does not replace it. It must also not suppress anything at HIGH or CRITICAL severity (findings_ledger.NEVER_SUPPRESSED_SEVERITIES already refuses to let .janitor.toml silence those) and it must not lose a finding: the ledger entry and its count must remain queryable, so a standing owner chore is still visible in /janitor-findings and to the owner, even when it is no longer re-raised at the agent.

ACCEPTANCE. (1) An owner-only condition that fires unchanged N times emits a fresh line on the first fire and a counted line thereafter, and then goes silent — asserted by a test that drives the dispatcher with the same condition over N fires and counts the emitted lines. (2) A condition that CHANGES (its signature differs) re-emits a fresh line, so a real change is never swallowed. (3) An agent-actionable condition still prints on every fire until it clears. (4) The count and the ledger entry are readable afterwards: nothing is deleted, only de-duplicated from the agent's context. (5) A HIGH/CRITICAL finding is never suppressed by this mechanism. (6) The classification of owner-only is stated for each condition the mechanism governs, and a condition with no classification is treated as agent-actionable (fail OPEN toward visibility, never toward silence).

NEXT ACTION: read scripts/lib/findings_ledger.py and scripts/lib/rotator_alert.py in full, and measure how many distinct conditions can reach a model turn and which of them are owner-only — that measurement sizes the classification work this card depends on. Write it as its own card if it is more than a small, bounded change, because the TRDD rule forbids "and also do X" inside one card.

## Approval log

- 2026-10-20T01:30:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
