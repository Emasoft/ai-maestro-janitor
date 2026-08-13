---
trdd-id: KTXZJC6E
title: The background-agent respawn path is always empty so the documented fallback cannot run
column: todo
created: 2026-08-13T05:38:20+0200
updated: 2026-08-13T07:55:00+0200
implementation-commits: [e81ac464]
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-82OP4EN9]
---

# `pending-agents.json` never stores a transcript, so `respawn_prompt` can never run

`pending_agents.add`'s docstring states the contract plainly:

> *"`transcript` is the RECOVERY path. Resuming an agent is always preferred … but when a
> resume fails, the only way to respawn the SAME job is to reissue its original prompt, and
> SubagentStart's payload does not carry one. The agent's first user message does, so the
> transcript path is what makes the fallback possible at all."*

**Measured 2026-08-13: the field is empty for every entry.** Both agents live in the manifest
at the time of writing carried `"transcript": ""` — including one spawned five minutes
earlier. `spawn_prompt()` / `respawn_prompt()` read that path, so the fallback the docstring
describes cannot execute for any main-session-spawned background agent.

## Cause — a correct guard with a missing second half

`scripts/hooks/on-subagent-start.py:66-67`:

```python
if session_id and transcript and Path(transcript).stem == session_id:
    transcript = ""
```

The guard itself is **right**: a workflow-spawned subagent receives the PARENT SESSION's
`transcript_path` in the payload, and storing that would make recovery reissue the wrong
conversation. What is missing is the other half — having rejected the wrong path, the hook
never derives the RIGHT one, so it stores nothing at all.

## The right path exists and is derivable from data the hook already holds

Verified on disk this session — both agents have their own transcript, at a path built from
exactly the two values the hook has in hand (`session_id`, `agent_id`):

```
~/.claude/projects/<project-slug>/<session_id>/subagents/agent-<agent_id>.jsonl
```

| agent | lines | size |
|---|---|---|
| `af07c17ce31f7976d` (live) | 106 | 710 973 |
| `aa8c1135f87f68a8d` (stopped) | 108 | 252 570 |

And the recovery genuinely works once the path is known: reading the stopped agent's first
user message recovered its original prompt verbatim (an `agentlenspro` cache-break forensic
task) — which is precisely what `respawn_prompt` is for, done by hand because the field was
empty.

## Why this matters more than it looks

This is the recurring shape on this board: **a mechanism that is wired, reachable, documented,
and inert.** Nothing errors, no test fails, and the manifest looks healthy — the field is
simply always `""`, so the failure only appears at the moment recovery is needed, which is the
moment it cannot be diagnosed. A resume that silently cannot fall back is worse than none,
because the caller believes a fallback exists.

## What

1. In `on-subagent-start.py`, after rejecting a parent-session `transcript_path`, DERIVE the
   agent's own transcript path from `session_id` + `agent_id` and store that. Store it only
   when the file is resolvable, never a speculative path — an unreadable path stored as fact
   is the same bug re-inverted.
2. Keep the existing guard intact — do not widen it to accept the parent transcript.

## ⚠ CORRECTIONS 2026-08-13 07:30 — three things this card got wrong, found by checking it

Written from observation, then verified before acting. The thesis survives; the prescription in
§What does not.

**1. The derived path in §"The right path exists" is INCOMPLETE.** Workflow-spawned agents do not
sit at `<session_id>/subagents/agent-<id>.jsonl` — they nest one level deeper:

```
<projects>/<slug>/<session_id>/subagents/workflows/wf_<runid>/agent-<agent_id>.jsonl
```

Measured on disk today. A fix built from the path this card stated would resolve direct Agent-tool
spawns and silently miss every workflow agent — and workflow agents are the majority case, because
they are the ones whose payload carries the parent transcript and therefore the ones the guard
blanks. Resolution must SEARCH the session's `subagents/` subtree, not join a fixed path.

**2. "Store it only when the file is resolvable" is UNSATISFIABLE at SubagentStart.** The hook fires
at spawn; the agent's transcript does not exist yet. Obeying that instruction literally stores
nothing — the same bug, reached by a different route. The resolution must therefore be LAZY: store
the SEARCH ROOT (derivable at spawn from data the hook holds, and a search root is not a claim that
a file exists), and resolve the file at READ time, when recovery actually runs and the transcript is
guaranteed to exist.

**3. The bigger finding — NOTHING CALLS `respawn_prompt`.** Grepped the whole tree: the only callers
of `spawn_prompt` / `respawn_prompt` are their own unit tests. So populating the field fixes a
prerequisite for a consumer that does not exist, and this card as written would have shipped a
correctly-populated field nobody reads.

