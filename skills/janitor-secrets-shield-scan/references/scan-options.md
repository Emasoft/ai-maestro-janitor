# Scan options (janitor-secrets-shield-scan)

## Table of contents

- [Scan options](#scan-options)

## Scan options

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
  then its findings are kept with line null (never for a JSONL file: its walk is one pass, so past the limit it is a timeout skip).
- `--file-timeout-per-mb` extra seconds allowed per MB of file size. Default: 5.
- `--redact` replaces each secret found with a marker and keeps its value in the vault (plain-file redact; marker passes are those of `--passes`, default `secrets`, `cards`; `email` only when named). The `home` pass is opt-in with `--redact`: it runs last, rewrites home paths to `~`, and those rewrites are not restorable. To put the values back, see Restore below. Default: off, scan only.
- `--min-age-minutes` with `--redact`, a file modified within this many minutes is not written and is reported as skipped. Default: 10.
- `SHIELD_SCAN_VERSION` (environment): when set, replaces the version from `.claude-plugin/plugin.json` as the summary field `plugin_version`, and the scan does not read the manifest. It is checked before any file is read: a value that is empty, longer than 64 characters, or contains whitespace or a control character exits 2 with `SHIELD_SCAN_VERSION is set but empty or malformed`, with no fallback to the manifest. The value goes verbatim into the summary, which is why it is capped at 64 characters. Unset, the manifest version is reported. It exists for a byte-identical vendored copy of `scan.ts` that has no plugin manifest; a shell that exports it changes the `plugin_version` that the summary of the janitor scan reports, so export it only for such a copy.
