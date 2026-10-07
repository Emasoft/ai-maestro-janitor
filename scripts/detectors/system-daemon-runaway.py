#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""system-daemon-runaway — warn on a process RAM/CPU runaway + disk pressure
(TRDD-HK7IZ21Z, EHT/safety-net of TRDD-ZNN0UK5K).

THE GAP: TRDD-ZNN0UK5K fixed the janitor's OWN cause of a 39GB `fseventsd` runaway
(keepalive restage churn + test pollution). `memory-guard` (the daemon) only kills
JANITOR-OWNED runaways ("only janitor-owned runaways are killable — standing down"),
so a SYSTEM daemon (`fseventsd`, `mds`, `mds_stores`, `mdworker`) — or any OTHER
process — driven to a RAM/CPU runaway is INVISIBLE until it crashes the host. The
owner framed this as "the janitor **or some other process** is leaking", so this
detector watches the whole CLASS, whoever causes it, at ~4GB instead of 39GB.

READ-ONLY, ALERT-ONLY — this detector NEVER kills, signals, or otherwise touches any
process. Killing something a human depends on is exactly the harm a false positive
here would cause; the fix belongs to a human (or `memory-guard`, for the narrower
janitor-owned case) who can tell a real leak from a legitimately busy process.

THE self-match trap (why this is NOT `pgrep -f`/`ps | grep`): both scan the LIVE
process table, and the shell running the pipeline carries the search pattern in its
own argv — so the scan matches itself. This detector instead SNAPSHOTS `ps` to
memory/a file FIRST (a bare `ps -axo ...` argv, no pattern, no pipe, no shell) and
only THEN parses it — the snapshot predates the parser, so self-matching this
detector's own `uv run` invocation is structurally impossible. `parse_ps_rows` /
`classify_runaway` (scripts/lib/daemon_runaway.py) are pure functions over that
snapshot text, so the thresholds are provable against a captured fixture instead of
the live machine.

THE CPU PERSISTENCE GATE (TRDD-8QSLYMGU, corrected by TRDD-JEEQCHFG): `ps %cpu` is a
decaying average over UP TO A MINUTE of previous real time (`man ps`) — NOT over the
process's lifetime, as this comment claimed until 2026-08-16. One sample therefore
cannot separate a 60-second spike from sustained load; both read high while the window
is hot. Consecutive fires are 600 s apart, so their windows do not overlap and a CPU
finding is only
reported once it has held across consecutive fires, counted in
`system-daemon-runaway-streaks.json` (this file is the whole reason the detector keeps
state beyond dedupe). RSS findings are NOT gated — RSS is an instantaneous level and
the parent incident was an RSS finding, so gating it would delay the alarm that matters.

Opt-out: CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED=false (default enabled —
this is a safety net for host-crashing runaways, not a hygiene nag). Cadence ~600s
via the dispatch.py roster. Fail-open throughout: any error (no `ps`, unparseable
snapshot, unreadable disk stat) degrades to a silent no-op — a detector that cries
wolf on its own failures gets ignored, which is the same as not existing.

TEST SEAM: `JANITOR_PS_SNAPSHOT` (mirrors the same seam in `stale-index-lock.py` /
`git_utils.clear_stale_index_lock`) — when set (even to ""), its value is used
verbatim as the `ps` snapshot instead of spawning a real `ps`, so a test can drive
this detector deterministically regardless of what is actually running on the host.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import daemon_runaway as dr  # noqa: E402
import dedupe  # noqa: E402
import state  # noqa: E402

_LOG = "system-daemon-runaway"


def _gather_ps_snapshot() -> str | None:
    """A `ps -axo pid,ppid,rss,%cpu,comm` snapshot as TEXT, or None when it cannot be
    taken. Bare argv only — see the module docstring for why this must never become
    `pgrep`/`ps | grep`. `JANITOR_PS_SNAPSHOT` (test seam) short-circuits to the
    injected value, including an explicit empty string (a test asserting "no rows")."""
    injected = os.environ.get("JANITOR_PS_SNAPSHOT")
    if injected is not None:
        return injected
    proc = state.run_subprocess(
        ["ps", "-axo", "pid,ppid,rss,%cpu,comm"], timeout=10.0, detector_name=_LOG
    )
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout


def _disk_free_pct(path: str = "/") -> float | None:
    """The free-space percentage of the filesystem holding `path`, or None on any
    failure (no `statvfs` on this platform, permission error, a zero-block report).
    None must never be treated as "plenty of room" — `classify_runaway` already
    encodes that (a None disk reading never trips the disk-danger branch)."""
    try:
        st = os.statvfs(path)
    except (OSError, AttributeError):  # AttributeError: os.statvfs is POSIX-only
        return None
    if st.f_blocks == 0:
        return None
    return (st.f_bavail / st.f_blocks) * 100.0


