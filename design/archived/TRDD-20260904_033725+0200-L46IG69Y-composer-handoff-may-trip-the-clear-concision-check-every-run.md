---
trdd-id: L46IG69Y
title: the composer-authored handoff may trip clear_trigger's concision warning on every clear
column: complete
created: 2026-09-04T03:37:25+0200
updated: 2026-09-05T00:34:59+0200
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

## Superseded — a first measurement over the wrong population

A first measurement was taken over the wrong population — all 29 handoffs on
disk, split by the composer's ship DATE rather than attributed to it, so the
"post" half included files the measuring session had hand-written itself — and
discarded. Its lesson is in the measurement box below; its ~90 lines of numbers
are cut FROM THIS CARD, where a reader met them before the correct ones.

## Acceptance criteria

**Closed `complete` 2026-09-05, USER decision.** The card briefly carried
`eht: [34GB6XUI]` — the ZQ02QG1L collapse — which walked it through three wrong
columns in an hour: `dev` and `testing` each assert active work nobody was doing,
and `human_review` asserts a review from a human who had never been asked. **The
gate was the defect, not the column.** Asked directly, the USER dropped it;
TRDD-34GB6XUI stays in `todo` as an unlinked chore.

The lesson: **a gate whose only claimant is an agent's judgment — not a
correctness requirement — should be ASKED about, not encoded.** `eht:` exists for
effects that genuinely must be handled, and this is no argument against it; a
readability cleanup is not one of those. The collapse box was inherited here from
an earlier session, and promoting it into a formal `eht:` is what turned a latent
preference into a blocker on a finished, tested fix. Distinguishing a
correctness-effect from preference-work is the call worth making — and when it is
preference, the person who owns the priorities answers it, not the agent.

- [x] The two questions above are measured and the answers recorded here.
      **TAKEN 2026-09-04, and the earlier "cannot close here" was wrong** — not
      because the invalid attempt's numbers were salvageable (they were not), but
      because the POPULATION was never unavailable. It is enumerable exactly:
      `.janitor/logs/agent-handoff-compose.log` carries one
      `wrote <name> (<n> chars)` line per composer run, so the composer names its
      own output. Five files, all still on disk, zero missing, no date heuristic
      and no shape guess. The invalid attempt failed on the one axis it had
      controlled for — provenance — while the composer had been recording
      provenance the whole time. **A producer's own log is the provenance oracle;
      generating a fresh sample was never the only way in.**
      Measured by calling the REAL `check_handoff_concise` (not a `wc -c` + grep
      proxy — the proxy is what the invalid attempt was faulted for):
      - **Q2, size: ALWAYS over.** 5/5 `too-large`; 23816 / 25823 / 35910 /
        38362 / 40535 bytes against the 4096 budget = **5.8-9.9x**. Not marginal,
        so the warning fired on EVERY run — never "only for long sessions".
      - **Q1, references: matched in all 5** (6-32 hits each — `TRDD-`, `memgrep`,
        `#\d+`), because a summary reproduces ids the session discussed.
        INCIDENTAL, not by construction: nothing stops a reference-free summary,
        and that residual possibility is why the check is LIFTED rather than
        tuned — kept, it would fire on exactly that summary, and an intermittent
        warning looks like signal.
      - **Third check, unasked and it decided the remedy:** `inlined-block`
        fired 0/5.
- [x] A remedy is chosen with the measurement cited, or the interaction is
      explicitly accepted with a reason.
      **CHOSEN: option 3, split TWO-of-three** — not option 3 as this card wrote
      it ("skip the shape warning", singular). The measurement splits the three
      checks apart, which the card could not have known before taking it:
      - `too-large` and `no-references` are LIFTED for composer output. Both
        restate the link-only DESIGN (concise; exhaustive by REFERENCE), and a
        prose summary is exhaustive by INCLUSION on purpose. Lifting only the
        byte check would leave `no-references` free to fire on the summary that
        names no ids — intermittent, which looks like signal and is worse than
        always-on.
      - `inlined-block` STAYS LIVE for both producers. Its rationale is link-only
        but its PREDICATE is "you pasted a big blob", which survives the shift to
        prose: llm-ext quoting a source file instead of summarizing it is the one
        shape where composer output is bloated beyond its own nature. It fired
        0/5, so keeping it costs no noise on any handoff this host has. A first
        draft lifted all three and a review caught it — "inapplicable to prose"
        is true of the two design restatements, false of the predicate.
      Option 2 (retune the constants) was never on the table once read closely:
      `_HANDOFF_MAX_BYTES`'s own comment scopes it to *"the link-only handoff …
      never the tens-of-KB a compaction summary runs"*, i.e. the ratified
      contract already names composer output as what it is NOT about. So this is
      a SCOPING of a ratified check, not a governance change — Tier 0.
      Option 1 (a link-only mode in the composer) is declined: it would give the
      composer two output shapes to satisfy a check that does not apply to the
      shape the composer produces. (The check DOES apply to the link-only shape —
      it is that shape's contract, which is the premise of this whole fix.)
      Implemented: `handoff_files.COMPOSED_MARKER`, stamped by
      `compose_agent_handoff.py`, honoured by `clear_trigger`. Marker lives in
      the shared module because both sides already import it; it goes in the
      PAYLOAD rather than the filename because every consumer groups by the
      filename's key and a new key would split the session's group.
      (The ZQ02QG1L collapse that used to be a box HERE is now **TRDD-34GB6XUI**,
      this card's `eht:`. The instinct that put it here was right — a prose note
      on ZQ02QG1L would be honoured only if someone read the top of a 404-line
      file at the right moment, and nothing evaluates a condition written as
      prose. But a box that finishing THIS card cannot tick is not this card's
      acceptance criterion: it would either hold the card open or be ignored, and
      both hide the real state. A TRDD in `todo` is the thing that gets seen.)
- [x] If a remedy is applied, a test pins it so the warning cannot silently
      return to firing on every run.
      `test_a_composer_handoff_is_exempt_from_size_and_references_but_not_the_fence`
      — ONE payload violating all three, asserted TWICE: unmarked yields exactly
      `{too-large, no-references, inlined-block}`, marked yields exactly
      `["inlined-block"]`. One payload, not two, because the split IS the claim —
      two payloads could not show that the marker is what moved, and asserting
      only the marked half would pass on a check that had stopped working for
      everyone. Plus
      `test_the_exemption_needs_the_marker_at_the_top_not_merely_present`: the
      marker EXEMPTS, so a model-authored handoff that merely quotes the string
      mid-prose (this repo's handoffs discuss the janitor constantly) must not
      exempt itself. The exact-list assertion deliberately pins order: a NEW
      reason appearing on a composed handoff should fail this test, because
      whether it falls inside the exemption is a human's call.

## Notes and lessons learned

- The transferable lesson from the conversion that produced this: replacing an
  instruction with a script also replaces every constraint the instruction
  carried. The old step 2's shape rules were not commentary, they were the
  contract with a downstream consumer, and nothing in the diff made that visible
  — the consumer is in a different file, reached two steps later.
