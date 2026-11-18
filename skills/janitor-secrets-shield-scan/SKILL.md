---
name: janitor-secrets-shield-scan
description: Scans a project or a folder tree for secrets (API keys, tokens, private keys, card numbers) with the rules of the janitor secret shield (hooks/secret-shield), and writes the findings file outside any repo. With --redact it replaces each secret with a marker and keeps the value in a local vault. It never prints a secret value. Use when asked to scan for secrets, find leaked API keys or tokens, audit a project or folder tree for credentials, or redact, mask or remove secrets from files. Trigger with /janitor-secrets-shield-scan [path] [--all] [--redact].
---

# Janitor secrets-shield scan

## Overview

Walks a project (or any folder tree), runs the secret shield rules over every
file in scope, and writes one JSON line per finding to a findings file. The
file holds paths, kinds and line numbers, never a secret value. The run prints
the summary line and the findings file path. By default nothing in the scanned
tree is changed. With `--redact` the files in the working tree are rewritten:
each secret is replaced by a marker and its value is kept in a local vault (see
Redact). Git history is not scanned yet (a later version).

## Prerequisites

- `bun` and `git` on PATH.
- `${CLAUDE_PLUGIN_ROOT}` set (Claude Code sets it); the scanner is
  `${CLAUDE_PLUGIN_ROOT}/scripts/shield_scan/scan.ts`.
- Tested on macOS only.

## Instructions

1. Root = the path in `$ARGUMENTS`, else the current working directory. Pass
   the user's options through, each argument quoted as one word, so a path
   with spaces stays one argument. Expand a leading `~` in a path argument
   (the root or `--out`) to the home folder before quoting it: a quoted `~`
   is not expanded by the shell, and the scanner does not expand it either,
   so it would look for a folder named `~` in the current directory and
   exit 2. A root whose name starts with a dash is passed as an absolute
   path or as `./<name>`: the scanner reads any argument starting with a
   dash as an option and stops with exit 2.

2. Run:

   ```bash
   bun run "${CLAUDE_PLUGIN_ROOT}/scripts/shield_scan/scan.ts" [options] [root]
   ```

3. A large tree can take hours: run it with `run_in_background` and read the
   two stdout lines when it ends. Never poll.

4. Report the result in words (see Output). Never call a run clean when it is
   incomplete or when part of the tree was not scanned.

## Options

- `--all` scans every file, hidden and gitignored ones too, plus each
  repository's `.git/config` (it can hold a token in a remote URL), never
  other `.git` content. Default: off, the scope follows the ignore rules.
- `--passes` comma list of passes to run, from `secrets`, `cards`, `email`,
  `home`; an unknown name exits 2. Default: `secrets,cards`.
- `--jobs` number of worker processes. Default: the smaller of 8 and the CPU
  count minus 1, at least 1.
- `--out` path of the findings file. Default:
  `~/.secrets_shield/scans/<root name>-<timestamp>.jsonl`.
- `--max-file-mb` files larger than this many MB are skipped as over-size
  (with `--redact`, text files over it go to the large lane, see
  `--max-large-mb`). Default: 64.
- `--max-large-mb` with `--redact`, text files over `--max-file-mb` and up to
  this many MB are redacted one at a time in a large lane; a text file over it
  is neither scanned nor redacted, is reported as `not-scanned-too-large`, and
  makes the run incomplete (exit 3). A binary file over `--max-file-mb` is an
  ordinary binary skip. Must be at least `--max-file-mb`. Default: 1024.
- `--file-timeout-base` fixed seconds of the per-file time limit. Default: 30.
  The limit is base plus per-MB times the file size in MB; a file that runs
  past it is skipped as a timeout, unless its whole-file pass had finished:
  then its findings are kept with line null.
- `--file-timeout-per-mb` extra seconds allowed per MB of file size. Default: 5.
- `--redact` replaces each secret found with a marker and keeps its value in the vault (plain-file redact; marker passes are those of `--passes`, default `secrets`, `cards`; `email` only when named). The `home` pass is opt-in with `--redact`: it runs last, rewrites home paths to `~`, and those rewrites are not restorable. To put the values back, see Restore below. Default: off, scan only.
- `--min-age-minutes` with `--redact`, a file modified within this many minutes is not written and is reported as skipped. Default: 10.

## Redact

`--redact` rewrites files in the working tree. Run it only when the user asks
for it, and first tell the user that it rewrites working-tree files and that
the secret values go to a plain vault file (below). Run it first on a copy or a
sample of the tree, not on the only copy.

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
  (`not-scanned-too-large`) and the run is incomplete. The large lane has been
  tested only on files of tens of KB; peak memory and time on large files are
  not measured.
