# Findings file format (janitor-secrets-shield-scan)

## Table of contents

- [Record kinds and fields](#record-kinds-and-fields)

## Record kinds and fields

The findings file is JSON lines: `finding` (path, kind, line or null, count),
`skip` (path, reason), with `--redact` also `residual` (path, kind, count), and
the summary last. It never holds a secret value.
Text inside a shield marker (`[REDACTED-BY-SECRET-SHIELD. …]` or `[JANITOR-REDACTED:…]`) is never read, so a re-scan of a redacted tree does not count its markers, and a secret hidden inside text shaped like a marker is not found.
A finding with line null was found in the whole file but not on one line (a
secret split over lines, or, in a plain file, the per-line pass was killed by the time limit).
A finding of kind `json-unredactable` is a JSON line (in a `.jsonl` or `.ndjson`
file) that holds a finding the shield could not hide without breaking the line:
it is counted in both modes, one per such line, and with `--redact` the file is
not written (skip `json-broken`). `jsonl_lines_not_json` in the summary counts
the non-blank lines of those files that are not JSON; they are read as text.
The file is private to the owner (mode 0600). A path inside any git work tree
is refused (exit 2), because the file says where the secrets are.
