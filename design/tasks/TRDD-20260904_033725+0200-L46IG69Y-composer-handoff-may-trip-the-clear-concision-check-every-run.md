---
trdd-id: L46IG69Y
title: the composer-authored handoff may trip clear_trigger's concision warning on every clear
column: todo
created: 2026-09-04T03:37:25+0200
updated: 2026-09-04T03:37:25+0200
current-owner: main-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
external-refs: [TRDD-ZQ02QG1L]
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: []
---

# the composer-authored handoff may trip the clear-path concision check

## Why this exists

TRDD-ZQ02QG1L converted `janitor-handoff-and-clear` step 2 from model-authored
prose to `compose_agent_handoff.py`. That removed the model cost, which was the
point, and traded away a shape contract nobody had noticed was load-bearing.

This card exists because ZQ02QG1L closed with that consequence recorded but
unfixed, and an effect of a change is the changing card's post-condition. It is
ZQ02QG1L's EHT.

## The interaction

The old step 2 produced a link-only index BY CONSTRUCTION — its instructions
said link-never-inline, exhaustive-by-reference, no duplicated TRDD `## STATE`
blocks, "a few hundred bytes to low KB". `compose_agent_handoff.py` produces an
`llm-ext` PROSE SUMMARY and imposes none of that.

`janitor-handoff-and-clear` is the FIRST path to put composer output in front of
a concision check. The already-converted `/janitor-write-handoff` feeds
`/compact`, which checks nothing; this skill's step 3 feeds `clear_trigger.py`,
which checks:

- `_HANDOFF_MAX_BYTES = 4096` — `scripts/clear_trigger.py:124`
- `_REFERENCE_RE = re.compile(r"\[\[|ATOM-[A-Z0-9]|TRDD-[A-Za-z0-9]|memgrep|#\d+")`
  — `:130`

Nothing in the composer emits those tokens by construction, and a prose summary
can exceed 4 KB.

## Why it is NOT urgent

Verified, not assumed: the comment at `clear_trigger.py:791` states the ratified
contract as **"ABSENCE IS FATAL; shape is WARN-only"** (the check itself is at
~`:809`, `handoff = _read_handoff()` / `if handoff is None:`). An absent handoff
REFUSES the clear — owner invariant 2026-08-28, after a session woke blank
mid-migration — while a bloated or reference-free one still clears, because
losing the session to enforce concision is the worse trade.

So the failure mode is stderr noise, not a lost context.

## Why it is still worth fixing

A warning that fires on every run carries no information and trains its reader
to ignore it. That is not a general principle imported from outside — it is the
argument `publish.py`'s `stage_install_smoke` makes about its own async-lag
note, in this repo, for this reason.

**The uncomfortable possibility, and why this needs measuring before a fix is
chosen:** an `llm-ext` summary of a session that discusses TRDD ids would likely
reproduce them, so `_REFERENCE_RE` may match INCIDENTALLY. That would make the
warning intermittent — which is worse than always, because an intermittent
warning looks like signal.

## What must be measured FIRST

One real `/janitor-handoff-and-clear` run (or `compose_agent_handoff.py` output
fed directly to `check_handoff_concise`), answering:

1. Does the composer's output match `_REFERENCE_RE`? Always, never, or sometimes?
2. Does it exceed 4096 bytes? Typically, or only for long sessions?

Choosing a remedy before that answer is known would repeat the `ruff
target-version` mistake from TRDD-CN62E66F — a remedy that does not remedy,
proposed confidently.

## Candidate remedies, to be chosen AFTER the measurement

1. Teach `compose_agent_handoff.py` a link-only mode and pass it from this skill
   — restores the original contract, but the composer then has two output
   shapes.
2. Retune `_HANDOFF_MAX_BYTES` / `_REFERENCE_RE` for composer-authored handoffs
   — but those constants are described as ratified, so this is a governance
   change, not a tweak.
3. Have the check recognise a composer-authored handoff and skip the shape
   warning for it — narrowest, and honest about the fact that two producers
   legitimately have two shapes.

## Acceptance criteria

- [ ] The two questions above are measured and the answers recorded here.
- [ ] A remedy is chosen with the measurement cited, or the interaction is
      explicitly accepted with a reason.
- [ ] If a remedy is applied, a test pins it so the warning cannot silently
      return to firing on every run.

## Notes and lessons learned

- The transferable lesson from the conversion that produced this: replacing an
  instruction with a script also replaces every constraint the instruction
  carried. The old step 2's shape rules were not commentary, they were the
  contract with a downstream consumer, and nothing in the diff made that visible
  — the consumer is in a different file, reached two steps later.
