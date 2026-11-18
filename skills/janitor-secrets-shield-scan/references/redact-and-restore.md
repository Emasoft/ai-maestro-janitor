# Secrets-shield scan: redact and restore detail

Detail moved out of SKILL.md to keep its body under the per-skill token cap. The
safety facts stay in SKILL.md; this file holds the full text of the redact and
restore behaviour.

## Table of contents

- [Redact details](#redact-details)
- [Git repositories](#git-repositories)
- [JSONL files](#jsonl-files)
- [Restore](#restore)
- [Redact summary fields](#redact-summary-fields)

## Redact details

- Marker: each secret becomes `[REDACTED-BY-SECRET-SHIELD. Type: <type>. ID: <UUID>]`.
  The same value in one file gets one ID. A second run changes nothing.
- Vault: a plain SQLite file at `~/.secrets_shield/vault.db`, not encrypted.
  Anyone who can read that account's files can read every value (owner
  decision, TRDD-QM8YRCZ5). Values never reach stdout, stderr or the findings
  file.
- Passes: those of `--passes` (default `secrets,cards`; `email` only when
  named). `home` runs last, rewrites home paths to `~`, is not vaulted and not
  restorable.
- A file is replaced only after its vault rows are committed and a restore
  check shows the original comes back byte for byte (else `align-error`).
- Never written, still scanned and counted in `findings_not_redacted`; each is
  a `skip` record and a count under `skipped`: `git-internal` (anything inside
  a `.git` folder, or a `.git` pointer file; with `--all`, `.git/config` is
  scanned but never rewritten, so a token there makes the run exit 1),
  `vault-folder`, `hardlinked`,
  `recent` (modified within `--min-age-minutes`), `not-utf8` (not lossless
  UTF-8), `git-operation` (merge, rebase, cherry-pick, revert or bisect in
  progress), `git-check-failed`, `align-error`, `not-regular-at-write`,
  `outside-root`, `changed-during-redact`, `write-error`. Symlinks are never
  followed.
- Large lane: a text file over `--max-file-mb` and up to `--max-large-mb` is
  redacted one at a time. A larger text file is neither scanned nor redacted
  (`not-scanned-too-large`) and the run is incomplete. Measured once per size
  on generated text with about one secret per 100 KB (2026-11-18): 100 MB took
  36 s and 300 MB took 592 s; the redact worker needed at least about 13 times
  the file size in memory (a sampled lower bound) and restore about 4 times;
  redact then restore gave back identical bytes. Time grew faster than size
  between those two runs (cause not found yet), so a text file over about
  300 MB with many secrets may run past its per-file time limit. On a machine
  with little memory pass a lower `--max-large-mb`.
- Rounds and residual: the scanner also replaces copies of a redacted value
  that no rule matched, then scans again. If that finds something it runs
  another round (at most 3) and writes the file once. What is still found
  after the last round is the residual: the file is still written and the run
  exits 1.
- Agents never run `restore.ts` (see Restore).

## Git repositories

Redacting tracked files changes only the working tree. Every committed secret
stays in the repo objects and the index, and `git checkout`, `git stash` or
`git reset` brings it back. History is never rewritten (owner decision). A
history scan is a later version. Tell the user this whenever a repo is
redacted.

## JSONL files

A `.jsonl` or `.ndjson` file is redacted as plain text in this version: the
scanner does not treat it differently and does not check that each line is
still valid JSON. In one probe (a fake token in a JSON string on one line, a
fake private key escaped in a JSON string on another) both secrets became
markers and both lines still parsed.
The JSON-aware mode is a later version. Do not run `--redact` on a tree with
JSONL files you need intact yet.

## Restore

`bun run <plugin root>/scripts/shield_scan/restore.ts [--any-origin] [--max-large-mb N] <file|root>` puts the value kept in the vault back in place of each marker. It is for a person at a terminal only: agents never run it. With the real vault it refuses to run unless stdin is a terminal; that stops an accidental run, it is not a boundary.

- It reads every file under the root, gitignored files too, but never the content of a `.git` folder or the vault folder. Home paths rewritten to `~` are not restored.
- A marker is restored only in the file it was redacted in. A marker in a moved or copied file is left and reported as `moved`, unless `--any-origin` is given. Another hard-link name of a redacted file is reported as `moved`, because its path is not the origin recorded in the vault; with `--any-origin` it reaches the hardlink guard and is skipped as `hardlinked`.
- A hardlinked file, a file that is not lossless UTF-8, and a file in a repo with a merge, rebase, cherry-pick, revert or bisect in progress are left as they are and reported.
- A binary file (a NUL in its first 8192 bytes) is left as it is and is not searched for markers, so a marker in one does not change the exit code; the summary counts it under `skipped` as `binary`.
- A file that changes while it is being read is skipped as `changed-during-restore`; the exit code is 1 when the bytes read held a marker.
- There is no `--min-age-minutes` guard: a recently changed file is restored too. A file open in an editor gets its markers back if the editor later saves its old buffer; close it and run restore again (the vault keeps the values).
- `--max-large-mb` (default 1024): a text file over it is not read, and the run is incomplete.
- Output: JSON lines on stdout (left, note and skip records, then a summary), never a value. Exit: 3 incomplete (it wins over 1); else 1 a marker was left or a file with markers was skipped; else 0 every marker found was restored; 2 usage, refused, or no vault.

## Redact summary fields

With `--redact` the summary also holds `redact`, `min_age_minutes`,
`residual_check` and these counts. Report them in words: `files_redacted` (files
rewritten), `values_vaulted` (distinct values in the vault, counted per file),
`findings_not_redacted` (findings in files that were not written, reasons under
`skipped`; home paths are never counted), `residual` (hits still found between
the markers after the last round, one `residual` record each),
`rounds_used_max` (1 to 3), `files_not_scanned` (text files over
`--max-large-mb`), `large_lane_files` and `home_rewrites` (home paths rewritten
to `~`, not restorable). `findings` and the `finding` records are what the scan
found before redaction, not what is left. Never call a redact complete while
`findings_not_redacted` or `residual` is above 0, or `complete` is false.