That is this card's own thesis — *"wired, reachable, documented, and inert"* — one layer deeper than
it recorded, and it is why the acceptance list below is split. Populating the field is still correct
and still the prerequisite; it is simply not sufficient, and saying otherwise is how a mechanism
gets declared fixed while remaining inert.

## ⏵ 2026-08-13 07:55 — PART A SHIPPED (`e81ac464`). Part B is what remains.

`agentDir` is recorded by the hook when — and only when — the blanking guard fires;
`pending_agents.resolve_transcript` does the deferred lookup at resume time, preferring a stored
`transcript` that still resolves and otherwise searching `<agentDir>` for `agent-<id>.jsonl`
(direct hit first, then `rglob` for the `workflows/wf_*/` nesting). `respawn_prompt_for(entry)` is
the form callers should use.

### Review caught a real defect in the delivered work, and it was correction 2 in mirror image

The implementation computed `agentDir` OUTSIDE the blanking guard, so it was also stored for the
branch where the payload already carries the AGENT's own transcript. There `Path(transcript).parent`
is `<slug>/<session_id>/subagents[/workflows/wf_…]`, so the join produced
`…/wf_c1827891-050/<session_id>/subagents` — **verified against a real on-disk path: it cannot
exist.** Harmless in the happy path (a resolvable `transcript` is preferred), and precisely the sin
§CORRECTIONS names: *an unresolvable path recorded as fact.* Moved inside the guard, plus a mirror
test asserting that branch stores `agentDir == ""`. The guard now carries a comment saying why the
derivation may never leave it.

### Falsified — three breaks, each re-run first-hand rather than accepted from the report

| break | test that must go red | result |
|---|---|---|
| `agentDir` computed outside the guard | `…stores_no_agent_dir_when_the_payload_gave_the_agents_own_path` | ✗ red |
| `rglob` branch removed | `…finds_nested_workflow_shape` | ✗ red |
| hook stops passing `agent_dir` | `…stores_agent_dir_alongside_blanked_transcript` | ✗ red |

Restored after each; 59 tests in the file pass, ruff + mypy clean.

### Provenance

`reports/ktxzjc6e/20260813_072505+0200-respawn-handle.md` (gitignored, so annotated here rather
than trusted later). Its claims — implementation complete, both falsifications observed, three
gates green — were each TRUE of what it ran, and it still delivered the out-of-guard `agentDir`
defect above: its two falsifications tested the two guards it had been told to test, and neither
could see a third guard that did not yet exist. The lesson is not "the agent was careless" but the
one already on this board: **a falsification proves the guards you wrote, never the guard you
failed to write.**

### What part A does NOT do — the honest limit

The handle is populated and resolvable. **Nothing reads it.** Correction 3 still stands: grep finds
no caller of `respawn_prompt` outside its own unit tests, so recovery remains a manual act (as done
by hand this session). Part B is unstarted, and this card must not be closed until it exists —
otherwise the mechanism is exactly what this card was filed about, one layer deeper.

## Acceptance — part A: the recovery handle is populated and resolvable

- [ ] The hook stores a SEARCH ROOT (`<projects>/<slug>/<session_id>/subagents`) whenever it blanks
      a parent-session `transcript_path`; the blanking guard itself is unchanged
- [ ] Resolution finds the agent transcript at BOTH shapes — `<root>/agent-<id>.jsonl` and
      `<root>/workflows/wf_*/agent-<id>.jsonl` — the second being correction 1
- [ ] Recovery returns the agent's ORIGINAL PROMPT TEXT (assert on content, not on non-emptiness —
      an empty-but-present file passes the weaker check)
- [ ] Falsified per guard: drop the subtree search and watch the workflow case go red; drop the
      search-root storage and watch both go red
- [ ] The workflow-subagent case still stores no parent transcript (the guard tested in its own
      right, since widening it is the tempting wrong fix)

## Acceptance — part B: a consumer exists (correction 3; NOT satisfied by part A)

- [ ] Some production path actually calls the respawn fallback when a resume fails — until then the
      handle is populated and unread, and this card must not be called complete

## Original acceptance (superseded by A and B above)

- [ ] A newly spawned background agent's manifest entry carries a NON-empty `transcript` that
      resolves to a real file
- [ ] `respawn_prompt()` on that entry returns the agent's ORIGINAL prompt (assert on prompt
      content, not merely on a non-empty string — an empty-but-present file would pass that)
- [ ] Falsified: restore the blanking and watch the new test go red
- [ ] The workflow-subagent case still stores nothing rather than the parent's transcript
      (the guard tested in its own right, since widening it is the tempting wrong fix)

## Notes and lessons learned
