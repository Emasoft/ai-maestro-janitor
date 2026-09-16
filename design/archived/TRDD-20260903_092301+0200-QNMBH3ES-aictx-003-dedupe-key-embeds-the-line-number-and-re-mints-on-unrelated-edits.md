---
trdd-id: QNMBH3ES
title: AICTX-003 dedupe key embeds the line number so an unrelated edit above the match re-mints a byte-identical proposal
column: complete
created: 2026-09-03T09:23:01+0200
updated: 2026-09-03T23:38:32+0200
current-owner: janitor-main-session
task-type: bugfix
priority: normal
severity: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [detector, agent-context-integrity, issue-catalog, dedupe]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: [b0dca228, 436cca65, 4d70ca78]
external-refs: [janitor#291]
created-by: issue triage 2026-09-03
---

# AICTX-003 dedupe key is line-number-unstable

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:05:58+0200

- QNMBH3ES-migration-order follow-up (2026-09-03T11:05:58+0200): fixed four more advisor/fork-
  confirmed defects in the same migration path.
  1. **Order** — `migrate_legacy_where` now runs BEFORE the raise loop in `main()` (was after):
     the old order minted a fresh new-key proposal first, then re-keyed the legacy entry onto
     that same key, landing two files under one dedupe key forever. New test:
     `test_migration_runs_before_the_raise_loop_so_no_duplicate_proposal_survives`.
  2. **Many legacy entries → one key** — `migrate_legacy_where` (`scripts/lib/issue_catalog.py`)
     now tracks a `taken: set[str]` (seeded from already-pending new-shape keys, grown as each
     legacy entry is migrated); a second legacy entry proximity-matching an already-taken key is
     dropped, never re-keyed onto it too. New test:
     `test_migrate_legacy_where_drops_a_second_legacy_entry_claiming_an_already_taken_key`.
  3. **Stamp-before-process** — `state.atomic_write(last_hash_file, signature)` moved to the LAST
     statement of both success paths in `main()` (was right after `_scan`, before anything that
     could still raise). New test:
     `test_last_hash_stamp_is_written_only_after_the_fire_fully_succeeds` (forces the crash by
     monkeypatching `agent_config_patterns.scan_text`, not the detector's own logic).
  4. **Capped scan** — `migrate_legacy_where` takes a new `scanned_rels: set[str] | None` kwarg;
     a legacy entry whose rel fell outside the cap is left completely untouched. `main()` also
     skips `reconcile` entirely on a capped fire (absence from a live set built without scanning
     every candidate proves nothing) and logs `scan capped at N of M candidate files — reconcile
     skipped`. New test:
     `test_a_capped_scan_leaves_an_unscanned_files_legacy_proposal_untouched_and_skips_reconcile`.

  Gates green: `ruff check scripts tests` clean, `mypy scripts/ --ignore-missing-imports` clean
  (502 files), `pytest tests/test_agent_context_integrity.py tests/test_issue_catalog.py -q` →
  87 passed (38 test functions in the detector file, up from 34).

  **NEXT ACTION:** none — ready for `testing`/`ai_review`. No git add/commit/push performed (out
  of scope per this dispatch).

## Earlier state (2026-09-03T10:20:00+0200) — superseded by the block above

Implemented + tested. Added `_dedupe_where(rel, f)` at
`scripts/detectors/agent-context-integrity.py:283` (`sha1(f.matched_text)[:12]:{rel}:{f.rule_id}`,
hash first so the 200-char `_fields` cap in `issue_catalog.py` truncates the tail, never the
hash). Used it in BOTH `raise_issue`'s `where=` (was line 601, now via the helper) and
`reconcile`'s live-wheres list (was line 625) — lockstep, per the card's warning. The line number
moved to `evidence=[f"{rel}:{f.line}"]` so it stays human-jumpable without re-entering the key.
No separate `dedupe_key` was added (`where` alone still selects the key, per the card).

3 new tests in `tests/test_agent_context_integrity.py` (all pass, isolated HOME/project fixture
`_catalog_project`, no mocking of the catalog — real `issue_catalog.raise_issue`/`reconcile`
against a scratch `design/proposals/`):
`test_dedupe_key_is_stable_when_an_unrelated_edit_shifts_the_line`,
`test_dedupe_key_differs_for_two_distinct_matches_in_the_same_file`,
`test_an_old_line_keyed_proposal_is_withdrawn_on_the_next_reconcile`.

Gates green: `ruff check` clean, `mypy` clean on the touched detector, `pytest
tests/test_agent_context_integrity.py tests/test_issue_catalog.py -q -p no:randomly` → 79 passed.

**NEXT ACTION:** none — ready for `testing`/`ai_review`. No git add/commit/push performed (out
of scope per the dispatch prompt).

- QNMBH3ES-unique-match follow-up (2026-09-03T10:11:09+0200): `migrate_legacy_where` no longer
  guesses on an ambiguous `rel` (two live findings, same file, same rule) — it now takes
  `new_keys_by_rel: dict[str, list[str]]`, migrates only when exactly one candidate key exists,
  and drops (never re-keys, never merges) otherwise, counting the ambiguous case separately in
  the fire log (`migrated N, dropped M (ambiguous A)`). Caller updated in
  `scripts/detectors/agent-context-integrity.py`. Checked the `_dedupe_where` empty-span
  `ValueError` propagation asked about in the same follow-up: it is NOT swallowed inside
  `agent-context-integrity.py` — it raises out of that detector's `main()`. But each detector
  runs as its OWN subprocess (`dispatch.py::_run_detector`, `subprocess.run([script,
  "--one-shot"], ...)`), so the exception only crashes that child process (Python prints the
  traceback to the detector's inherited stderr and exits 1); it never reaches `dispatch.py`'s
  own process. `_run_detector` then observes `proc.returncode != 0` and DOES swallow it into a
  log line (`state.log_line("dispatch", f"detector '{name}' exited non-zero")` +
  `_record_default_outcome(name, "error:rc=1", started)`) — the heartbeat itself proceeds to the
  next detector unaffected. So: guard swallows = yes, but at the subprocess-boundary in
  `dispatch.py`, not inside the detector's own exception handling (there is none there).

## Measured (janitor#291, re-verified 2026-09-03)

`scripts/detectors/agent-context-integrity.py:601` raises the finding with
`where=f"{rel}:{f.line}"`, and `scripts/lib/issue_catalog.py::_finding_key` (~line 578) folds
`where` into the dedupe key. Any edit ABOVE the flagged span shifts `f.line`, the key changes,
and the catalog mints a second proposal whose content is byte-identical to the first. The
suppressive `refused` disposition shipped for janitor#110 is defeated while the key itself moves.

## Fix

Change `where` in BOTH `raise_issue` at `scripts/detectors/agent-context-integrity.py:601` AND
`reconcile` at `scripts/detectors/agent-context-integrity.py:625` in lockstep to
`{rel}:{rule_id}:{sha1(matched_span)[:12]}` — hash BEFORE a long `rel`, since `_fields` caps
`where` at 200 chars (`issue_catalog.py:559`/`574`). Keep the line in `evidence`/the human
message so the reader can still jump to it. Do NOT add a separate `dedupe_key` while `:625`
stays line-shaped: `issue_catalog.reconcile` keys via `_finding_key(..., "")` = `code:where`
(`issue_catalog.py:799`), so a mismatched `where` between the two call sites would retract
every live proposal on the next fire. The lockstep change to both call sites IS the
acceptance-#3 migration — old line-keyed entries drop out of `live` once `where` no longer
carries the line.

## Acceptance

- [x] Test: the same match at line 40 and, after inserting 3 lines above it, at line 43 yields
      ONE catalog entry (second raise is a no-op / same key). Proof:
      `test_dedupe_key_is_stable_when_an_unrelated_edit_shifts_the_line` —
      `aci._dedupe_where(rel, at_40) == aci._dedupe_where(rel, at_43)`; first raise
      `first_seen=True`, second `first_seen=False`; `len(_proposals(...)) == 1`.
- [x] Test: two different matched spans in the same file under the same rule yield TWO keys.
      Proof: `test_dedupe_key_differs_for_two_distinct_matches_in_the_same_file` — distinct keys,
      `len(_proposals(...)) == 2` after both raises.
- [x] Existing open AICTX-003 proposals keyed by line are retracted or re-keyed on the next
      detector pass (state the mechanism; no silent duplicates left behind). Mechanism:
      `main()` calls `issue_catalog.migrate_legacy_where(_CODE, new_key_by_rel)` BEFORE
      `reconcile` on every fire. It re-keys, in place, every pending proposal whose stored
      `where` still matches the retired `rel:line` shape and whose `rel` has a live finding
      this fire — rewriting its `ticket-dedupe-key:` frontmatter line to the new
      `digest:rel:rule_id` key, so `reconcile` then finds it already in `live` and leaves it
      alone (no re-mint churn). A legacy entry whose `rel` has no live finding this fire is a
      dead artifact and is deleted directly — never through `ticket_proposal.retract`, which
      would assert the finding was seen-then-cleared, a claim the old key format cannot back.
      Proof: `test_migrate_legacy_where_rekeys_live_findings_and_drops_vanished_ones_without_retract`
      — one still-present old-keyed proposal ends up rewritten with the new key, one vanished
      old-keyed proposal is removed from `design/proposals/`, and `ticket_proposal.retract` is
      never called for either, across the migration pass AND the follow-up `reconcile` call.
      (`test_an_old_line_keyed_proposal_is_withdrawn_on_the_next_reconcile` still covers the
      standalone `reconcile`-only path with no migration step in front of it.)

## Approval log

- 2026-09-03T23:38:32+0200 — COMPLETE. Reviewed by the janitor main session under the owner's standing delegation of the review columns (2026-09-03). Every acceptance box verified against the code, not taken from the card's own word.

## Notes and lessons learned
