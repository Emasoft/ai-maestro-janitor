---
trdd-id: XCRTJ1C9
title: A document that describes an attack is flagged as one — mention vs use in agent-context-integrity
column: complete
created: 2026-08-14T18:11:42+0200
updated: 2026-08-14T20:42:00+0200
current-owner: janitor-session
task-type: security
project-id: ai-maestro-janitor
approval-tier: 0
severity: medium
npt: []
eht: []
external-refs: [janitor#254]
implementation-commits: [adcadee3]
---

# A document that describes an attack is flagged as one — mention vs use

## The defect

`scripts/agent_context_bench.py`, live run 2026-08-14, still reproduces the three
false positives from janitor#254 verbatim:

| what fired | on what |
|---|---|
| `prompt-injection-multilingual` | a security-POLICY document |
| `exfil-structural-probe` | a post-mortem NARRATING a past attack |
| `prompt-injection-multilingual` | a LABELLED test fixture |

All three documents *talk about* attacks. None *is* one. This is the classic
mention-vs-use problem, and the detector currently cannot tell the two apart.

## What already exists, and why it does not solve this (verified, not assumed)

`agent-context-integrity.py:183` has `_has_foreign_provenance` — but that is **git**
provenance (is the file tracked, is its history local), not **document** provenance.
Its own comment at `:227-234` is explicit that it is *"deliberately NARROWER"* and
that *"unknown provenance is the shape a real attack takes"*, so it fails toward a
human reading the finding.

That design is correct and must not be weakened. It simply does not address this
case: **all three false positives are tracked, local, verified-provenance files.**
They pass the git gate and then fire on content. So this is not a matter of tuning
the existing gate — the missing signal is a different axis entirely.

## The trap any fix must avoid

The obvious fix is a self-declared genre marker — frontmatter like
`content-genre: security-doc`, or a title pattern. **A self-declared marker is
attacker-writable.** An injected document can carry the marker too, and the
detector would then suppress the one thing it exists to catch. A marker that the
document asserts about itself is worth exactly nothing on its own.

## Options

**A — genre marker CORROBORATED by git provenance.** Trust a genre marker only when
the commit that INTRODUCED it has verified-local provenance. This reuses
`_has_foreign_provenance` for what it is genuinely good at, and closes the
attacker-writable hole: an injected file's marker arrives with the injection and
therefore has the wrong provenance.
*Con:* a legitimately vendored security doc from outside the repo never gets the
marker trusted, so it keeps firing.

**B — structural containment** (inside a fenced block / blockquote / labelled
fixture section).
*Con and a live warning:* fenced code blocks are ALREADY handled inconsistently in
this detector — measured 2026-08-14 (commit `9138e988`), fenced blocks are MASKED
in prose, so `dynamic-exec-in-body` is blind exactly where its own description says
the threat lives. Building suppression on fences would deepen an existing bug
rather than fix it. **Do not pick B without fixing that first.**

**C — DOWNGRADE, never suppress.** A corroborated described-attack becomes a
low-severity/INFO finding instead of disappearing.
*Pro:* the finding stays visible and auditable.
*Con:* alert volume.

**Recommendation: A + C.** Corroborate the marker with git provenance, and have it
DOWNGRADE rather than suppress.

**The reason C is not optional:** over-suppression is invisible by construction. A
suppressed true positive produces no output, so nothing distinguishes "the gate
worked" from "the gate silently ate a real attack" — the same reasoning that killed
prefix-derived and link-derived ancestry in TRDD-3QIQ2E6J, and the same shape as
TRDD-OO301H7D, where a discarded signal degraded a guard with no error anywhere.
A detector may reorder findings by confidence; it must not make one vanish.

## Acceptance criteria

- [x] **DECISION: A + C, as recommended** — corroborate the genre marker with git
      provenance (A) and DOWNGRADE rather than suppress (C). B was declined on its
      own stated ground: fenced blocks are still MASKED in prose (`9138e988`), so
      building containment on fences would deepen that bug. Shipped in `adcadee3`.
- [x] The three janitor#254 false positives no longer fire at full severity —
      verified by re-running `scripts/agent_context_bench.py`, not by reasoning.
      → re-run first-hand: FP at full severity 3/40 → **0/40**. The three residual
      LOW findings are exactly the policy doc, the incident post-mortem, and the
      labelled fixture.
- [x] A test proving a marker with UNVERIFIED provenance is NOT trusted (the
      attacker-writable case). This is the load-bearing test; without it the fix is
      a suppression mechanism handed to the adversary.
      → `test_a_marker_with_unverified_provenance_is_not_trusted`, plus
      `test_a_marker_with_foreign_provenance_is_not_trusted`. Corroborated by the
      bench: 4 attack samples carry genre-marker text and still fire at FULL
      severity, because `provenance_verified` is False for them — the marker alone
      never earns the downgrade.
- [x] No finding is silently suppressed — every downgraded finding is still emitted
      and countable.
      → benign FP rate is **unchanged at 8% (3/40)** while full-severity FPs went to
      zero: the findings are still emitted, only re-ranked. Every suppression
      decision is additionally logged with its rule id and reason.
- [x] True positives still fire: the bench's genuine attack samples are re-run and
      still detected at full severity, proving the change did not neuter the rules.
      → **`recall (intended) 57%` == `recall (full severity) 57%`.** Their equality
      is the safety property: any future divergence means the gate has begun eating
      real findings. Re-check this pair, not the headline recall, when tuning.
- [x] `uv run pytest`, `uv run ruff check scripts tests`,
      `uv run mypy scripts/ --ignore-missing-imports` clean.
      → 201 passed; ruff clean; mypy clean over 484 files.

## Notes

Filed from the janitor#254 triage 2026-08-14. The triage's judgement that this
"needs a real design decision, not a bounded patch" is correct and is why this is a
card rather than a fix: the naive patch (trust a self-declared marker) hands the
adversary the suppression switch.
