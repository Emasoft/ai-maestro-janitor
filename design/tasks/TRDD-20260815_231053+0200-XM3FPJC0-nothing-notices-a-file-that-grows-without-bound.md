---
trdd-id: XM3FPJC0
title: Nothing notices a file that grows without bound — 231 MB of debug log accumulated for 11 days unseen
column: testing
created: 2026-08-15T23:10:53+0200
updated: 2026-08-15T23:38:00+0200
current-owner: janitor-main-session
task-type: feature
scope: project
approval-tier: 0
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-LCO8229M, TRDD-ZNN0UK5K, TRDD-1T53EKTN]
---

# Nothing notices a file that grows without bound

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-15

**The evidence, measured tonight.** A `[system-daemon-runaway]` alert fired naming a hot node
process and a 96%-full disk. The disk turned out to be CHRONIC (1.8 T of 1.9 T, 83 G free) and
unrelated, but underneath it sat a real balloon nothing had reported:
`/tmp/claude/statusline-debug.log` at **231 MB**, appended several times per second since
**2026-08-04** — eleven days. Truncated by hand (231 MB → 1.9 K); it regrew to 16 K within four
minutes, so the writer is live and unbounded.

**The gap, verified before writing this.** 73 detectors exist. The three purge detectors
(`reports-purge`, `screenshot-purge`, `trashcan-purge`) are all AGE-based sweeps of directories
the janitor OWNS, and `state.rotate_log_if_big` bounds the janitor's OWN logs at 1 MiB. **Nothing
watches SIZE or GROWTH of a file the janitor does not own**, so a third-party writer can balloon
indefinitely and the only signal is a disk-pressure alarm that names the wrong culprit — which is
exactly what happened.

This is the same failure family as `reports-purge`: TRDD-LCO8229M exists because forensics on a
39 GB fseventsd runaway (TRDD-ZNN0UK5K) tied disk pressure AND fsevents volume to high-rate
automated FS churn. A log written several times a second is that churn; the janitor already
bounds its own contribution and is blind to everyone else's.

**SHIPPED 2026-08-15; column `dev → testing`.** `scripts/detectors/runaway-file-growth.py` exists,
is registered hourly in `dispatch.py` and listed in `_ADVISORY_DETECTORS`, with 15 tests, clean
ruff+mypy. FIELD-RUN against the real filesystem rather than fixtures only: silent at the default
100 MB threshold (the balloon had been truncated), and at a lowered threshold it correctly named
all three real files under `/tmp/claude` — including a **42 MB `statusline-error.log`** nobody knew
existed, holding 570,525 lines of tracebacks (11,045 `URLError` + 1,918 `OSError`) from the SAME
writer. The gap closed on its first real run, and the `/tmp` → `/private/tmp` realpath dedupe was
confirmed live (one entry per inode, not two).

**NEXT ACTION.** Watch one real hourly fire in a session that did not run it by hand, and confirm
the re-alert policy behaves over time: a static file named once, a growing one re-announced only
after it doubles.

## Design

**REPORT ONLY — it must NEVER delete.** The files it watches belong to other tools, other projects
and the user. Age-purging a directory the janitor owns is safe; deleting a 200 MB file because it
is large is not, and RULE 0 plus the cross-project rule both forbid it. The detector NAMES the
file, its size and its growth, and a human decides. That is the whole product.

* **Scan** each configured root for regular files at or above a byte threshold. Default root
  `/tmp/claude` (where tonight's balloon lived); default threshold 100 MB.
* **Resolve and dedupe by realpath.** On macOS `/tmp` is a symlink to `/private/tmp`, so a naive
  two-root scan reports the same inode twice and makes the finding look like two runaways.
* **Re-alert only on real growth.** State maps realpath → last-alerted size; a path re-alerts only
  when it has grown by at least a factor (default 2×). Without this an hourly detector repeats the
  same 231 MB line forever, and a detector that cries the same wolf every hour is one the reader
  learns to skip — the failure `screenshot-purge`'s own history warns about.
* **Fail open, never raise.** An unreadable root, a vanished file mid-scan, or a permission error
  degrades to "nothing to report" — a tidiness advisory must never break a heartbeat.

Knobs: `CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_MIN_BYTES` (default 104857600),
`CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_ROOTS` (`:`-separated, default `/tmp/claude`),
`CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_GROWTH_FACTOR` (default 2.0). Setting the threshold to 0
disables the detector.

## Acceptance

* [ ] A file at or above the threshold is reported once, with its size and its age.
* [ ] The same unchanged file is NOT reported again on the next fire.
* [ ] A file that doubles IS reported again, naming the growth.
* [ ] A file below the threshold is never reported.
* [ ] The same inode reached through `/tmp` and `/private/tmp` is reported ONCE.
* [ ] Nothing is ever deleted or modified by the detector.
* [ ] An unreadable/absent root is a silent no-op, not an exception.
* [ ] Registered in `dispatch.py` (hourly) and in `_ADVISORY_DETECTORS`.
* [ ] ruff + mypy clean; full suite green.

## Notes

Tonight's specific writer is `~/.claude/statusline.py:814,824` — the user's own script, OUTSIDE any
project tree, so this session did not edit it and only reported the three-line fix (gate the debug
write behind an env var). That separation is the point of a report-only detector: the janitor can
see the balloon everywhere, and only ever fixes what it owns.
