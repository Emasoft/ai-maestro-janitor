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
turns rows + a disk-free reading into `Finding`s. Both are pure functions of their
inputs — the detector script owns every side effect (spawning `ps`, reading
`os.statvfs`, printing, dedup state).
"""

from __future__ import annotations

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


def format_drift_line(findings: list[Finding], disk_danger: bool, disk_free_pct: float | None) -> str | None:
    """Render ONE concise drift line for the worst finding, or None when there is
    nothing to report. Pure formatting — no truncation/sanitization here (the caller
    still runs it through `state.sanitize_for_drift_line` because `command` ultimately
    derives from an OS-reported string, not a hardcoded constant)."""
    if not findings:
        return None
    worst = findings[0]
    if worst.kind == "rss":
        metric = f"RSS {worst.rss_mb / 1024.0:.1f}GB"
    else:
        metric = f"CPU {worst.pcpu:.0f}%"
    watched_txt = " (a known FS-churn/Spotlight daemon)" if worst.is_watched else ""
    extra = f" — {len(findings) - 1} more process(es) also over threshold" if len(findings) > 1 else ""
    disk_txt = ""
    if disk_danger and disk_free_pct is not None:
        disk_txt = f" + disk {100.0 - disk_free_pct:.0f}% full — likely the amplifier turning FS churn into a balloon"
    return (
        f"[system-daemon-runaway] {worst.command} (pid {worst.pid}) {metric}{watched_txt}"
        f"{disk_txt}{extra} — a process RAM/CPU runaway; investigate before it exhausts the host."
    )
