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

## R2 design (orchestrator, 2026-11-19)

Status: orchestrator design after round-2 review; no severity floor and the dateless key are defaults pending the owner's answer, reversible.

1. findings_ledger.entries(project_dir) -> list[dict]: public read-only wrapper over _read_raw; never touches the cursor or surfaced state.
2. Catalog rows in design/specs/issue-codes.toml, then regenerate with scripts/build_issue_codes.py (issue_codes_gen.py, docs/ISSUE-CODES.md) so tests/test_issue_codes_spec.py passes:
   - LEDGER-001 HARNESS kind (janitor own machinery; repair agent janitor-repair-agent);
   - LEDGER-002 PROJECT kind (user repo/board; proposal TRDD, approval command);
   - LEDGER-003 needs-human (only the owner can fix: ITERM-AUTOMATION-TCC, WORKER-STALLED): ticket lands in needs_human, never dispatched.
   New KIND_REGISTRY entries in scripts/lib/tickets.py as needed (e.g. ledger-finding-harness, ledger-finding-project, ledger-finding-human); follow existing entries exactly.
3. A code-owned table src->group (janitor/project/human), keyed on the full ledger `src` (detector name), never derived from ledger text. Real src values measured 2026-11-19. Janitor (LEDGER-001): memory-librarian, reports-purge, subagent-report, wikimem-syntax, daemon, hook-timeout-scan, janitor:autorecall, jev-compaction, orphaned-memory-maint. Project (LEDGER-002): dirty-tree, gh-reply-watch, github-issues-watch, memorize-nudge, project-map-drift, repo-state, report-to-trdd-drift, stale-stash, trdd-drift, trdd-reminder, trdd-cross-card-blindspot, trdd-state-reconciliation. Human (LEDGER-003): iterm-automation-alarm, background-worker-progress. Unknown src -> project (approval needed, safest).
4. Detector scripts/detectors/ledger-to-card.py, registered in dispatch.py _DETECTORS at 3600 s (own env knob), NOT in _ADVISORY_DETECTORS. Per fire:
   - group entries by (code, src), sev case-folded;
   - skip codes LEDGER-001/002/003/004, TICKETED-*, NEVER_SURFACE_CODES, sev INFO, and entries written by raise_issue (ref is T-<id8> of an existing ticket, or TRDD-<id8> of an existing proposal, for catalogued codes only);
   - dedupe key LEDGER:<code>:<src> (no date). Already filed = open ticket (non-ARCHIVED) or open proposal with that key;
   - closing floor: newest ARCHIVED ticket in tickets/closed/ (closing time = Ticket.updated_at) or refused/approved proposal with that key (closing time = frontmatter updated:); count only entries newer than its closing time;
   - repeating = >=3 counted entries, or 2 entries >=3600 s apart;
   - evidence = [code, src] only (stable, so a human refusal sticks); count, first/last ts and as many of the last 5 msgs as fit in the 200-character `found` slot (issue_catalog._FIELD_CAP) go into detail;
   - call issue_catalog.raise_issue(code, where=..., evidence=..., dedupe_key=...); print its Raised.line; on ok=False print the why line AND record it with findings_ledger.record() at sev HIGH, code LEDGER-004 (a registered non-kind catalog row), then continue;
   - caps: issue_catalog.MAX_RAISES_PER_FIRE (5) per fire; at most 3 new proposals per local day (state file under .janitor/state); sort by severity then count; one line reports what a cap dropped.
5. Tests (new file tests/test_ledger_to_card.py, real ledger/state files in tmp dirs, no mocks of the code under test): repeating code opens exactly one card; second run bumps seen, no duplicate; refused proposal stays refused across runs with new msgs; already-filed skipped; closed ticket does not reopen from old entries but reopens from newer ones; human group lands needs_human; caps hold and drop line printed; cursor file unchanged; own codes skipped.