- Rounds and residual: the scanner also replaces copies of a redacted value
  that no rule matched, then scans again. If that finds something it runs
  another round (at most 3) and writes the file once. What is still found
  after the last round is the residual: the file is still written and the run
  exits 1.
- Agents never run `restore.ts` (see Restore).

### Git repositories

Redacting tracked files changes only the working tree. Every committed secret
stays in the repo objects and the index, and `git checkout`, `git stash` or
`git reset` brings it back. History is never rewritten (owner decision). A
history scan is a later version. Tell the user this whenever a repo is
redacted.

### JSONL files

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

## Exit codes

- 0: complete, no findings. With `--redact`: complete, and no finding was left
  unredacted and `residual` is 0.
- 1: complete, with findings. With `--redact`: `findings_not_redacted` or
  `residual` is above 0.
- 3: incomplete: a timeout, read-error, crash, git-error or unreadable-dir
  skip, whatever the findings. With `--redact` also a text file over
  `--max-large-mb` (`files_not_scanned` above 0).
- 2: usage or fatal error. The scanner writes a fixed text on stderr; show it.
  With `--redact` also a vault that cannot be opened or written.

## Output

stdout holds two lines: the summary JSON line, then the findings file path.
Report in words: `files_scanned`, `bytes_scanned`, `findings`,
`files_with_findings`, each nonzero reason under `skipped`, `complete`,
`mb_per_s`, and the findings file path.

When `gitignored_entries` is above 0, `ignored_repos` is above 0 or
`ancestor_rules_skipped` is true, say in plain words what was not scanned (for
example "140 gitignored entries and 40 repositories inside ignored folders were
not scanned") and name `--all`. Never call a run clean when `complete` is false
or when any of those three is set.

The findings file is JSON lines: `finding` (path, kind, line or null, count),
`skip` (path, reason), with `--redact` also `residual` (path, kind, count), and
the summary last. It never holds a secret value.
A finding with line null was found in the whole file but not on one line (a
secret split over lines, or the per-line pass was killed by the time limit).
The file is private to the owner (mode 0600). A path inside any git work tree
is refused (exit 2), because the file says where the secrets are.

On request, list files and kinds from the findings file (for example with
`jq`). Never open or print the flagged lines of the scanned files: they hold
the secrets.

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

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset or `scan.ts` missing: abort, ai-maestro-janitor
  is not installed in this session.
- `git` missing: exit 2 with a fixed message. `bun` missing: the shell
  reports command not found (exit 127). Either way ask the user to install
  it; do not retry.
- Exit 2: show the stderr text verbatim. A findings path inside a git work tree
  is fixed by passing `--out` with a path outside any repo.
- Exit 3: the scan is incomplete; name the skip reasons and say the result is
  not a clean bill of health.

## Examples

```text
User: /janitor-secrets-shield-scan
User: scan this project for leaked API keys
User: /janitor-secrets-shield-scan ~/Code/app --all
User: audit the folder ~/work for credentials and list the files
```

## Scope

- Default scope follows `.gitignore`, `.git/info/exclude` and the global
  excludes file. Ignored folders and the repositories inside them are not
  scanned. A repository two or more levels below an ignored folder is skipped
  and not counted in `ignored_repos`.
- `--all` scans every file including hidden and ignored ones and each
  repository's `.git/config`, never other `.git` content.
- Symlinks are never followed. A file over `--max-file-mb` is skipped as
  over-size; with `--redact`, a text file over it goes to the large lane (see
  Redact).
- Git history is not scanned yet (a later version).
- Nothing in the scanned tree is changed unless `--redact` is given (see
  Redact).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/shield_scan/scan.ts`: the scanner.
- `${CLAUDE_PLUGIN_ROOT}/hooks/secret-shield/`: the shield rules it applies.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve the root (`$ARGUMENTS` path, else the cwd); quote each argument
- [ ] Run `bun run "${CLAUDE_PLUGIN_ROOT}/scripts/shield_scan/scan.ts" [options] [root]` in the background
- [ ] Read the summary line and the findings file path when it ends
- [ ] Report counts, skips, completeness and the findings file path in words
- [ ] Name what was not scanned (ignored entries, ignored repos, ancestor rules) and `--all`
- [ ] Never print a secret value or the flagged lines of the scanned files
- [ ] Add `--redact` only when asked, after telling the user it rewrites working-tree files and that the values go to a plain, unencrypted vault
- [ ] For a git repo, say that committed secrets stay in the repo and checkout, stash or reset brings them back
- [ ] Do not run `--redact` on a tree with JSONL files the user needs intact
- [ ] Report the redact summary fields in words (see Output); never call a redact complete while `findings_not_redacted` or `residual` is above 0
- [ ] Never run `restore.ts` (a person at a terminal only)