def _coerce_float(raw: str | None, default: float) -> float:
    """Best-effort positive float from an env knob; junk/absent/non-positive falls
    back to `default` — a typo in a threshold must never crash the heartbeat or
    silently disarm the detector (e.g. a threshold of 0 would fire on every process)."""
    if not raw:
        return default
    try:
        val = float(raw.strip())
    except ValueError:
        return default
    return val if val > 0 else default


def _load_streaks(path: Path) -> dict[str, int]:
    """The persisted CPU streak map, or {} on ANY problem (missing, unreadable, not
    JSON, not an object). Entries are validated individually — a hand-edited or
    half-migrated file must degrade to "no history" (one extra fire before a real
    alarm) rather than crash a fail-open detector or, worse, feed a bogus count
    straight into the gate. `bool` is rejected explicitly because it IS an `int` in
    Python, so `True` would silently pass as a streak of 1."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: val
        for key, val in raw.items()
        if isinstance(key, str) and isinstance(val, int) and not isinstance(val, bool) and val > 0
    }


def _save_streaks(path: Path, streaks: dict[str, int]) -> None:
    """Persist the streak map atomically. A write failure is swallowed: the cost is one
    delayed alarm on the next fire, whereas raising here would take down the whole
    heartbeat over a detector's bookkeeping."""
    try:
        state.atomic_write(path, json.dumps(streaks, sort_keys=True))
    except OSError:
        pass

def _gather_cpu_times(pids: list[int]) -> dict[int, float]:
    """Cumulative CPU seconds per pid from `ps -p … -o pid=,time=`; {} on any failure.

    NLHVLGEP: the differenced burn needs `time`, which the main snapshot does not carry
    (adding a column there would reshape every captured snapshot the parser is tested on).
    A pid that already exited is simply absent from ps's output, so it gets no figure.
    """
    if not pids:
        return {}
    proc = state.run_subprocess(
        ["ps", "-p", ",".join(str(p) for p in pids), "-o", "pid=,time="],
        timeout=10.0, detector_name=_LOG,
    )
    if proc is None:
        return {}
    times: dict[int, float] = {}
    for line in proc.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit():
            secs = dr.parse_cpu_time(fields[1])
            if secs is not None:
                times[int(fields[0])] = secs
    return times


def _load_samples(path: Path) -> dict[str, object]:
    """The persisted `{key: [cpu_time_s, sampled_at_epoch]}` map, or {} on ANY problem.

    Values stay untyped on purpose: `dr.measured_burn` validates each entry's shape, so a
    stale or hand-edited entry degrades to "no delta" for that process only."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_samples(path: Path, samples: dict[str, list[float]]) -> None:
    """Persist the samples atomically; a write failure costs one fire's delta, nothing more."""
    try:
        state.atomic_write(path, json.dumps(samples, sort_keys=True))
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """True iff a process with `pid` currently exists (TRDD-JEEQCHFG box 2).

    `os.kill(pid, 0)` sends NO signal — signal 0 only probes existence + permission:
    success or `PermissionError` (the process exists but is not ours — still alive)
    mean alive; `ProcessLookupError` means gone. A malformed/absurd pid can never name a
    real runaway, so treat it as gone.

    Test seam: an injected `JANITOR_PS_SNAPSHOT` carries SYNTHETIC pids that do not exist
    on the host, so trust them (the same seam `_gather_ps_snapshot` reads) — otherwise
    every streak/emit e2e test would need a real runaway process. The filter's own logic
    is unit-tested against a captured snapshot via `dr.alive_findings`."""
    if os.environ.get("JANITOR_PS_SNAPSHOT") is not None:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OverflowError, ValueError, OSError):
        return False
    return True


