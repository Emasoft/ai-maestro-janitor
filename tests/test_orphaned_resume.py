"""Tests for the orphaned-resume-flag decision layer (issue #125).

An unconsumed `resume-after-compact.flag` is the janitor's own silent failure: a compaction
recorded a resume target that no heartbeat ever delivered. Everything here is PURE or
filesystem-local (tmp_path) — no process scanning, because the session that needs waking is
by definition the one with no process to find.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "lib"))

import orphaned_resume as orf  # noqa: E402

_NOW = 1_800_000_000


def _project(tmp: Path, name: str, *, flag_age_s: int | None, cron: str | None) -> Path:
    """A project root with an optional resume flag of a given age."""
    root = tmp / name
    state = root / ".janitor" / "state"
    state.mkdir(parents=True, exist_ok=True)
    if flag_age_s is not None:
        (state / "resume-after-compact.flag").write_text("1", encoding="utf-8")
        (state / "resume-after-compact.ts").write_text(str(_NOW - flag_age_s), encoding="utf-8")
    if cron is not None:
        (state / "armed-cadence.cron").write_text(cron, encoding="utf-8")
    return root


def _harness_dir(projects_root: Path, slug: str, cwd: str) -> None:
    """A harness per-project dir whose newest transcript carries `cwd`."""
    d = projects_root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.jsonl").write_text(
        json.dumps({"type": "user", "cwd": cwd}) + "\n", encoding="utf-8"
    )


# ── cadence → staleness window ───────────────────────────────────────────────


def test_cadence_seconds_reads_only_the_minute_step_form():
    """`*/N` is the only shape the janitor arms; anything else is honestly unknown."""
    assert orf.cadence_seconds("*/5 * * * *") == 300
    assert orf.cadence_seconds("*/30 * * * *") == 1800
    assert orf.cadence_seconds("") is None
    assert orf.cadence_seconds("0 9 * * *") is None      # a fixed-hour cron, not a step
    assert orf.cadence_seconds("*/0 * * * *") is None    # nonsense step
    assert orf.cadence_seconds("*/90 * * * *") is None   # >60 is not a minute step


def test_stale_window_scales_with_the_projects_OWN_cadence():
    """A `*/5` project is late after 15 min; a `*/30` one is not until 90.

    Using one global window would either nag the fast project or let the slow one rot —
    3 fires is a pattern at whatever rate that project actually runs.
    """
    assert orf.stale_window("*/5 * * * *") == 900
    assert orf.stale_window("*/30 * * * *") == 5400
    # Unknown cadence falls back rather than inventing a period from a cron it cannot read.
    assert orf.stale_window("") == orf.DEFAULT_STALE_SECONDS
    assert orf.stale_window("0 9 * * *") == orf.DEFAULT_STALE_SECONDS


def test_is_orphaned_needs_a_flag_and_enough_age():
    """No flag is never a finding; a young flag is a fire in flight, not a failure."""
    assert not orf.is_orphaned(None, "*/5 * * * *")     # no flag at all
    assert not orf.is_orphaned(300, "*/5 * * * *")      # 1 fire — a hiccup
    assert not orf.is_orphaned(899, "*/5 * * * *")      # just under 3 fires
    assert orf.is_orphaned(900, "*/5 * * * *")          # 3 fires — a pattern
    assert orf.is_orphaned(86400, "")                   # unknown cadence, clearly dead


# ── flag age ─────────────────────────────────────────────────────────────────


def test_flag_age_prefers_the_ts_sidecar_over_mtime(tmp_path):
    """The `.ts` sidecar is written BEFORE the flag, so it cannot be newer — and unlike
    mtime it survives a copy/checkout that would otherwise reset the age to zero."""
    root = _project(tmp_path, "p", flag_age_s=7200, cron="*/5 * * * *")
    assert orf.flag_age(root / ".janitor" / "state", now=_NOW) == 7200


def test_flag_age_is_None_without_a_flag(tmp_path):
    root = _project(tmp_path, "p", flag_age_s=None, cron="*/5 * * * *")
    assert orf.flag_age(root / ".janitor" / "state", now=_NOW) is None


def test_flag_age_falls_back_to_mtime_when_the_sidecar_is_garbage(tmp_path):
    """A corrupt sidecar must not hide a real orphan — degrade to mtime, never to None."""
    root = _project(tmp_path, "p", flag_age_s=100, cron=None)
    (root / ".janitor" / "state" / "resume-after-compact.ts").write_text("not-a-number")
    assert orf.flag_age(root / ".janitor" / "state", now=_NOW) is not None


# ── root discovery ───────────────────────────────────────────────────────────


def test_roots_come_from_the_transcript_cwd_not_the_harness_SLUG(tmp_path):
    """The slug is lossy and must not be reverse-engineered.

    `~/.claude/projects/<slug>` is the abs path with every non-alphanumeric char dashed, so
    `/a/b-c` and `/a-b/c` produce the SAME slug — un-reversible. The transcript's own `cwd`
    is authoritative, and using it is also why this found a project living outside the
    obvious workspace tree that a `find ~/Code` sweep missed entirely.
    """
    projects = tmp_path / "projects"
    _harness_dir(projects, "-Users-x-Code-alpha", "/Users/x/Code/alpha")
    _harness_dir(projects, "-Users-x-other-place-beta", "/Users/x/other/place/beta")

    assert orf.known_project_roots(projects) == [
        "/Users/x/Code/alpha",
        "/Users/x/other/place/beta",
    ]


def test_root_discovery_survives_junk_dirs(tmp_path):
    """An empty dir, a dir with no transcript, and an unparseable line are all skipped —
    a scan that dies on one bad directory reports nothing about the other forty-three."""
    projects = tmp_path / "projects"
    (projects / "empty").mkdir(parents=True)
    d = projects / "broken"
    d.mkdir(parents=True)
    (d / "session.jsonl").write_text("{ not json\n", encoding="utf-8")
    _harness_dir(projects, "good", "/Users/x/good")

    assert orf.known_project_roots(projects) == ["/Users/x/good"]


# ── end-to-end scan ──────────────────────────────────────────────────────────


def test_scan_finds_only_orphans_and_orders_worst_first(tmp_path):
    """The oldest leads, because that is the session that has been dead longest."""
    projects = tmp_path / "projects"
    code = tmp_path / "code"

    old = _project(code, "very-dead", flag_age_s=26 * 86400, cron=None)
    mid = _project(code, "dead", flag_age_s=6 * 86400, cron="*/15 * * * *")
    young = _project(code, "in-flight", flag_age_s=60, cron="*/5 * * * *")   # 1 fire — fine
    none = _project(code, "healthy", flag_age_s=None, cron="*/5 * * * *")

    for p in (old, mid, young, none):
        _harness_dir(projects, p.name, str(p))

    found = orf.scan(projects, now=_NOW)

    assert [f["root"] for f in found] == [str(old), str(mid)]
    assert found[0]["age_s"] > found[1]["age_s"]


def test_format_finding_names_no_other_project():
    """The message carries the AGE and the CADENCE, never a project name or path.

    It is written into the AFFECTED project's own ledger, so naming a project inside it
    would put one project's identity into another's surface — the per-project channeling
    invariant (TRDD-X92VBFNF) that keeps an automatic surface carrying only its own data.
    """
    msg = orf.format_finding(6 * 86400, "*/15 * * * *")

    assert "6.0d" in msg and "*/15" in msg
    assert "/Users/" not in msg
    assert "janitor-arm" in msg          # actionable: says what to actually do


def test_format_finding_says_never_armed_when_there_is_no_cadence():
    """'(none)' would read as a bug in the detector; 'never armed' names the real cause."""
    assert "never armed" in orf.format_finding(99999, "")


def test_project_slug_keeps_the_user_name_out_of_logs():
    """Logs are read by humans AND agents; an absolute path leaks the machine's user."""
    assert orf.project_slug("/Users/someone/Code/AI-MAESTRO/thing") == "thing"
    assert orf.project_slug("/Users/someone/Code/thing/") == "thing"


