"""Posture-grade computation for the janitor heartbeat.

Computes a single A-F letter grade summarising the security posture of
the current project based on the union of recent detector findings.
Surfaced at most once per LOCAL day (the cron's natural cadence is fast
enough that day-level granularity is plenty; finer granularity adds
noise without insight).

Grading scale (calibrated against real-world heartbeats)

  A  — 0 active CRITICAL, 0 active HIGH, ≤ 1 MAJOR
  B  — 0 CRITICAL,         ≤ 1 HIGH,     ≤ 3 MAJOR
  C  — ≤ 1 CRITICAL,       ≤ 2 HIGH,     ≤ 6 MAJOR
  D  — ≤ 2 CRITICAL,       ≤ 4 HIGH      or > 6 MAJOR
  F  —    > 2 CRITICAL  or > 4 HIGH

"Active" = surfaced by a detector in the last 24 h AND not suppressed
via .janitor.toml. Severity counts use the per-detector seen-files (the
janitor's own dedupe layer) so a single attack that surfaces across 3
detectors only counts once.

Returns a `PostureGrade` namedtuple with the letter + numeric score +
per-severity counts. The heartbeat emits ONE drift line per local day
with the grade.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import NamedTuple


class PostureGrade(NamedTuple):
    """A single grade snapshot for the heartbeat."""

    letter: str  # "A", "B", "C", "D", "F"
    score: int   # 0-100, 100 = perfect
    critical: int
    high: int
    major: int
    minor: int
    # OSV "MAL-*" advisories = known-MALICIOUS package versions
    # installed (worm self-propagation, infostealers, etc.). DISTINCT
    # from CVE-class findings: a CVE is "bug in legit package", a
    # MAL-* is "this version was published as malware". Treated as a
    # hard F regardless of count and surfaced separately so the user
    # cannot miss it. Source: supply-chain-hardening (sweep-D).
    mal_advisories: int = 0


_DEFAULT_WEIGHTS = {
    "CRITICAL": 35,
    "HIGH": 18,
    "MAJOR": 6,
    "MINOR": 1,
    # Each MAL-* counts as twice a CRITICAL when scoring: a known-
    # malicious version installed is strictly worse than an unfixed
    # CVE, and the numeric score should reflect that hierarchy.
    "MAL": 70,
}


def compute(
    critical: int = 0,
    high: int = 0,
    major: int = 0,
    minor: int = 0,
    mal_advisories: int = 0,
) -> PostureGrade:
    """Compute a posture grade from per-severity counts + OSV MAL-* count.

    Numeric score = 100 - weighted_sum(counts), clamped at 0.
    Letter is the LOWEST grade band the counts qualify for — i.e.
    the harshest reasonable read of the data so the user sees the
    worst signal first.

    Any non-zero `mal_advisories` count forces the letter to F
    regardless of the other counts — a known-malicious version
    installed is an emergency that the rest of the score must not mask.
    """
    deduction = (
        _DEFAULT_WEIGHTS["CRITICAL"] * critical
        + _DEFAULT_WEIGHTS["HIGH"] * high
        + _DEFAULT_WEIGHTS["MAJOR"] * major
        + _DEFAULT_WEIGHTS["MINOR"] * minor
        + _DEFAULT_WEIGHTS["MAL"] * mal_advisories
    )
    score = max(0, 100 - deduction)

    # MAL-* short-circuits to F — the canonical "known-malware installed"
    # state must never be confused with "merely many CVEs".
    if mal_advisories > 0:
        letter = "F"
    elif critical > 2 or high > 4:
        letter = "F"
    elif critical > 1 or high > 2 or major > 6:
        letter = "D"
    elif critical > 0 or high > 1 or major > 3:
        letter = "C"
    elif high > 0 or major > 1:
        letter = "B"
    else:
        letter = "A"
    return PostureGrade(
        letter, score, critical, high, major, minor, mal_advisories,
    )


def should_surface_today(stamp_file: Path) -> bool:
    """Return True iff today's local date has not yet been stamped.

    Used to enforce the "one posture line per local day" cadence — the
    grade is information-dense but repeating it every 5 min would be
    noise. The stamp file lives under the janitor's state dir so it's
    per-project and survives a heartbeat process restart.
    """
    today = _dt.date.today().isoformat()
    try:
        last = stamp_file.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        last = ""
    return last != today


def mark_surfaced_today(stamp_file: Path) -> None:
    """Stamp today's date so should_surface_today returns False for
    the rest of the day."""
    today = _dt.date.today().isoformat()
    stamp_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = stamp_file.with_suffix(stamp_file.suffix + f".tmp.{today}")
    tmp.write_text(today, encoding="utf-8")
    tmp.replace(stamp_file)


def format_drift_line(grade: PostureGrade) -> str:
    """Render the grade as a single heartbeat-friendly drift line."""
    parts = [
        f"posture: {grade.letter} (score {grade.score}/100)",
    ]
    # MAL-* advisories surface FIRST so the user cannot miss them.
    if grade.mal_advisories:
        parts.append(f"{grade.mal_advisories} OSV MAL-* (known-malicious)")
    if grade.critical:
        parts.append(f"{grade.critical} CRITICAL")
    if grade.high:
        parts.append(f"{grade.high} HIGH")
    if grade.major:
        parts.append(f"{grade.major} MAJOR")
    if grade.minor:
        parts.append(f"{grade.minor} MINOR")
    if grade.mal_advisories:
        suffix = (
            "EMERGENCY: a known-MALICIOUS package version is installed. "
            "Isolate the workstation (do NOT rotate tokens first — wiper / "
            "dead-man-switch risk on revoke), snapshot, then triage. "
            "See OSV.dev MAL-* advisory IDs in the supply-chain-watcher log."
        )
        return f"[posture-grade] {' / '.join(parts)} — {suffix}"
    if grade.letter == "A":
        suffix = "no active CRITICAL/HIGH findings — keep it green."
    elif grade.letter == "B":
        suffix = "minor friction; clean up to reach A."
    elif grade.letter == "C":
        suffix = "noticeable risk surface; address HIGH findings."
    elif grade.letter == "D":
        suffix = "significant risk; CRITICAL findings need attention now."
    else:  # F
        suffix = "untenable risk; STOP and triage CRITICAL findings before shipping."
    return f"[posture-grade] {' / '.join(parts)} — {suffix}"
