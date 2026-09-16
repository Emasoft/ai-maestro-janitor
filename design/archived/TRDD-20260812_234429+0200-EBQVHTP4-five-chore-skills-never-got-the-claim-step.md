---
trdd-id: EBQVHTP4
title: Five of the seven memory chore skills never got the claim step — they still tell the agent to pick its own scope
column: complete
created: 2026-08-12T23:44:29+0200
updated: 2026-08-12T23:57:44+0200
current-owner: janitor-main-session
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

## Acceptance — ALL MET, landed `9b885599`

- [x] All seven chore skills carry the claim step, verbatim-patterned on `split`'s, including
      the STOP-and-report branch for exit 2 / unreadable / wrong-chore, and the explicit ban on
      the legacy `memory-maint-pending.json` slot
- [x] No skill self-selects a scope any more — pinned by
      `test_skill_does_not_hand_the_agent_a_scope_to_pick`, which greps for the INVITATION
      (`or $USER_MEM`, `--scope <LOCAL|PROJECT|USER>`), not just for the script's absence: a
      claim step is worthless while a menu still sits next to it
- [x] Every one of the seven is still under the 5000-token cap, by MOVING prose out (measured
      with the same o200k_base×1.3 the gate uses: consolidate 4908, conflict 4818, repair 4864,
      atomize 4541, harvest 4723). Verified no step, command or prohibition left: the
      `is_due`/TRDD-VJ8L465M double-gate ban, `is_legal_merge`'s refusal catalog and harvest's
      DORMANT note all still resolve inside their skill's tree
- [x] A test asserts the invariant for all seven at once — `tests/test_memory_chore_claim_step.py`

**The guard test needed hardening before it was worth anything, and that is the lesson here.**
As delivered it asserted only that the slot is NAMED; a skill still telling the agent to READ
it would have passed. Both replacement assertions then FAILED to catch their own defect on the
first falsification attempt — the prohibition window was an open-ended slice to EOF (so any
stray "never" later in the file satisfied it), and the scope-menu probe was aimed at a line
spelling these skills do not use. Both fail correctly now. A test that cannot fail is not
evidence; the only way to know which kind you wrote is to attack it.

## Approval log

- 2026-08-12T23:44:29+0200 — FILED at `todo` by janitor-main-session (tier 0, own scope).
  Found while VERIFYING a lean-worker's skill trim rather than trusting its report; the trim
  itself is unrelated and already landed (`ec28365d`).
- 2026-08-12T23:57:44+0200 — COMPLETED by janitor-main-session. All five skills carry the claim step; the
  seven-skill guard test landed with both new assertions falsified. Shipped in `9b885599`.
