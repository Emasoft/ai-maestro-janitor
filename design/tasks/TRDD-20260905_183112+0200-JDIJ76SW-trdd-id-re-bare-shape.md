---
trdd-id: JDIJ76SW
title: TRDD filename matcher drops v1-migrated bare TRDD-<8hex>-<slug> cards from detectors and the board count
column: testing
created: 2026-09-05T18:31:12+0200
updated: 2026-09-05T19:00:30+0200
current-owner: janitor-session
task-type: bugfix
scope: project
min-approval-requirement: none
npt: []
eht: []
implementation-commits: [5ea63752]
external-refs: [ai-maestro:D552QXOU, ai-maestro:UAP7ZEJL, ai-maestro:f6f4664e]
relevant-rules: []
---

## Symptom

Peer session (ai-maestro hub, its card TRDD-D552QXOU) measured on 2026-09-05 that the
heartbeat's todo count disagreed with a direct grep of `design/tasks/*.md` by exactly one:
two dropped legacy-named cards plus one counted LOCAL-scope card cancelled out to a net −1
(their card TRDD-UAP7ZEJL). They renamed their two offending cards (ai-maestro commit
`f6f4664e`) so their own symptom is gone. The filename matcher that dropped them lives in
THIS repo (`ai-maestro-janitor`), shared by every consumer below, so the defect is ours to
fix even though the peer's instance of it is already worked around.

The net −1 was measured by an earlier ai-maestro-side session (card TRDD-UAP7ZEJL,
2026-09-05 03:13-04:58) — not by the hub session, which verified only the installed 3.4.14
cache regex.

## Root cause

`scripts/lib/trdd_common.py:193-199`:

```python
_TRDD_ID_RE = re.compile(
    r"^TRDD-"
    r"(?:"
    r"\d{8}_\d{6}[+-]\d{4}-([0-9A-Za-z]{8})"  # current: <timestamp>-<id8 base36>
    r"|([0-9a-fA-F-]{36})"                     # legacy:  <full-uuid>
    r")"
    r"-.+\.md$"
)
```

Two alternatives only:
- current: `TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8 base36>-<slug>.md`
- legacy: `TRDD-<36-char uuid>-<slug>.md`

It does NOT match the v1-migrated bare shape `TRDD-<8hex>-<slug>.md` (no timestamp
prefix before the id). A card in that shape is silently invisible to every consumer of
`extract_uid()` even when its frontmatter `trdd-id:` field is perfectly valid — the
matcher operates on the FILENAME, not the frontmatter, so a valid card is dropped purely
because of how it happens to be named.

## Blast radius

Every one of these calls `trdd_common.extract_uid(path.name)` (or `f.name`) and silently
gets `None` back for a bare-shape filename, which each caller treats as "not a TRDD" /
"no id" and skips:

- `scripts/dispatch.py:2656`, `:2738`, `:2896`
- `scripts/lib/ticket_proposal.py:110`, `:123`, `:233`, `:265`, `:429`, `:480`
- `scripts/findings_cli.py:54`
- `scripts/detectors/trdd-reminder.py:190`
- `scripts/detectors/trdd-cross-card-blindspot.py:245`
- `scripts/detectors/trdd-drift.py:290`, `:451`, `:500`, `:552`, `:647`

`trdd-drift.py` and `trdd-reminder.py` are the board-summary / stale-card detectors most
likely to visibly under-count; `dispatch.py` and `ticket_proposal.py` route work by uid, so
a dropped uid there means the card is never dispatched or reconciled at all, not merely
undercounted.

Governing spec: the filename recipe in `~/.claude/rules/trdd-design-tasks.md` step 2.

## Test coverage gap

`tests/test_trdd_common.py` covers `TRDD-<timestamp>-<id8>-<slug>.md` (lowercase and
uppercase base36 id) and `TRDD-<uuid>-<slug>.md`, but no case for the bare
`TRDD-<8hex>-<slug>.md` shape — confirmed absent by reading the whole file
(`tests/test_trdd_common.py:25-60`, the only `extract_uid` tests in the suite).

## Fix requirement

- Accept the bare shape `TRDD-<8hex-or-base36>-<slug>.md` as a THIRD alternative in
  `_TRDD_ID_RE`, captured into the same group semantics `extract_uid()` already returns
  (an 8-char id, case preserved) so every downstream consumer above needs no change.