# ── end-to-end: the ledger write is day-bucketed, like the drift line ─────────

_DETECTOR = _HERE.parent / "scripts" / "detectors" / "orphaned-resume-flag.py"


def _run_detector(home: Path, project: Path) -> str:
    import os
    import subprocess

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "orphansess"
    env.pop("CLAUDE_PLUGIN_OPTION_ORPHANED_RESUME_INTERVAL", None)
    res = subprocess.run(
        [sys.executable, str(_DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    # A detector that exits non-zero is logged by dispatch as a failure — never acceptable
    # on the heartbeat path, so surface it loudly instead of asserting on stdout alone.
    if res.returncode != 0:
        raise AssertionError(f"detector exited {res.returncode}; stderr:\n{res.stderr}")
    return res.stdout


def _age_from_real_now(root: Path, age_s: int) -> Path:
    """Re-stamp a fixture flag against the REAL clock.

    `_project` writes its `.ts` relative to the frozen `_NOW`, which the pure tests inject.
    The DETECTOR reads `time.time()` instead, and `_NOW` (2027) is in the future — so a
    fixture built for the pure tests yields a NEGATIVE age end-to-end and nothing is ever
    orphaned. That silence is indistinguishable from a working dedupe, which is exactly how
    a test like this passes while proving nothing.
    """
    import time as _t

    (root / ".janitor" / "state" / "resume-after-compact.ts").write_text(
        str(int(_t.time()) - age_s), encoding="utf-8"
    )
    return root


def _ledger_lines(project: Path) -> list[str]:
    p = project / ".janitor" / "state" / "findings-ledger.ndjsonl"
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.exists() else []


def test_repeated_fires_write_the_ledger_ONCE_per_day_bucket(tmp_path):
    """Regression (measured 2026-08-12): the ledger write used to be unconditional while
    only the stdout drift line was deduped, so ONE stuck flag wrote a HIGH entry on EVERY
    fire — 6 entries in 10 minutes on 2026-08-07.

    The harm is not disk (the ledger is ring-trimmed at 500 lines) but SIGNAL: ~288
    entries/day evicts every other finding within ~2 days, and the SessionStart surface
    (capped at 10 lines) degenerates into ten copies of one message. Worse, the affected
    project is BY DEFINITION the dark one, so nobody is there to notice or ack it.
    """
    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    code = tmp_path / "code"
    observer = _project(code, "observer", flag_age_s=None, cron="*/5 * * * *")
    dead = _age_from_real_now(_project(code, "dead-one", flag_age_s=6 * 86400, cron="*/5 * * * *"), 6 * 86400)
    for p in (observer, dead):
        _harness_dir(projects, p.name, str(p))

    for _ in range(4):
        _run_detector(home, observer)

    lines = _ledger_lines(dead)
    assert len(lines) == 1, f"4 fires must write ONE entry, got {len(lines)}:\n" + "\n".join(lines)
    assert '"RESUME-ORPHANED"' in lines[0]
    # The finding belongs to the AFFECTED project, never the observer's own ledger.
    assert _ledger_lines(observer) == []


def test_two_orphaned_projects_do_not_suppress_each_other(tmp_path):
    """The dedupe key is per affected project. A single shared key would mean the first
    orphan found silences every other one for the rest of the day — the failure mode that
    makes a fleet-wide detector report exactly one victim no matter how many there are."""
    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    code = tmp_path / "code"
    observer = _project(code, "observer", flag_age_s=None, cron="*/5 * * * *")
    a = _age_from_real_now(_project(code, "dead-a", flag_age_s=6 * 86400, cron="*/5 * * * *"), 6 * 86400)
    b = _age_from_real_now(_project(code, "dead-b", flag_age_s=7 * 86400, cron="*/5 * * * *"), 7 * 86400)
    for p in (observer, a, b):
        _harness_dir(projects, p.name, str(p))

    _run_detector(home, observer)
    _run_detector(home, observer)

    assert len(_ledger_lines(a)) == 1
    assert len(_ledger_lines(b)) == 1
