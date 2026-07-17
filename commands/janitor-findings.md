---
description: Browse THIS project's findings ledger — the per-project mailbox where every janitor finding is indexed with a traceable ref (ticket/TRDD). List unread + recorded findings, show a finding's full body by ref, or ack the inbox.
argument-hint: "[list [N] | show <T-XXXXXXXX|TRDD-XXXXXXXX> | ack]"
---

# /janitor-findings [list [N] | show <ref> | ack]

The on-demand browser over `<project>/.janitor/state/findings-ledger.ndjsonl`
(TRDD-FENWWB4E, `design/ARCHITECTURE.md` §4 — ratified). Session start injects only a
capped index of UNREAD lines; this command is where deep reads happen, pulled never
pushed.

## Instructions

Run the backing CLI with the user's arguments (default verb: `list`):

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/findings_cli.py" $ARGUMENTS
```

Surface its stdout to the user verbatim. The verbs:

| verb | effect |
|---|---|
| `list [N]` | newest N recorded findings (default 20) + the unread count. Read-only. |
| `show <ref>` | resolve the finding's BODY: `T-…` → the ticket (open or closed); `TRDD-…` → the proposal/task TRDD file, verbatim. Read-only. |
| `ack` | advance the cursor — mark everything currently recorded as read (stops re-surfacing at session start). |

## Scope

OWN project only — this reads the current project's ledger, never another project's
(the per-project isolation invariant, `ARCHITECTURE.md` §3). Machine-wide views live
behind `/janitor-show-global-status`. `ack` writes only the cursor file; nothing else
is mutated.

## Error handling

- Empty ledger → the CLI says so; report that this project has no recorded findings.
- Unknown ref → the CLI reports it; suggest `list` to see valid refs.
