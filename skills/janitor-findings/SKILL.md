---
name: janitor-findings
description: Browse THIS project's janitor findings ledger — the per-project mailbox where every janitor finding (drift, security, supply-chain) is indexed with a traceable ref (ticket/TRDD). Use when the user asks what the janitor found / to see janitor findings / to read a finding by its T- or TRDD- ref / to ack the inbox, or when you need the full body behind a finding ref the session-start injection only summarized. Verbs — list [N], show <ref>, ack.
---

# Janitor findings

## Overview

The on-demand browser over `<project>/.janitor/state/findings-ledger.ndjsonl` (TRDD-FENWWB4E,
`design/ARCHITECTURE.md` §4 — ratified). SessionStart injects only a capped index of UNREAD lines;
this skill is where the deep reads happen — findings are pulled, never pushed.

## When to use

- The user asks "what did the janitor find?", "show me the findings", "read finding T-…/TRDD-…", or
  "mark the findings read".
- A session-start finding index mentioned a ref and you need its full body.
- You want to check this project's recorded janitor findings before acting on a related area.

## Instructions

Run the backing CLI with the user's arguments (default verb `list` when none were given). The
arguments arrive via this skill's invocation — use the `ARGUMENTS` line if present, else `list`:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/findings_cli.py" <arguments>
```

Surface its stdout to the user verbatim. The verbs:

| verb | effect |
|---|---|
| `list [N]` | newest N recorded findings (default 20) + the unread count. Read-only. |
| `show <ref>` | resolve the finding's BODY: `T-…` → the ticket (open or closed); `TRDD-…` → the proposal/task TRDD file, verbatim. Read-only. |
| `ack` | advance the cursor — mark everything currently recorded as read (stops re-surfacing at session start). |

**Every line ends with the AGE OF THE MEASUREMENT** (`— 4m ago`, `— 3d ago`), because a finding is
recorded once and may be surfaced much later: without it, an old alarm reads as a live one. Check
that age before acting — a "CPU 390%" line was once surfaced here while the named process sat at
5.3%. `age unknown` means the entry carries no usable timestamp (a hand-written or pre-upgrade
line), never "just now": an absent measurement is deliberately not rendered as a reassuring zero.

## Scope

OWN project only — this reads the current project's ledger, never another project's (the per-project
isolation invariant, `ARCHITECTURE.md` §3). Machine-wide views live behind
`/janitor-show-global-status`. `ack` writes only the cursor file; nothing else is mutated.

## Error handling

- Empty ledger → the CLI says so; report that this project has no recorded findings.
- Unknown ref → the CLI reports it; suggest `list` to see valid refs.
