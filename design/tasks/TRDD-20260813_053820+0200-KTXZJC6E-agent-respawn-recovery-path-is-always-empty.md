---
trdd-id: KTXZJC6E
title: The background-agent respawn path is always empty so the documented fallback cannot run
column: complete
created: 2026-08-13T05:38:20+0200
updated: 2026-08-14T18:12:00+0200
implementation-commits: [e81ac464, 8996e199, 1f1ac985]
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

- [x] The hook stores a SEARCH ROOT (`<projects>/<slug>/<session_id>/subagents`) whenever it blanks
      a parent-session `transcript_path`; the blanking guard itself is unchanged — verified
      `scripts/hooks/on-subagent-start.py:66-85`, `agent_dir` computed INSIDE the guard only
- [x] Resolution finds the agent transcript at BOTH shapes — `<root>/agent-<id>.jsonl` and
      `<root>/workflows/wf_*/agent-<id>.jsonl` — the second being correction 1 — re-falsified
      2026-08-14 (see Part-B falsification note below; `resolve_transcript` stub broke both shapes)
- [x] Recovery returns the agent's ORIGINAL PROMPT TEXT (assert on content, not on non-emptiness —
      an empty-but-present file passes the weaker check) — `spawn_prompt`/`respawn_prompt` read the
      first user message verbatim; `test_respawn_prompt_cli_prints_the_original_prompt` asserts the
      literal string content, not presence
- [x] Falsified per guard: drop the subtree search and watch the workflow case go red; drop the
      search-root storage and watch both go red — original falsification table already in the
      2026-08-13 07:55 STATE block above (3/3 red); re-confirmed 2026-08-14 by independently
      stubbing `resolve_transcript` and observing the same two shapes go red
- [x] The workflow-subagent case still stores no parent transcript (the guard tested in its own
      right, since widening it is the tempting wrong fix) — `…stores_no_agent_dir_when_the_payload_gave_the_agents_own_path`
      passes in the current 64/64 green run

## ⏵ 2026-08-13 08:50 — PART B, scoped from the code rather than guessed

Traced the whole consumer chain before designing anything. **No script can be the consumer**, and
that constraint decides the shape.

### What production actually emits today

`dispatch.py::_pending_agent_directive_lines` → `pending_agents.directive_lines()` → one line per
in-flight agent:

```
resume background agent via SendMessage: <agent-id> — <description>
```

plus ONE shared note (deliberately shared, not per-line, for token economy) warning that a DIED agent
re-runs the request that killed it. **The respawn fallback is named nowhere in that output.** So the
main Claude is told to SendMessage-resume and told nothing about what to do when that fails — which
is precisely the state `add()`'s own docstring claims the transcript handle prevents.

### Why the consumer cannot be a script

Only the main Claude issues the SendMessage and sees it fail. Nothing on disk records "a resume was
attempted and did not work", and no detector can infer it — a silent agent is indistinguishable from
a working one. So an autonomous `if resume_failed: respawn()` has no signal to branch on, and writing
one would be inventing a trigger that does not exist.

**The consumer is therefore the RESUME TURN itself**, and part B is two small pieces:

1. **An agent-facing entry point** that turns an id into the prompt — the thing a human or the main
   Claude can actually run at the moment a resume fails (`respawn_prompt_for` is a library function
   today, reachable only from Python).
2. **A pointer to it in the shared note**, emitted ONLY when at least one listed entry has a
   resolvable handle — so a project with no recoverable agents pays zero extra tokens, and the line
   never promises a fallback that would come back empty.

### The trap to avoid, named now

Do NOT put the fallback text on every agent line. The shared note exists because per-line prose is
paid on every heartbeat resume, and this card's own §"Why this matters more than it looks" is about a
mechanism that is *documented and inert* — adding inert prose to every resume would be that failure
with a token bill attached.

## Acceptance — part B: a consumer exists (correction 3; NOT satisfied by part A)

- [x] An entry point exists that returns an agent's respawn prompt from its id alone (not a Python
      import), so the fallback is reachable at the moment a resume fails —
      `scripts/respawn_prompt_cli.py <agent-id>` (already shipped in `8996e199`/`1f1ac985`,
      verified present and re-tested this session)
- [x] The resume output names that fallback — in the SHARED note, never per-line —
      `directive_lines()` appends `respawn_prompt_cli.py` to the ONE shared note, not to each
      per-agent line (`scripts/lib/pending_agents.py:362-368`)
- [x] It is emitted ONLY when a handle actually resolves, so the pointer never promises a prompt
      that would come back empty — gated on `_transcript_hit_cheap`/`resolve_transcript` over the
      listed entries
- [x] Falsified: an entry whose transcript cannot be resolved produces NO pointer — verified
      2026-08-14: stubbed the emit-condition to `if False`, ran
      `test_directive_note_names_respawn_fallback_when_a_handle_resolves`, went RED (assertion on
      "respawn_prompt_cli.py" in note failed against the note with no pointer); restored, went
      GREEN; `test_directive_note_omits_respawn_fallback_when_no_handle_resolves` was already
      green throughout (the negative case)

## Original acceptance (superseded by A and B above)

- [x] A newly spawned background agent's manifest entry carries a NON-empty `transcript` that
      resolves to a real file — via lazy `resolve_transcript()`; the raw manifest field itself
      stays `""` by design (part A), the resolved value is non-empty when the transcript exists
- [x] `respawn_prompt()` on that entry returns the agent's ORIGINAL prompt (assert on prompt
      content, not merely on a non-empty string — an empty-but-present file would pass that) —
      `test_respawn_prompt_cli_prints_the_original_prompt` asserts `"DO THE ORIGINAL JOB" in
      res.stdout`, content not presence
- [x] Falsified: restore the blanking and watch the new test go red — verified 2026-08-14:
      stubbed `resolve_transcript()` to `return ""` unconditionally, ran
      `test_resolve_transcript_finds_direct_agent_tool_shape`,
      `test_resolve_transcript_finds_nested_workflow_shape`, and
      `test_respawn_prompt_cli_prints_the_original_prompt` — all 3 went RED (direct-shape and
      nested-workflow-shape resolution both broken, CLI printed "no recoverable transcript" and
      exited 1 instead of 0); restored via Edit tool, re-ran full file, 64/64 GREEN
- [x] The workflow-subagent case still stores nothing rather than the parent's transcript
      (the guard tested in its own right, since widening it is the tempting wrong fix) — covered
      by Part A's own falsification table (already ticked/shipped in `e81ac464`); re-confirmed
      this session by re-running the full suite (64/64 pass) with the guard intact

## Notes and lessons learned