def main() -> int:
    state.init_state()

    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED", True):
        return 0

    ps_text = _gather_ps_snapshot()
    seen = state.state_dir() / "system-daemon-runaway-seen.txt"
    streak_file = state.state_dir() / "system-daemon-runaway-streaks.json"
    sample_file = state.state_dir() / "system-daemon-runaway-cpu-samples.json"
    if ps_text is None:
        # Could not gather a snapshot at all — fail open (no findings), and forget any
        # prior dedupe key so a genuine runaway re-emits once `ps` is available again
        # rather than staying silently deduped against a stale bucket.
        #
        # The streak map is deliberately left UNTOUCHED here: a failed snapshot is not
        # evidence that a burst ended, and clearing it would reset a legitimate streak
        # on a transient `ps` hiccup, delaying a real alarm. Carrying it costs at most
        # one fire's worth of staleness, which errs toward alarming — the correct
        # direction for a safety net.
        dedupe.emit_forget(seen, "runaway")
        return 0

    rows = dr.parse_ps_rows(ps_text)
    # `command` is an OS-reported string (ultimately from `ps`, not a hardcoded
    # constant) — sanitize it PER-FIELD, here, before it ever reaches a Finding or a
    # drift line. Sanitizing the WHOLE assembled line instead (as done further down in
    # an earlier draft) also defangs this detector's OWN `[system-daemon-runaway]`
    # marker prefix, which is not untrusted — that broke the fixed-prefix contract
    # every other detector's drift line relies on.
    rows = [
        dr.ProcRow(pid=r.pid, ppid=r.ppid, rss_mb=r.rss_mb, pcpu=r.pcpu,
                   command=state.sanitize_for_drift_line(r.command))
        for r in rows
    ]

    rss_threshold_mb = _coerce_float(
        os.environ.get("CLAUDE_PLUGIN_OPTION_RUNAWAY_RSS_MB"), 4096.0
    )
    cpu_threshold_pct = _coerce_float(
        os.environ.get("CLAUDE_PLUGIN_OPTION_RUNAWAY_CPU_PCT"), 90.0
    )
    disk_danger_free_pct = _coerce_float(
        os.environ.get("CLAUDE_PLUGIN_OPTION_RUNAWAY_DISK_DANGER_FREE_PCT"), 5.0
    )

    disk_free_pct = _disk_free_pct("/")
    findings, disk_danger = dr.classify_runaway(
        rows,
        disk_free_pct,
        rss_threshold_mb=rss_threshold_mb,
        disk_danger_free_pct=disk_danger_free_pct,
        cpu_threshold_pct=cpu_threshold_pct,
    )

    # Gate the CPU findings on persistence (RSS passes straight through) and persist the
    # new streak map UNCONDITIONALLY — including when `reportable` is empty. A CPU
    # finding on its first fire is not reported but MUST be remembered, or the streak
    # can never reach the minimum and a genuinely sustained burn would stay silent
    # forever. Writing here also DROPS the keys absent from this snapshot, which is what
    # makes an ended burst stop counting instead of resuming its streak days later.
    reportable, streaks = dr.sustained_findings(findings, _load_streaks(streak_file))
    _save_streaks(streak_file, streaks)


    # NLHVLGEP: difference cumulative CPU time against the previous fire's sample so the
    # alarm can report the MEASURED burn. REPORT ONLY: `reportable` above was decided by
    # the unchanged %cpu bar and streak gate; nothing below can add or drop a finding.
    # Like the streaks, samples are rewritten every fire so an ended burst is forgotten.
    now = time.time()
    cpu_findings = {dr.finding_key(f): f for f in findings if f.kind == "cpu"}
    cpu_times = _gather_cpu_times([f.pid for f in cpu_findings.values()])
    prior_samples = _load_samples(sample_file)
    measured: dict[str, tuple[float, float]] = {}
    samples: dict[str, list[float]] = {}
    for key, f in cpu_findings.items():
        cpu_s = cpu_times.get(f.pid)
        if cpu_s is None:
            continue
        samples[key] = [cpu_s, now]
        burn = dr.measured_burn(prior_samples.get(key), cpu_s, now)
        if burn is not None:
            measured[key] = burn
    _save_samples(sample_file, samples)

    if not reportable:
        # Nothing over the bar this beat — forget the dedupe key so a FUTURE runaway
        # (even by the same process/command) re-arms instead of staying deduped
        # against an episode that already cleared.
        dedupe.emit_forget(seen, "runaway")
        state.rotate_log_if_big(_LOG)
        return 0

    # Re-validate at REPORT time (TRDD-JEEQCHFG box 2): the `ps` snapshot above names a
    # pid that can EXIT before we emit — a peer observed an alarm naming a dead pid,
    # which is a defect under any metric. Drop findings whose process is already gone.
    # The streak map is left as saved: a pid absent from the NEXT snapshot drops out
    # normally, and a best-effort emit-time probe must not rewrite persisted state.
    reportable = dr.alive_findings(reportable, _pid_alive)
    if not reportable:
        # Every over-the-bar process exited between snapshot and emit — same handling as
        # nothing over the bar: forget the dedupe key so a genuine future runaway re-arms.
        dedupe.emit_forget(seen, "runaway")
        state.rotate_log_if_big(_LOG)
        return 0

    line = dr.format_drift_line(reportable, disk_danger, disk_free_pct, streaks=streaks, measured=measured)
    if line is None:  # pragma: no cover — unreachable when reportable is non-empty
        return 0

    emitted = dedupe.emit_once(seen, "runaway", line)
    if emitted is not None:
        print(emitted)
    state.rotate_log_if_big(_LOG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
