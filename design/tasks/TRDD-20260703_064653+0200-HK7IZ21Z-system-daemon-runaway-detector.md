---
trdd-id: HK7IZ21Z
title: Failure-class detector — warn on fseventsd/mds/any process RAM-CPU runaway + disk pressure
column: complete
created: 2026-07-03T06:46:53+0200
updated: 2026-08-14T20:07:00+0200
implementation-commits: [fe2c68e1]
current-owner: janitor-session
assignee: null
priority: 3
severity: MEDIUM
effort: M
labels: [detector, observability, fsevents, oom]
task-type: feature
parent-trdd: TRDD-ZNN0UK5K
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
review-requirements: []
implementation-commits: []
---

# TRDD-HK7IZ21Z — system-daemon runaway detector (the fseventsd-class safety net)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-05

**2026-08-05 board triage (`backburner → todo`):** this card's own NEXT ACTION was "promote
from backburner when the parent's release ships." Verified, not assumed: the parent
TRDD-ZNN0UK5K is `column: complete`, and its fix commit `33ef7eb` is an ancestor of `HEAD`
and contained in every tag from `v1.0.0` through `v2.3.0` (`git merge-base --is-ancestor` +
`git tag --contains`, both run fresh). Grepped `scripts/` and `tests/` for
`system-daemon-runaway` / `system_daemon_runaway` — nothing exists yet, so this is real,
unstarted work, not a done-but-unclosed card. Moved to `todo` (ready to pull), not `dev`
(nobody is building it right now). The design below is unchanged and still the plan to build.

## ⏵ STATE (original) — 2026-07-03

- **Parent:** TRDD-ZNN0UK5K fixed the janitor's OWN cause of a 39GB fseventsd
  runaway (keepalive restage churn + test pollution — commit 33ef7eb, rechecked
  4×). This child is the EHT/safety-net: the USER framed it as "the janitor **or
  some other process** is leaking" — so detect the whole CLASS early, whoever
  causes it, at ~4GB instead of 39GB.
- **Gap it closes:** `memory-guard` (daemon) only kills **janitor-owned**
  runaways ("only janitor-owned runaways are killable — standing down"), so a
  SYSTEM daemon (`fseventsd`, `mds`, `mds_stores`, `mdworker`) — or any process —
  driven to a RAM/CPU runaway is INVISIBLE until it crashes the host. There is no
  alert.
- **Design (a per-session heartbeat detector — read-only alert, like
  `token-usage-anomaly`/`window-burn-rate` which already read machine-wide state
  from a per-session detector; alert-only ⇒ no scope-invariant violation):**
  1. `scripts/detectors/system-daemon-runaway.py` — snapshot `ps -axo
     pid,ppid,rss,%cpu,comm` to a FILE then parse the file (NEVER `pgrep`/`ps|grep`
     — self-match). Flag any process with `RSS > CLAUDE_PLUGIN_OPTION_RUNAWAY_RSS_MB`
     (default 4096) OR sustained `%cpu` over a threshold; specifically watch
     `fseventsd`/`mds*`/`mdworker*` (the FS-event + Spotlight class) but report ANY
     process over the bar. ALSO read disk free % (`os.statvfs("/")`); a >95%-full
     disk is the amplifier that turns FS churn into an fseventsd balloon.
  2. Pure lib `classify_runaway(rows, disk_free_pct, rss_threshold_mb,
     disk_danger_pct) -> list[Finding]` so tests need no live ps/mocks.
  3. Emit ONE concise, `emit_once`-deduped drift line, e.g.
     `[system-daemon-runaway] fseventsd RSS 39.0GB (>4GB) + disk 99% full — an
     FS-event storm; a process is churning the filesystem`.
  4. Opt-out `CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED`; cadence ~600s;
     fail-open. Wire into dispatch `_DETECTORS`.
- **Derived tasks:** (a) `tests/test_system_daemon_runaway.py` (over-RSS flagged,
  under-RSS silent, disk-pressure, fseventsd-named highlight, disabled→noop, ps
  parse); (b) CLAUDE.md observability-group + detector-roster update; (c) consider
  a follow-on that, on repeated alert, points at `/janitor-token-attribution`-style
  culprit identification (which process is creating the unique-path churn).
- **Reuse:** `state` (ps-snapshot-to-file, atomic_write), `dedupe.emit_once`,
  `run_subprocess`, `posture`/drift-line format, `security_helpers.sanitize_for_drift_line`.
- **NEXT ACTION:** promote from backburner when the parent's release ships; then
  implement detector + pure lib + tests + dispatch wiring + docs; ruff/pyright +
  `pytest tests/test_system_daemon_runaway.py`; ship in a release.

## Acceptance — added 2026-08-14 (the card shipped with none)

This card originally carried NO acceptance boxes, which is its own hazard: a card
with zero boxes is indistinguishable from a fully-satisfied one under any
box-counting audit. These record what was actually built and verified in
`fe2c68e1`.

- [x] Pure classifier `scripts/lib/daemon_runaway.py` takes parsed input, so tests
      need no live `ps` and no mocks of the thing under test.
- [x] Detector `scripts/detectors/system-daemon-runaway.py` SNAPSHOTS `ps` to a
      file and parses the file — never `pgrep -f` / `ps | grep`, whose pipeline
      shell carries the pattern in its own argv and so matches ITSELF. A runaway
      detector that matches its own scan reports a phantom leak every run.
      Pinned by `test_does_not_match_its_own_scanning_process`.
- [x] READ-ONLY and ALERT-ONLY: it never kills, signals, or remediates. Killing a
      process a human depends on is the harm it exists to prevent.
- [x] Fail-open on every error path (no `ps`, unparseable output, unreadable disk
      stats) — silence, never a crash and never a false alarm; tests cover those
      paths, not only the happy one.
- [x] Thresholds RSS>4096MB / CPU>90% / disk-free<5%, all env-overridable;
      `emit_once`-deduped drift line naming the worst offender.
- [x] Wired into `dispatch.py::_DETECTORS` at 600s, default ON, opt-out
      `CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED=false`.
- [x] Gates: 14 passed, ruff clean, mypy clean over 484 source files.
- [x] **Derived task (b), the detector-roster update — HANDLED, and it surfaced far
      more than this card's own addition.** Checking whether the roster named this
      detector revealed the page documented **39** detectors while `dispatch.py`
      registers **72** — stale by 33, nearly half the fleet undocumented. The COUNT
      is corrected on `janitor-detector-and-hook-roster` via the supersede protocol
      (old figure preserved as a dated `SUPERSEDED BODY`, never deleted), and the
      remaining grouped-list reconciliation is split out as **TRDD-IEW2K659** rather
      than absorbed here — documenting 33 detectors is a curator pass, not part of
      shipping one detector.
