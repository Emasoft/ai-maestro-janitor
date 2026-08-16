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

THE CPU PERSISTENCE GATE (TRDD-8QSLYMGU): `ps %cpu` is a decaying average over the
process's LIFETIME, so a burst that already ENDED still reads high and alarmed twice in
one night on a process `top -l 2` put at 5.3% / 0.8%. A CPU finding is therefore only
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


def main() -> int:
    state.init_state()

    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED", True):
        return 0

    ps_text = _gather_ps_snapshot()
    seen = state.state_dir() / "system-daemon-runaway-seen.txt"
    streak_file = state.state_dir() / "system-daemon-runaway-streaks.json"
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

    if not reportable:
        # Nothing over the bar this beat — forget the dedupe key so a FUTURE runaway
        # (even by the same process/command) re-arms instead of staying deduped
        # against an episode that already cleared.
        dedupe.emit_forget(seen, "runaway")
        state.rotate_log_if_big(_LOG)
        return 0

    line = dr.format_drift_line(reportable, disk_danger, disk_free_pct, streaks=streaks)
    if line is None:  # pragma: no cover — unreachable when reportable is non-empty
        return 0

    emitted = dedupe.emit_once(seen, "runaway", line)
    if emitted is not None:
        print(emitted)
    state.rotate_log_if_big(_LOG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
