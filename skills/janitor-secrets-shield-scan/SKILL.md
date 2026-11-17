---
name: janitor-secrets-shield-scan
description: Scans a project or a folder tree for secrets (API keys, tokens, private keys, card numbers) with the rules of the janitor secret shield (hooks/secret-shield), and writes the findings file outside any repo. Use when asked to scan for secrets, find leaked API keys or tokens, or audit a project or folder tree for credentials. Scan only, it redacts nothing and never prints a secret value. Trigger with /janitor-secrets-shield-scan [path] [--all].
---

# Janitor secrets-shield scan

## Overview

Walks a project (or any folder tree), runs the secret shield rules over every
file in scope, and writes one JSON line per finding to a findings file. The
file holds paths, kinds and line numbers, never a secret value. The run prints
the summary line and the findings file path. Scan only: nothing is redacted or
changed in the scanned tree. Git history is not scanned yet (a later version).

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
- `--max-file-mb` files larger than this many MB are skipped as over-size.
  Default: 64.
- `--file-timeout-base` fixed seconds of the per-file time limit. Default: 30.
  The limit is base plus per-MB times the file size in MB; a file that runs
  past it is skipped as a timeout, unless its whole-file pass had finished:
  then its findings are kept with line null.
- `--file-timeout-per-mb` extra seconds allowed per MB of file size. Default: 5.
- `--redact` replaces each secret found with a marker and keeps its value in the vault (plain-file redact; passes `secrets`, `cards`, `email`; the `home` pass with `--redact` exits 2). No restore command exists until step 3a-4 (restore.ts), so do not run `--redact` on real data before then. Default: off, scan only.
- `--min-age-minutes` with `--redact`, a file modified within this many minutes is not written and is reported as skipped. Default: 10.

## Exit codes

- 0: complete, no findings.
- 1: complete, with findings.
- 3: incomplete: a timeout, read-error, crash, git-error or unreadable-dir
  skip, whatever the findings.
- 2: usage or fatal error. The scanner writes a fixed text on stderr; show it.

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
`skip` (path, reason), and the summary last. It never holds a secret value.
A finding with line null was found in the whole file but not on one line (a
secret split over lines, or the per-line pass was killed by the time limit).
The file is private to the owner (mode 0600). A path inside any git work tree
is refused (exit 2), because the file says where the secrets are.

On request, list files and kinds from the findings file (for example with
`jq`). Never open or print the flagged lines of the scanned files: they hold
the secrets.

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
- Symlinks are never followed. A file over `--max-file-mb` is skipped.
- Git history is not scanned yet (a later version).
- Nothing is redacted: scan only.

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
