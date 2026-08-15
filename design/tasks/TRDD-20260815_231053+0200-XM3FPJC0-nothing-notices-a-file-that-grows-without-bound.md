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

**RE-ALERT POLICY VERIFIED LIVE (2026-08-15 23:47), on real files rather than fixtures.** A second
invocation ~25 minutes after the first re-reported ONLY the file that had grown —
`statusline-debug.log`, 279.2 KB → 635.6 KB, past the 2× gate, and the line named the growth — while
staying SILENT on `state_blocks.txt` and the 42 MB `statusline-error.log`, both unchanged since the
first run. That is exactly the designed behaviour: a static file is named once, a balloon keeps
announcing itself.

Be precise about what this is NOT: both runs were MANUAL invocations at a lowered threshold, so the
autonomous hourly fire (and the state file surviving between two dispatcher-driven runs) is still
unobserved. The policy is proven; the scheduling is not.

**SHIPPED in v3.3.6** after three gates caught real defects the local suite could not: the git mode
was 100644 so CI's `./scripts/detectors/<name>.py` would never have executed it (the test reads the
mode GIT RECORDS, and the file was untracked during the full-suite run, so it passed truthfully);
and the CI-parity preflight refused on bandit B108 for the `/tmp/claude` literal — annotated as a
verified false positive, because B108 guards the WRITE side and this detector only rglobs and stats,
skipping symlinks, which is the CWE-377 vector itself.

**NEXT ACTION.** Observe one autonomous hourly fire in a session that did not run it by hand, and
confirm the state file carries the re-alert baseline across dispatcher-driven runs.

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
