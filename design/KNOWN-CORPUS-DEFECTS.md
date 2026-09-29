# Known corpus defects — janitor repo design/ (recorded, fix at next legitimate touch)

## KD-1: TRDD-CGOV2XO4 `pre-block-column: ` empty value (archived/, line 14)

- **What:** the cancelled card CGOV2XO4 (design/archived/TRDD-20260802_212643+0200-CGOV2XO4-context-integrity-file-contract.md) carries `pre-block-column: ` — field present, value empty. Same written-non-value class as the `superseded-by: NONE` phantom fixed in commit 6e59ea00.
- **Why not fixed now:** the card is archived/immutable (TRDD-MQE5D28T D8); the un-archive/edit/re-archive workaround was already used twice in one session (2026-09-29) and the review ruled a third cosmetic re-dance is the wrong move — "record, don't resurrect."
- **When to fix:** in the same batch as the NEXT legitimate reason to touch that file, or at the next janitor-corpus repair pass. The fix: delete the line entirely (a terminal card restores to nothing).
- **Rule for the future:** archived-card corrections AFTER the archive is pushed are forbidden — record the defect and fix at the next legitimate touch. Within an unfired session, a same-session misfiling may be corrected via un-archive once; that license is spent.

## KD-2: `cancelled-datetime:` minted field (same card, line 16)

- **What:** the field is invented (grammar has `created:`/`updated:`/`approval-datetime:`); it also duplicates the timestamp already on the Approval log line (:129) and in `updated:`. Three copies of one timestamp.
- **Harmless** (terminal card, no consumer distinguishes yet). Do not mint more fields like it; do not "fix" by re-dancing.
