---
trdd-id: TUVQWLJF
title: A hand-typed future-dated updated field pins a card to the top of the board and nothing notices
column: dev
created: 2026-08-16T06:01:26+0200
updated: 2026-08-16T06:50:39+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: []
---

# A hand-typed future-dated `updated:` pins a card to the top of the board and nothing notices

## The defect, measured

Three cards in `design/tasks/` carried `updated:` values **in the future** relative to the
commit that wrote them:

| card | frontmatter said | commit that wrote it | skew |
|---|---|---|---|
| ZM5LZ24Y | `2026-08-16T06:50:00+0200` | `836a3143` @ 05:33:47 | **+77 min** |
| G4BCRUP7 | `2026-08-16T07:05:00+0200` | `8c02c047` @ 05:45:28 | **+79 min** |
| the session handoff | "Handoff — 2026-08-16 ~07:20" | written before 05:56 | **+84 min** |

All three are round numbers (`:50:00`, `:05:00`, `~07:20`). They were **typed, not generated**.
`trdd-design-tasks.md` already mandates `date +%Y-%m-%dT%H:%M:%S%z`; nothing checks it.

## Why it matters — and why it is NOT caught today

`updated:` is what the board sorts on, so a future stamp pins the card to the top **forever** —
and it silently outranks every honestly-stamped card. Worse for this project specifically, the
field is read as *when was this last measured*, and a session that trusts a stamp 77 minutes
ahead of the real clock is reasoning from a false measurement. That is the same failure class
that produced several wrong readings on 2026-08-16 (see ZM5LZ24Y's "FIVE of my own readings
were WRONG" list) — trusting a number without asking what produced it.

**`trdd-drift.py` cannot catch this today, and not by oversight:** it judges staleness from
`_last_touched_epoch` (git commit time, mtime for uncommitted/LOCAL), and never reads
`updated:` at all. So the field with no consumer is also the field with no validator — the two
facts are the same fact.

## Proposed fix

A new deduped finding in `scripts/detectors/trdd-drift.py`: parse frontmatter `updated:`, and
when it is more than a tolerance ahead of `now`, emit one `[trdd-drift]` line naming the card
and the offending value. Fail OPEN on an unparseable value (a nonsense date must not become a
second finding — `frontmatter_defect_for` already owns unreadable frontmatter).

Open design points, sent to the advisor before implementing:

- home (this detector vs its own) given it would be the first consumer of `updated:` here;
- tolerance (any future / 5 min / 1 h) — PROJECT TRDDs are pushed, so a second contributor's
  clock skew is in play, though the explicit UTC offset removes timezone as a risk;
- dedupe key `future-updated@<uid>@<value>` so a NEW bad stamp re-fires rather than being
  swallowed by a once-per-card key;
- whether a malformed value should be silent.

## Acceptance criteria

- [ ] Advisor verdict recorded here with the tolerance chosen and one line of rationale
      **ATTEMPT LOG — the consultation itself is the thing failing on this host.**
      Attempt 1 (06:02, full prompt: read `trdd-drift.py` + `trdd_common.py`, 5 questions) ran
      **34 min** with no verdict and was killed. Attempt 2 (06:36, deliberately narrowed to ONE
      file, 4 questions, ≤250 words) was still running at 13 min. A THIRD `fable-advisor:advisor`
      from an earlier, since-cleared session was found running **4 h** and killed — its answer had
      nowhere to land.
      **Not diagnosed as a wedge — that is a claim I cannot make yet**; slow and hung look
      identical from outside, which is the same "absence proves nothing" trap as ZM5LZ24Y. What IS
      measured: three consultations on this host, zero verdicts. If attempt 2 also returns nothing,
      implement under the advisor rule's own escape clause (proceed with an explicit written note
      that consultation failed) rather than leave a one-predicate detector change parked behind an
      unreliable gate — a mandatory-consultation rule that can only stall is a stall generator, and
      the board rule says a card that stops moving must say so out loud.
- [ ] The check ships in `trdd-drift.py` (or the home the verdict names), fail-open on parse
- [ ] A test asserting a future-stamped fixture FIRES and a correctly-stamped one does NOT
- [ ] A test asserting the dedupe key re-fires on a *different* offending value
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
      all clean

## Explicitly NOT in scope

Auto-correcting the stamp. A detector that rewrites the field it audits is not an auditor —
the same reasoning ZM5LZ24Y records for the C3 pin. Report it; a human or agent fixes it.
