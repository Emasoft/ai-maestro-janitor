---
trdd-id: HXD3VRM0
title: runaway-file-growth reports forever and escalates never
column: backburner
blocked-by: []
created: 2026-08-29T15:51:54+0200
updated: 2026-08-29T15:51:54+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 5
severity: MEDIUM
effort: S
min-approval-requirement: none
task-type: feature
labels: [detector, escalation, disk]
release-via: publish
test-requirements: [unit]
parent-trdd: TRDD-XM3FPJC0
---

# TRDD-HXD3VRM0 — `runaway-file-growth` reports forever and escalates never

## The evidence, and why it is not a hypothetical

`/tmp/claude/statusline-debug.log` was caught by `runaway-file-growth` **twice, weeks apart**:

- **231 MB** — recorded in the detector's own module docstring as its motivating example,
  "appended several times per second since 2026-08-04".
- **100.5 MB** — the finding that eventually reached a human on 2026-08-29.

The file was truncated or rotated between the two, so these are two independent firings on the
same path. Between them the detector kept reporting and the file kept growing, at a measured
**~7.17 lines/sec ≈ 32 MB/day** (`llm-externalizer-ea`'s measurement; owner-confirmed as a bug).

**What finally stopped it was a human reading a finding and telling another project's agent.**
The detector's contribution was real — it is the only reason anyone knew — but between the
231 MB firing and the fix, the loop was: detect → report → nobody acts → detect again.

Resolved for THIS file on 2026-08-29: the owning plugin (`llm-externalizer`) gated the writes
behind `CLAUDE_STATUSLINE_DEBUG` and updated both its shipped and installed copies. Verified
here first-hand — **0 bytes growth over 8 s**, file down to 741 KB. That closes the instance and
leaves the class open, which is what this card is for.

## The gap

`runaway-file-growth` is REPORT-ONLY by design, and the design is right as far as it goes: the
janitor SURFACES, an agent FIXES, and RULE 0 forbids deleting a file the janitor did not create.
Nothing here proposes auto-deleting or auto-truncating anything.

The gap is that a finding which is **still true after N firings** carries no more weight than a
finding on its first. There is no escalation, so an unbounded-growth condition — one of the few
whose cost compounds — is reported at the same LOW advisory level forever, and lands in the
findings ledger alongside things that genuinely can wait.

Contrast with the quiet-filter work of the same day (`_OTHER_ACTOR_DETECTORS`): there the fix was
to stop repeating a line the reader could not act on. This is the inverse case — a line the
reader CAN act on, repeating unheard. Both are attention-routing defects; they need opposite
treatment, and conflating them would silence exactly the wrong one.

## Scope (deliberately small)

1. **Track recurrence per path.** The detector already dedups on content; it needs to remember
   that a path has fired before and how long the condition has persisted.
2. **Escalate on persistence, not on size alone.** A 200 MB file that appeared once is a
   different problem from a 20 MB file that has grown every day for a week. The second is the
   one that compounds; only the second warrants promotion past quiet mode.
3. **Include the RATE in the line.** "100.5 MB" is a snapshot; "100.5 MB, +32 MB/day, first seen
   25 days ago" is a decision. Two stats of the same file over one interval is enough to compute
   it — the peer did exactly that by hand.
4. **Name the WRITER when it is cheap to find.** `lsof` or a plugin-cache grep for the literal
   path resolved this case in one command. A finding that names the owning plugin is actionable
   by whoever reads it; one that names only a path is a research task.

## What NOT to do

- **Do not auto-delete, auto-truncate or auto-rotate.** RULE 0, and worse: the file may be the
  only evidence of the bug producing it. This card is about ESCALATION, not remediation.
- **Do not fold this into the quiet filter's advisory list.** That list exists to suppress lines
  whose owner is a different actor. This detector's owner IS the reader.

## Acceptance

- [ ] A path that fires on consecutive passes is tracked, with first-seen and growth rate.
- [ ] The emitted line carries size, rate, and age — not size alone.
- [ ] Persistent growth escalates past LOW advisory; a first sighting does not.
- [ ] The writer is named when resolvable by a cheap local lookup.
- [ ] Regression test: a fixture growing across two passes escalates; a static large file does not.

## Notes and lessons learned

- 2026-08-29 — **A detector that only ever reports has a silent failure mode: being right,
  repeatedly, to nobody.** This one did its job correctly at 231 MB and again at 100.5 MB, and
  the file still grew for weeks. Correctness of the FINDING is not the same as effectiveness of
  the DETECTOR, and only the second is worth measuring. **Ask of any report-only check: what
  happens if it fires and nobody acts? If the answer is "it fires again", the condition it
  watches had better not be one that compounds.**
- 2026-08-29 — **Cross-project, the detector's value was realized only through a human.** The
  peer session could not have found this without the janitor's finding, and the janitor could not
  have fixed it without the peer (it is their file, their plugin — see
  `how-to-fix-issues-of-other-projects.md`). That hand-off worked here because a human was in the
  loop to carry it. Naming the owning plugin in the finding is what would let it work without one.
