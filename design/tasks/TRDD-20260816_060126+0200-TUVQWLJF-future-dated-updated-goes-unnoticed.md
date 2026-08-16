---
trdd-id: TUVQWLJF
title: A hand-typed future-dated updated field pins a card to the top of the board and nothing notices
column: testing
created: 2026-08-16T06:01:26+0200
updated: 2026-08-16T07:15:30+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: [fe8590c3]
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
      **OUTCOME: attempt 2 was killed at 23 min, still with no verdict. Consultation FAILED —
      three attempts, zero answers — so this shipped under the advisor rule's escape clause, and
      the four decisions below are MINE, recorded with their rationale so the advisor (or a
      reader) can overturn any of them against a stated argument rather than a shrug.**

      1. **Home: colocate in `trdd-drift.py`**, with the parser in `trdd_common.py` beside
         `FM_CREATED_RE`. The detector already walks every TRDD in BOTH scopes, already reads the
         head, already dedupes, already prints `[trdd-drift]`. A separate detector would duplicate
         that whole walk for one predicate, and a second walk is a second thing to keep in step.
      2. **Tolerance: 300 s.** The mandated format carries an explicit UTC offset, so timezone is
         not what the tolerance absorbs — CLOCK SKEW between contributors is, because PROJECT
         TRDDs are pushed. Past ~5 min on an NTP-synced host the skew is itself worth surfacing.
         Two orders of magnitude below the +77/+79 min errors measured.
      3. **Dedupe key carries the VALUE** (`future-updated@<uid>@<value>`), unlike the file's
         other once-per-card keys: a corrected card stops matching, and a SECOND bad stamp is a
         new key rather than being swallowed. A card someone is actively mis-editing is exactly
         where a once-forever key fails.
      4. **Checked BEFORE the active-column filter**, so terminal cards are audited. Rule §12
         freezes a terminal TRDD's body but still permits `updated:` to change, and 240 of ~300
         cards here are `complete`/`published` — filtering first would exempt the majority of the
         board from the one check about board ordering.
- [x] The check ships in `trdd-drift.py` (or the home the verdict names), fail-open on parse —
      `trdd_common.future_updated()` (pure) + the emit block in `trdd-drift.py`; unparseable,
      missing, naive (offset-less) and calendar-invalid values all return None
- [x] A test asserting a future-stamped fixture FIRES and a correctly-stamped one does NOT —
      `tests/test_trdd_drift_future_updated.py`, end to end through the real detector as a
      subprocess. **The first version of this assertion was WRONG and is worth recording:** it
      read `"TRDD-BBBBBBBB" not in out`, which failed against CORRECT behaviour, because the
      honest control card is also 100 days old and `column: todo`, so it legitimately earns the
      ORDINARY staleness line. Asserting on whole stdout conflated two findings; the test now
      asserts line-wise on the FUTURE lines only.
- [x] A test asserting the dedupe key re-fires on a *different* offending value — same file:
      report, re-run silent on the unchanged value, then a new value fires again
- [x] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
      all clean — ruff and mypy clean over the whole tree (485 files); 13 new tests pass and the
      279-test `-k trdd` selection is green; full-suite run recorded in the commit

## The check has a DETECTION WINDOW — found by measuring, not by reasoning

Non-vacuity was proven against the real corpus rather than a fixture, and the proof exposed a
limitation worth stating plainly.

Replaying the pre-correction `G4BCRUP7` body (`git show 8c02c047:…`, carrying the fabricated
`updated: 2026-08-16T07:05:00+0200`) through the real detector produced **nothing** — because by
then the wall clock read `07:06:42`. The stamp was no longer in the future. Re-stamping the same
real card two hours ahead fired it immediately:

```
[trdd-drift] TRDD-G4BCRUP7 updated='2026-08-16T09:06:42+0200' is in the FUTURE — …
```

So: **a fabricated stamp is only catchable until the clock overtakes it.** Tonight's +77 min
errors had a ~77-minute window; after that they are invisible to this check forever, sitting at
the top of the board looking ordinary. The check prevents the fresh mistake; it cannot audit the
corpus for old ones.

The complementary check — compare `updated:` against the timestamp of the commit that WROTE it —
has no window, and is how all three were actually found today (`git log -1 --format=%ad`). It is
deliberately NOT built here: it needs git per card, which this detector's hot loop avoids, and it
belongs in a reconciliation pass rather than a per-heartbeat sweep. Filed as a note rather than a
card because nothing is currently mis-stamped; if a fourth instance appears, that is the fix to
build, and this paragraph is the reason not to re-derive it.

## Explicitly NOT in scope

Auto-correcting the stamp. A detector that rewrites the field it audits is not an auditor —
the same reasoning ZM5LZ24Y records for the C3 pin. Report it; a human or agent fixes it.