- The bare-shape alternative must not swallow the current (timestamped) shape — order the
  alternation so the timestamped branch is tried first, or anchor precisely enough that a
  `\d{8}_\d{6}` prefix can never mis-parse as the bare id segment.
- Where a card has BOTH a filename id and a frontmatter `trdd-id:`, the frontmatter value
  remains authoritative on any mismatch (existing behavior elsewhere in the codebase —
  do not change that precedence, only stop the filename matcher from returning `None`).
- Add a regression test per shape (current-timestamped lowercase, current-timestamped
  uppercase, legacy-uuid, and the new bare shape) in `tests/test_trdd_common.py`.

## Acceptance

- [x] `_TRDD_ID_RE` (or its replacement) matches `TRDD-15ECPBSA-some-slug.md` and
      `extract_uid()` returns `15ECPBSA`.
- [x] `_TRDD_ID_RE` still matches the two existing shapes unchanged (no regression) —
      verified by `uv run pytest tests/test_trdd_common.py -k extract_uid`.
- [x] A new test `test_extract_uid_bare_shape_v1_migrated` (plus a shadow-ordering test and a
      short-id negative test) exists in `tests/test_trdd_common.py` asserting the bare-shape
      id is extracted, and passes via `uv run pytest tests/test_trdd_common.py -k
      test_extract_uid_bare`.
- [x] TARGETED suite green (coordinator, 2026-09-05 18:53–19:00): every test file naming the
      matcher or one of its six caller modules (`extract_uid|trdd_common|_all_folders_columns|
      trdd-reminder|trdd-drift|cross-card-blindspot|ticket_proposal|findings_cli` over `tests/`,
      24 files) — 411 + 243 passed, zero failures. Both runs exited 3 only because the
      source-tree write guard saw `scripts/dispatch.py` change under a concurrent worker
      (memory: rc3-with-every-test-passing-is-the-write-guard). The unscoped full run is NOT
      claimed here; the pre-publish gate performs it.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05T18:49:00+0200

**Files changed:**
- `scripts/lib/trdd_common.py:193-215` — added the bare `TRDD-<id8>-<slug>.md` alternative
  (group 3) to `_TRDD_ID_RE`, ordered AFTER the legacy UUID branch (a UUID's 9th char is also
  `-`, so bare-first would mis-capture only the UUID's first 8 hex chars); `extract_uid()`
  falls through `group(1) or group(2) or group(3)`.
- `tests/test_trdd_common.py` — added `test_extract_uid_bare_v1_migrated_shape`,
  `test_extract_uid_bare_shape_does_not_shadow_legacy_uuid`,
  `test_extract_uid_rejects_short_id`, and `test_bare_shape_card_is_counted_by_the_board`
  (exercises `dispatch._all_folders_columns` end to end in a tmp `design/tasks/` dir, not just
  `extract_uid`).

**Gate results (all captured to file, read whole, per rules):**
- `uv run pytest -q -p no:cacheprovider tests/test_trdd_common.py` → `99 passed`.
- `uv run ruff check scripts/lib/trdd_common.py tests/test_trdd_common.py` → `All checks passed!`.
- `uv run mypy scripts/ --ignore-missing-imports` → `Success: no issues found in 504 source files`.
- `uvx --with pyright pyright scripts/lib/trdd_common.py` → `0 errors, 0 warnings, 0 informations`.

**What is left:** the coordinator fills `implementation-commits:` on commit; the full-repo
`uv run pytest` (unscoped) has not been run to completion in this session — worth a spot-check
before archiving, but the touched surface (`extract_uid` + its one board-count caller) is
covered directly above.

## Notes

The peer session will not touch this repo's tree — this card is the owner-side record of
their finding, filed under standing autonomous-drain permission (todo-list queueing, no
code changed by the card author). The next session that picks this up chooses the
implementation approach (regex alternative vs. a small pre-check); no architecture
decision is pre-made here beyond the fix requirement above.

### Known trade-off (review 2026-09-05)

The shipped alternation admits an 8-DIGIT run for the bare-shape id, so a hand-named
`TRDD-20260905-slug.md` would parse as uid `20260905` (before this fix: `None`). No such
file exists in any of the three design roots on this host as of this review. Requiring at
least one letter in the bare-shape group was considered and rejected: it would reject
legitimate all-digit ids too (a hex id is all-digit with probability (10/16)^8 ≈ 2.3%;
base36 ids can be all-digit as well), trading one unmeasured false-positive risk for a
real false-negative one. The regex stays as committed.

## Approval log
