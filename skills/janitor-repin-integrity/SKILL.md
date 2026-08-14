---
name: janitor-repin-integrity
description: Manually re-certify the C3 last-good pin (the HMAC tamper anchor over the running janitor version). Use when the janitor-self-integrity detector reports the pin is stale and the daemon's own periodic re-pin cannot reach GitHub (offline, no gh CLI, no releases yet), or when the daemon is down. Trigger with /janitor-repin-integrity, "re-pin the janitor", "the C3 anchor is stale and won't advance".
---

# Janitor repin-integrity

## Overview

The daemon's periodic self-heal (`certify_newest_if_clean`, TRDD-ZM5LZ24Y) advances the C3
last-good pin on every heartbeat fire, but ONLY when the candidate version equals the GitHub
`releases/latest` tag it resolved that fire (the F1 provenance gate — the strengthening that
requires the RELEASE CHANNEL to agree, not merely local cache-write access). That gate fails
CLOSED whenever the tag can't be resolved: offline, no `gh` on PATH, or the repo has no
releases yet. On such a machine the daemon path can never advance the pin at all — this skill
is the deliberate manual escape hatch for exactly that case.

**It reuses the daemon's own predicate** (runnable + non-quarantined + C2-clean via
`certify_newest_if_clean(..., force=True)`) instead of re-deriving a second, subtly different
notion of "the version we trust" — a second predicate is exactly how the earlier quarantine
defect got into this codebase. Its one difference from the daemon path: it MAY bypass the F1
provenance gate, because a human running it deliberately IS the provenance. It says so, in
plain words, on every run — so a log or another agent reading the output later can never
mistake a manual override for an automatic, provenance-confirmed certification.

## Instructions

1. Run the script:

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/repin_integrity.py"
   ```

2. Report the outcome verbatim (it already states the override, the certified/no-op result,
   and the reason on failure) — no summarizing needed.

## Output

- Always prints the manual-override notice first.
- `certified last-good=<version> ...` — a new version was pinned. Exit 0.
- `already current: last-good=<version> ...` — the anchor already names the version the stub
  would actually run. Exit 0.
- `nothing eligible to pin: ...` (stderr) — no cached version is runnable + C2-clean +
  non-quarantined. The existing pin (if any) is left completely untouched. Exit 1.

## What this does NOT do

- Does not weaken or bypass C2 (the manifest verification) — a dirty/mutated version is never
  pinned, override or not.
- Does not touch the quarantine list.
- Does not run `claude plugin update` or fetch anything from GitHub — purely local, purely the
  cache already on disk.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/repin_integrity.py` — the script (thin wrapper around
  `version_update_lib.certify_newest_if_clean`).
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/version_update_lib.py::certify_newest_if_clean` — the
  shared predicate + F1 gate + F2 `force` bypass.
- `design/tasks/TRDD-20260814_152921+0200-ZM5LZ24Y-c3-pin-never-advances-after-manual-update.md`
  — the full design (F1/F2 decision + rationale).
