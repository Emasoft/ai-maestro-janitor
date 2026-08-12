---
trdd-id: EBQVHTP4
title: Five of the seven memory chore skills never got the claim step — they still tell the agent to pick its own scope
column: todo
created: 2026-08-12T23:44:29+0200
updated: 2026-08-12T23:44:29+0200
current-owner: unassigned
task-type: bugfix
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-WP7TCRME]
---

# The claim step landed in the rule and in 2 skills, not 7

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**VERIFIED first-hand 2026-08-12, not taken on report.** `grep -c memory_dispatch_claim.py`
across `skills/janitor-memory-*/SKILL.md`:

| carries the claim step | does NOT |
|---|---|
| `split`, `retro-lesson` | `consolidate`, `conflict`, `repair`, `atomize`, `harvest` |

And the heartbeat rule (`rules/janitor-heartbeat-protocol.md`, the memory-marker row) tells
every dispatched agent to run the claim step because **"the chore's own skill carries the exact
command"** — which for five of the seven chores is not true.

**What those five say instead.** Read in `janitor-memory-consolidate/SKILL.md:112`:

```bash
MEMDIR="$LOCAL_MEM"   # or $USER_MEM — the ONE scope for this pass
uv run --script --quiet "…/memory_candidates_cli.py" --intervention consolidate --scope <LOCAL|PROJECT|USER> …
```

The agent PICKS. That is exactly the failure the claim step was built to end:

  - **#150** — a dispatched `conflict` pass could not read its assignment, re-derived what was
    due, ran USER, and left the stamped LOCAL scope marked run-without-running for a full
    cadence. Measured: 378k tokens, zero mutations.
  - **janitor#242** — two dispatches pointing at the same shared slot; a `consolidate`
    overwrote an in-flight `repair`'s authority 367 s later on the same root.

The fix for both shipped: `scripts/memory_dispatch_claim.py` plus the rule rewrite (`7e0b4115`).
It reached the rule and two skills. The other five kept the old self-selection text, so the
janitor#242 race and the #150 wrong-scope run are **still reachable through five of the seven
markers the heartbeat emits.**

This is the session's recurring defect class again, and the sixth instance of it: code that
exists, is tested, is documented, and is not reachable from where it is claimed to run. The
audit question is never "does the fix exist" — it is "is it reachable from every caller".

## Why this is not a five-line patch

Every one of the five is at or near the 5000-Claude-token CPV cap, measured 2026-08-12 right
after the trim in `ec28365d`:

| skill | tokens | headroom |
|---|---|---|
| consolidate | 4969 | **31** |
| conflict | 4930 | **70** |
| harvest | 4899 | **101** |
| repair | 4797 | 203 |
| atomize | 4491 | 509 |

The claim block in `janitor-memory-split/SKILL.md` is ~200 tokens. So three of the five cannot
receive it without simultaneously moving an equivalent amount of prose into that skill's
`references/` dir. That is the work, and it is why this is a card rather than an inline fix:
done carelessly it either breaks the publish gate or drops a prohibition on the way out — which
is precisely what happened during the trim that surfaced this (the split skill lost its
"do NOT read the legacy `memory-maint-pending.json` slot" line and had to be restored).

## Acceptance

- [ ] All seven chore skills carry the claim step, verbatim-patterned on `split`'s, including
      the STOP-and-report branch for exit 2 / unreadable / wrong-chore, and the explicit ban on
      the legacy `memory-maint-pending.json` slot
- [ ] No skill self-selects a scope any more — `grep -n 'or \$USER_MEM' skills/janitor-memory-*/SKILL.md`
      returns nothing that decides an assignment (an illustrative example is fine, a decision is not)
- [ ] Every one of the seven is still under the 5000-token cap, by MOVING prose out, never by
      dropping a step or a prohibition
- [ ] A test asserts the invariant for all seven at once, so skill #8 cannot be added without it
      — the loss this card documents was found by hand, and the next one will not be

## Approval log

- 2026-08-12T23:44:29+0200 — FILED at `todo` by janitor-main-session (tier 0, own scope).
  Found while VERIFYING a lean-worker's skill trim rather than trusting its report; the trim
  itself is unrelated and already landed (`ec28365d`).
