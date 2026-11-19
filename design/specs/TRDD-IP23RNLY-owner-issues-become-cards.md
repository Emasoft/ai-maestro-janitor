# Owner order: every issue becomes a ticket or a TRDD (TRDD-IP23RNLY, PRRD G34.1)

## Owner words (verbatim)

Owner message 2026-11-19:

"issues must be solved not just reported. every issue must become either a janitor ticket or a TRDD. the janitor must ensure that, enforce that, nudge that!"

Owner message 2026-11-19, just before it:

"why the hell all agents are forgetting their goal!!!! fix this immediately!! its destroying all continuity of work!"

## Already decided in code (not an open question)

scripts/lib/tickets.py (docstring, TRDD-CGYMUKO6): HARNESS-domain kinds (the janitor own machinery) open AND auto-dispatch a ticket. PROJECT-domain kinds (the user code) may only PROPOSE a TRDD under design/proposals/ through scripts/lib/ticket_proposal.py propose(); running the printed command is the approval. The domain comes from KIND_REGISTRY, never from free text.

## Requirements

R1. Every issue an agent or the janitor finds (a finding, a drift line, a failure an agent reports to the user) is recorded in the same turn it is found. An issue in janitor machinery becomes a HARNESS ticket (T-XXXXXXXX). An issue in project code becomes a proposal TRDD under design/proposals/, or a task TRDD when an agent files it directly.

R2 (PROPOSAL, awaiting the owner answer and a design review; not a decided requirement). The janitor enforces R1. A heartbeat detector reads the findings ledger (scripts/lib/findings_ledger.py; the line field ref) and finds entries whose ref names no existing ticket or TRDD and that recur. For each it opens a ticket (HARNESS kinds) or prints the exact command that proposes the TRDD (PROJECT kinds), and it keeps nudging until each entry is linked.

R3 (PROPOSAL, awaiting the owner answer and a design review; not a decided requirement). The janitor nudges the agent. When a turn reply reports a problem (a bug, failure, error or gap) and the turn created or cited no ticket or TRDD id, the next heartbeat (or a Stop hook; the design decides which) tells the agent to file one. False-positive risk: spotting "this reply reports a problem" from free text is a classifier. It will fire on replies that quote a known issue, describe a fix just made, explain an error the user asked about, or discuss a bug in general. A false positive nags the agent on a turn that needs no card, and repeated nags train the agent to ignore the nudge. The design must name its precision target, cite-an-id exemption (R4) and a per-session nudge cap before it ships.

R4. A report or a nudge that only restates a known issue cites its id (T-XXXXXXXX or TRDD-<id8>) instead of describing it afresh.

## Precedents to reuse, not duplicate

- scripts/detectors/report-to-trdd-drift.py: decision reports with no TRDD.
- scripts/lib/tickets.py: ticket store, KIND_REGISTRY, HARNESS and PROJECT domains.
- scripts/ticket_cli.py: ticket command line.
- scripts/lib/ticket_proposal.py: propose() writes a TRDD proposal and prints the approval command.
- scripts/lib/findings_ledger.py: the ledger whose ref field R2 reads.

## Open questions for the owner

1. Severity floor: does every LOW advisory need a card, or are advisories auto-ticketed in batches (one ticket per detector per day, listing the entries)?
