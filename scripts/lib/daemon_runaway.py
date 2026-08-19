"""Pure decision layer for the system-daemon runaway detector (TRDD-HK7IZ21Z).

The parent incident (TRDD-ZNN0UK5K) was the janitor's OWN keepalive churn driving
`fseventsd` to 39 GB RSS before anything noticed — `memory-guard` only kills
JANITOR-OWNED runaways, so a SYSTEM daemon (or any other process) doing the same
thing is invisible until it crashes the host. This module is the safety net's pure
"is this process/host state dangerous?" verdict: no subprocess, no filesystem I/O,
so the thresholds are provable against a captured `ps` snapshot instead of the live
machine (a real runaway is, by definition, not something a test suite should have to
reproduce).

`parse_ps_rows` turns `ps -axo pid,ppid,rss,%cpu,comm` TEXT into rows; `classify_runaway`
turns rows + a disk-free reading into `Finding`s; `sustained_findings` then drops the
CPU findings that have not held across consecutive fires. All three are pure functions
of their inputs — the detector script owns every side effect (spawning `ps`, reading
`os.statvfs`, printing, dedup state, and PERSISTING the streak map `sustained_findings`
returns).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# The FS-event + Spotlight class the parent incident belongs to (TRDD-ZNN0UK5K was
# `fseventsd`). Membership here only changes a finding's WORDING (a watched name is
# called out explicitly as "a known FS-churn daemon") — it never changes whether a
# process crosses the threshold. The whole point of this detector is to catch the
# CLASS ("the janitor or some other process is leaking" — the parent TRDD's framing),
# so an unlisted process over the bar is reported exactly the same as a listed one.
KNOWN_WATCHLIST: frozenset[str] = frozenset(
    {"fseventsd", "mds", "mds_stores", "mdworker", "mdworker_shared"}
)


@dataclass(frozen=True)
class ProcRow:
    """One parsed row of a `ps -axo pid,ppid,rss,%cpu,comm` snapshot."""

    pid: int
    ppid: int
    rss_mb: float
    pcpu: float
    command: str


@dataclass(frozen=True)
class Finding:
    """A single process (or the host disk) crossing a runaway threshold."""

    pid: int
    command: str
    rss_mb: float
    pcpu: float
    kind: str  # "rss" | "cpu"
    is_watched: bool  # True iff `command`'s basename is in KNOWN_WATCHLIST


def _basename(command: str) -> str:
    """The last path segment of a `ps` COMMAND field — `/usr/sbin/fseventsd` and
    `fseventsd` must classify identically against KNOWN_WATCHLIST."""
    return command.rsplit("/", 1)[-1].strip()


def parse_ps_rows(ps_text: str) -> list[ProcRow]:
    """Parse `ps -axo pid,ppid,rss,%cpu,comm` TEXT into `ProcRow`s.

    Fail-soft PER LINE: an unparseable line (the header row, a truncated line, a
    process whose command is empty) is skipped rather than raising — a single
    malformed row must never crash a fail-open detector. `comm` (not `command`) is
    a single token with no embedded spaces, so a plain `split(None, 4)` — at most 5
    fields — is exact; a wider `args`-style column would need different parsing.
    """
    rows: list[ProcRow] = []
    for line in ps_text.splitlines():
        fields = line.split(None, 4)
        if len(fields) < 5:
            continue
        try:
            pid = int(fields[0])
            ppid = int(fields[1])
            rss_kb = float(fields[2])
            pcpu = float(fields[3])
        except ValueError:
            continue  # header row ("PID PPID RSS %CPU COMM") or other garbage
        command = fields[4].strip()
        if not command:
            continue
        rows.append(ProcRow(pid=pid, ppid=ppid, rss_mb=rss_kb / 1024.0, pcpu=pcpu, command=command))
    return rows


def classify_runaway(
    rows: list[ProcRow],
    disk_free_pct: float | None,
    rss_threshold_mb: float = 4096.0,
    disk_danger_free_pct: float = 5.0,
    cpu_threshold_pct: float = 90.0,
) -> tuple[list[Finding], bool]:
    """PURE verdict: which processes are runaway, and is the disk itself dangerously full?

    `disk_free_pct` is the CURRENT free-space percentage (None when it could not be
    measured — never treated as "plenty of room"). `disk_danger_free_pct` is the
    threshold BELOW which the disk counts as dangerously full (default 5.0, i.e. the
    disk is in the danger zone once free space drops under 5% — equivalently, more
    than 95% full, the level the parent incident's fseventsd amplification needed).

    A row is an RSS finding when it exceeds `rss_threshold_mb`; else a CPU finding
    when it exceeds `cpu_threshold_pct`. RSS takes priority — a process ballooning
    in memory is the fseventsd-class failure this detector exists for, and a busy-but-
    bounded process (e.g. a compiler) can legitimately peg CPU without being a leak.
    Findings sort by `rss_mb` descending so the detector's headline is always the
    worst offender. Returns `(findings, disk_danger)` — disk pressure is reported
    separately because it AMPLIFIES a process finding rather than being one itself
    (a full disk with no runaway process is a different problem this detector does
    not claim to diagnose).
    """
    findings: list[Finding] = []
    for row in rows:
        base = _basename(row.command)
        watched = base in KNOWN_WATCHLIST
        if row.rss_mb > rss_threshold_mb:
            findings.append(Finding(row.pid, base, row.rss_mb, row.pcpu, "rss", watched))
        elif row.pcpu > cpu_threshold_pct:
            findings.append(Finding(row.pid, base, row.rss_mb, row.pcpu, "cpu", watched))
    findings.sort(key=lambda f: f.rss_mb, reverse=True)
    disk_danger = disk_free_pct is not None and disk_free_pct < disk_danger_free_pct
    return findings, disk_danger


def finding_key(finding: Finding) -> str:
    """The identity a CPU streak is counted against: pid AND command, never pid alone.

    The OS recycles pids, so a streak keyed on the number alone could be inherited by
    an unrelated process that happened to reuse it — which would alarm on that new
    process's very FIRST high sample, precisely the single-sample bug the streak
    exists to prevent.
    """
    return f"{finding.pid}:{finding.command}"


def sustained_findings(
    findings: list[Finding],
    prior_streaks: dict[str, int],
    min_streak: int = 2,
) -> tuple[list[Finding], dict[str, int]]:
    """PURE gate: drop CPU findings that have not held across `min_streak` fires.

    WHY only CPU: on macOS `ps %cpu` is a decaying average over UP TO A MINUTE of
    previous real time (`man ps`), not an instantaneous reading. So ONE sample cannot
    tell a 60-second spike from sustained load — both present the same number while the
    window is hot. It is NOT a lifetime average: a burst that ended decays away within
    about a minute (measured 2026-08-16: a pid went 100.2 -> 5.0 in minutes, and %cpu
    differed from time/etime by ~1800x on another).

    That correction matters for what this gate is FOR. Consecutive fires are 600 s
    apart (`dispatch.py`), so two fires sample windows that do not overlap at all —
    genuinely independent samples, not one smoothed window read twice. Requiring the
    condition to hold across them is therefore a real test of PERSISTENCE, and it is
    what separates a minute-long spike from a process that is still burning ten minutes
    later. Raising the threshold instead would silence real slow burns without fixing
    the spikes.

    HISTORICAL, and do not restore it: this docstring used to claim %cpu was a lifetime
    average, so "a burst that already ENDED keeps a high number". That mechanism was
    invented, not measured, and TRDD-8QSLYMGU was filed on it. The `top -l 2`
    cross-checks that appeared to confirm it (5.3%, 0.8%) were never like-for-like — a
    ~1-second delta against a ~1-minute average — so they refuted nothing. Superseded by
    TRDD-JEEQCHFG. On the corrected reading, some alarms the fleet dismissed as false
    positives were probably CORRECT.

    WHY NOT RSS — the single most important line here: `ps` RSS is an instantaneous
    LEVEL (a process at 5 GB is at 5 GB right now, with no history baked in), so it
    needs no persistence to be interpretable. RSS findings therefore pass through
    UNGATED, deliberately: the incident this detector exists for (TRDD-ZNN0UK5K,
    fseventsd at 39 GB) was an RSS finding, and the tempting symmetry of gating both
    kinds would have delayed the one alarm that mattered by a full cadence.

    Returns `(reportable, streaks)`. `streaks` counts ONLY the CPU findings present in
    THIS call — a key absent from `findings` is DROPPED rather than carried at its old
    count, which is what makes an ended burst stop counting instead of resuming its
    streak days later. The caller MUST persist `streaks` even when `reportable` is
    empty, or a first-fire CPU finding is forgotten and the streak can never reach
    `min_streak` at all.
    """
    reportable: list[Finding] = []
    streaks: dict[str, int] = {}
    for finding in findings:
        if finding.kind != "cpu":
            reportable.append(finding)
            continue
        key = finding_key(finding)
        streak = prior_streaks.get(key, 0) + 1
        streaks[key] = streak
        if streak >= min_streak:
            reportable.append(finding)
    return reportable, streaks


def alive_findings(
    findings: list[Finding], pid_alive: Callable[[int], bool]
) -> list[Finding]:
    """Drop findings whose pid no longer exists at REPORT time (TRDD-JEEQCHFG box 2).

    A `ps` snapshot names a pid that can EXIT before the alarm is emitted — a peer
    observed an alarm naming a pid that no longer existed, which is a defect under any
    metric. Re-check each finding's pid against a caller-supplied liveness probe (the
    detector passes an `os.kill(pid, 0)` existence check; a test passes a fake) and keep
    only the still-live ones. Best-effort by nature — the pid can still exit
    microseconds later — but it removes the observed case where the process was ALREADY
    gone when the line was printed. PURE: the syscall lives in the caller's `pid_alive`,
    so this stays testable against a captured snapshot like the rest of the module.
    """
    return [f for f in findings if pid_alive(f.pid)]


def format_drift_line(
    findings: list[Finding],
    disk_danger: bool,
    disk_free_pct: float | None,
    streaks: dict[str, int] | None = None,
) -> str | None:
    """Render ONE concise drift line for the worst finding, or None when there is
    nothing to report. Pure formatting — no truncation/sanitization here (the caller
    still runs it through `state.sanitize_for_drift_line` because `command` ultimately
    derives from an OS-reported string, not a hardcoded constant).

    `streaks` is `sustained_findings`' map; when it carries the worst finding's key the
    CPU branch names how many consecutive checks the condition held for.
    """
    if not findings:
        return None
    worst = findings[0]
    if worst.kind == "rss":
        metric = f"RSS {worst.rss_mb / 1024.0:.1f}GB"
    else:
        # NAME THE WINDOW. A reader who cross-checks a "CPU 161%" alarm with `top` and
        # sees 0.8% otherwise concludes the janitor is lying — which is exactly the
        # reaction the ungated version produced. Both numbers are correct; they measure
        # different things, and only the alarm can say which one it reported.
        held = (streaks or {}).get(finding_key(worst))
        # MEASURED 2026-08-16, correcting a FALSE claim this line shipped from 3.3.9:
        # it said "a lifetime average, not a live sample". `man ps` says %cpu is "a
        # decaying average over up to a minute of previous (real) time", and three
        # measurements agree with the man page against the old text — %cpu != time/etime
        # (99.0% vs 0.055% on one pid, ~1800x apart); %cpu MATCHES consumption computed
        # from cpu_time deltas; and %cpu DECAYS (100.2 -> 5.0 within minutes, which a
        # 13-day denominator forbids). The old wording also told the reader the number
        # was meaningless, which is a reliable way to get the next REAL runaway dismissed.
        window = "a ~1-minute decaying average; a live delta may differ on a bursty process"
        if held is not None and held > 1:
            window += f"; over the bar on {held} consecutive checks"
        metric = f"CPU {worst.pcpu:.0f}% ({window})"
    watched_txt = " (a known FS-churn/Spotlight daemon)" if worst.is_watched else ""
    extra = f" — {len(findings) - 1} more process(es) also over threshold" if len(findings) > 1 else ""
    disk_txt = ""
    if disk_danger and disk_free_pct is not None:
        disk_txt = f" + disk {100.0 - disk_free_pct:.0f}% full"
        # Only the RSS branch claims disk pressure AMPLIFIES the finding — that is the
        # parent incident's actual mechanism (FS churn on a near-full disk ballooning
        # RSS). A near-full disk does not make a CPU average worse, and pairing the two
        # manufactured a compound emergency out of two independent non-events, both of
        # which had been true and harmless all night (TRDD-8QSLYMGU). For CPU the disk
        # is REPORTED, never escalated on.
        if worst.kind == "rss":
            disk_txt += " — likely the amplifier turning FS churn into a balloon"
    return (
        f"[system-daemon-runaway] {worst.command} (pid {worst.pid}) {metric}{watched_txt}"
        f"{disk_txt}{extra} — a process RAM/CPU runaway; investigate before it exhausts the host."
    )
