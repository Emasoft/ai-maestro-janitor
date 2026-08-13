"""Tests for the orphaned-memory-maint decision layer + detector (issue #238,
TRDD-2112XCKO).

A dropped memory-maintenance pass looks IDENTICAL to a completed one from the
scheduler's own state — nothing deletes `memory-maint-pending.json` when the
dispatched agent finishes. What proves a drop is (1) no NEWER dispatch of the same
(intervention, scope, root) has landed since (`pending_is_current`), combined with
(2) the record's age exceeding several multiples of its own cadence (`is_orphaned`).
Pure logic is tested directly; the end-to-end shape (dedupe + the findings ledger) is
tested by running the real detector as a subprocess, exactly like its sibling
`orphaned-resume-flag` (test_orphaned_resume.py).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "lib"))

import orphaned_memory_maint as omm  # noqa: E402

_NOW = 1_800_000_000

# ── read_pending ──────────────────────────────────────────────────────────────


def test_read_pending_absent_file_is_healthy_not_malformed(tmp_path):
    payload, malformed = omm.read_pending(tmp_path)
    assert payload is None
    assert malformed is False


def test_read_pending_malformed_json_is_a_finding(tmp_path):
    (tmp_path / omm.PENDING_NAME).write_text("{ not json", encoding="utf-8")
    payload, malformed = omm.read_pending(tmp_path)
    assert payload is None
    assert malformed is True


def test_read_pending_missing_required_field_is_malformed(tmp_path):
    (tmp_path / omm.PENDING_NAME).write_text(
        json.dumps({"marker": "[janitor-memory-repair]", "stamped_at": 123}),
        encoding="utf-8",
    )
    payload, malformed = omm.read_pending(tmp_path)
    assert payload is None
    assert malformed is True


def test_read_pending_well_formed_payload(tmp_path):
    (tmp_path / omm.PENDING_NAME).write_text(
        json.dumps({
            "marker": "[janitor-memory-repair]", "intervention": "repair",
            "scope": "LOCAL", "root": "/tmp/x", "stamped_at": 100, "dispatch_id": "d1",
        }),
        encoding="utf-8",
    )
    payload, malformed = omm.read_pending(tmp_path)
    assert malformed is False
    assert payload is not None
    assert payload["intervention"] == "repair"
    assert payload["scope"] == "LOCAL"


# ── pure decisions ───────────────────────────────────────────────────────────


def test_pending_age_s_never_negative():
    assert omm.pending_age_s({"stamped_at": _NOW}, now=_NOW - 5) == 0
    assert omm.pending_age_s({"stamped_at": _NOW - 100}, now=_NOW) == 100


def test_pending_is_current_true_when_no_newer_dispatch():
    payload = {"stamped_at": 1000}
    assert omm.pending_is_current(payload, last_run=1000)
    assert omm.pending_is_current(payload, last_run=0)


def test_pending_is_current_false_when_superseded_elsewhere():
    """A later dispatch of the SAME key (this project or another) proves the corpus
    WAS attended to — this stale record must not be reported."""
    payload = {"stamped_at": 1000}
    assert not omm.pending_is_current(payload, last_run=2000)


def test_pending_is_current_false_on_garbage_payload():
    assert not omm.pending_is_current({}, last_run=0)


def test_is_orphaned_needs_age_past_factor_times_cadence():
    assert not omm.is_orphaned(0, 100.0, factor=3)
    assert not omm.is_orphaned(299, 100.0, factor=3)
    assert omm.is_orphaned(300, 100.0, factor=3)
    assert omm.is_orphaned(3000, 100.0, factor=3)


def test_is_orphaned_disabled_intervention_never_orphans():
    """cadence == inf means the intervention is at 0/day — nothing was ever
    expected to run again, so an ancient record is simply history."""
    assert not omm.is_orphaned(10_000_000, math.inf, factor=3)
    assert not omm.is_orphaned(10_000_000, 0.0, factor=3)


def test_factor_for_scope_local_is_tighter():
    """LOCAL has no other session to recover it (#238's core finding) — tighter
    bound than USER/PROJECT, which a healthy peer session can re-dispatch."""
    assert omm.factor_for_scope("LOCAL") == omm.LOCAL_FACTOR
    assert omm.factor_for_scope("local") == omm.LOCAL_FACTOR  # case-insensitive
    assert omm.factor_for_scope("USER") == omm.DEFAULT_FACTOR
    assert omm.factor_for_scope("PROJECT") == omm.DEFAULT_FACTOR
    assert omm.factor_for_scope("LOCAL", local=1, default=5) == 1
    assert omm.factor_for_scope("USER", local=1, default=5) == 5


def test_format_finding_names_the_stranding_for_local():
    msg = omm.format_finding("repair", "LOCAL", 7200, 3600.0)
    assert "no other session can recover this LOCAL scope" in msg
    assert "2.0h" in msg


def test_format_finding_names_the_peer_recovery_for_user():
    msg = omm.format_finding("consolidate", "USER", 7200, 3600.0)
    assert "another healthy session sharing this scope" in msg
    assert "no other session can recover" not in msg


def test_format_finding_handles_disabled_cadence():
    msg = omm.format_finding("split", "PROJECT", 100000, math.inf)
    assert "disabled" in msg


# ── end-to-end: the real detector as a subprocess ───────────────────────────

_DETECTOR = _HERE.parent / "scripts" / "detectors" / "orphaned-memory-maint.py"


def _stamp_last_run(gstate: Path, intervention: str, scope: str, root: str, ts: int) -> None:
    """Write the same machine-wide last-run stamp `memory_settings.mark_ran` would,
    without importing the module under a different env — the file SHAPE is the
    contract (`scripts/lib/memory_settings.py::_stamp_path`/`mark_ran`)."""
    gstate.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]
    (gstate / f"memory-maint-{intervention}-{scope}-{h}.last-run.ts").write_text(
        str(int(ts)), encoding="utf-8"
    )


def _write_pending(state_dir: Path, *, intervention: str, scope: str, root: str, stamped_at: int) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / omm.PENDING_NAME).write_text(
        json.dumps({
            "marker": f"[janitor-memory-{intervention}]", "intervention": intervention,
            "scope": scope, "root": root, "stamped_at": stamped_at, "dispatch_id": "d1",
        }),
        encoding="utf-8",
    )


def _write_settings(settings_dir: Path, **values: object) -> None:
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "memory-settings.json").write_text(
        json.dumps(values, indent=2, sort_keys=True), encoding="utf-8"
    )


def _run(home: Path, project: Path, gstate: Path, settings: Path, **extra: str) -> str:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["JANITOR_GLOBAL_STATE_DIR"] = str(gstate)
    env["JANITOR_MEMORY_SETTINGS_DIR"] = str(settings)
    env.pop("CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_INTERVAL", None)
    env.update(extra)
    res = subprocess.run(
        [sys.executable, str(_DETECTOR)], capture_output=True, text=True, env=env, timeout=60,
    )
    if res.returncode != 0:
        raise AssertionError(f"detector exited {res.returncode}; stderr:\n{res.stderr}")
    return res.stdout


def _ledger_lines(project: Path) -> list[str]:
    p = project / ".janitor" / "state" / "findings-ledger.ndjsonl"
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.exists() else []


def _fixture(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    gstate = tmp_path / "gstate"
    settings = tmp_path / "settings"
    state_dir = project / ".janitor" / "state"
    return home, project, gstate, settings, state_dir


def test_no_pending_file_is_silent(tmp_path):
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    _write_settings(settings, repair_per_day=1000.0)
    out = _run(home, project, gstate, settings)
    assert out == ""
    assert _ledger_lines(project) == []


def test_fresh_pending_is_silent(tmp_path):
    """1x cadence old — a hiccup, not a drop."""
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    root = str(project / "memory")
    _write_settings(settings, repair_per_day=1000.0)  # cadence ~86.4s
    now = int(time.time())
    _write_pending(state_dir, intervention="repair", scope="LOCAL", root=root, stamped_at=now - 10)
    _stamp_last_run(gstate, "repair", "LOCAL", root, now - 10)
    out = _run(home, project, gstate, settings)
    assert out == ""
    assert _ledger_lines(project) == []


def test_orphaned_local_pending_alarms(tmp_path):
    """LOCAL, current (no newer dispatch), well past its 1x-cadence bound -> a
    HIGH MEMPASS-ORPHANED entry naming the stranding."""
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    root = str(project / "memory")
    _write_settings(settings, repair_per_day=1000.0)  # cadence ~86.4s, LOCAL factor 1
    now = int(time.time())
    old = now - 500  # well past 86.4s
    _write_pending(state_dir, intervention="repair", scope="LOCAL", root=root, stamped_at=old)
    _stamp_last_run(gstate, "repair", "LOCAL", root, old)

    out = _run(home, project, gstate, settings)

    assert "orphaned-memory-maint" in out
    assert "LOCAL" in out and "no other session can recover" in out
    lines = _ledger_lines(project)
    assert len(lines) == 1
    assert '"MEMPASS-ORPHANED"' in lines[0]


def test_superseded_elsewhere_does_not_alarm(tmp_path):
    """A NEWER machine-wide dispatch of the same key (simulating a healthy peer
    session re-running it) proves the corpus was attended to — must stay silent
    even though THIS record, personally, is ancient."""
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    root = str(project / "memory")
    _write_settings(settings, consolidation_per_day=1000.0)
    now = int(time.time())
    old = now - 500
    _write_pending(state_dir, intervention="consolidate", scope="USER", root=root, stamped_at=old)
    _stamp_last_run(gstate, "consolidate", "USER", root, now - 5)  # newer than stamped_at

    out = _run(home, project, gstate, settings)

    assert out == ""
    assert _ledger_lines(project) == []


def test_disabled_intervention_never_orphans(tmp_path):
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    root = str(project / "memory")
    _write_settings(settings, harvest_per_day=0.0)  # disabled -> cadence == inf
    now = int(time.time())
    old = now - 10_000_000
    _write_pending(state_dir, intervention="harvest", scope="LOCAL", root=root, stamped_at=old)
    _stamp_last_run(gstate, "harvest", "LOCAL", root, old)

    out = _run(home, project, gstate, settings)

    assert out == ""
    assert _ledger_lines(project) == []


def test_malformed_pending_alarms_once_and_recovers(tmp_path):
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    _write_settings(settings, repair_per_day=1000.0)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / omm.PENDING_NAME).write_text("{ not json", encoding="utf-8")

    out1 = _run(home, project, gstate, settings)
    assert "MEMPASS-MALFORMED" not in out1  # code lives in the ledger, not stdout
    assert "cannot be parsed" in out1
    lines = _ledger_lines(project)
    assert len(lines) == 1
    assert '"MEMPASS-MALFORMED"' in lines[0]

    # Second fire on the SAME malformed file: deduped, no second ledger entry.
    out2 = _run(home, project, gstate, settings)
    assert out2 == ""
    assert len(_ledger_lines(project)) == 1

    # File becomes readable again (fixed by hand, or overwritten by a fresh
    # dispatch) -> the malformed dedupe key must be forgotten so a FUTURE genuine
    # malformation re-alerts instead of staying suppressed forever.
    root = str(project / "memory")
    now = int(time.time())
    _write_pending(state_dir, intervention="repair", scope="LOCAL", root=root, stamped_at=now)
    _stamp_last_run(gstate, "repair", "LOCAL", root, now)
    out3 = _run(home, project, gstate, settings)
    assert out3 == ""  # fresh, not orphaned — but no crash, no stuck malformed state

    (state_dir / omm.PENDING_NAME).write_text("{ still not json", encoding="utf-8")
    out4 = _run(home, project, gstate, settings)
    lines = _ledger_lines(project)
    # A SECOND, distinct malformed incident — proof the dedupe key was actually
    # forgotten after healing, not merely quiet because it never re-triggered.
    assert sum(1 for ln in lines if '"MEMPASS-MALFORMED"' in ln) == 2
    assert "cannot be parsed" in out4


def test_three_consecutive_dropped_passes_alarm_once_not_never(tmp_path):
    """THE AMOA case (janitor#238) and the card's fifth acceptance box: a memory pass
    dispatched and silently dropped THREE times in a row, with no heal in between.

    Two ways to fail it, and both are bad in the direction this detector exists to prevent:
    staying silent (the original bug — a dropped pass is invisible, so the corpus quietly
    stops being maintained), or shouting once per drop (three lines for one standing fact
    trains the reader to filter the detector out). The contract is exactly one finding, and
    one ledger entry, for as long as the condition holds.

    Distinct from the dedupe/heal test below, whose docstring scopes it to the CONSUMED-file
    criterion: here nothing ever heals, which is the whole point.
    """
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    root = str(project / "memory")
    _write_settings(settings, repair_per_day=1000.0)
    now = int(time.time())

    outs = []
    # Each drop: the scheduler dispatched and stamped, and nothing ever consumed it. Every
    # stamp stays well past factor*cadence so no intermediate evaluation reads as healthy —
    # a single healthy read would emit_forget the key and mask the "alarms once" claim.
    for stamped_at in (now - 1500, now - 1100, now - 700):
        _write_pending(state_dir, intervention="repair", scope="LOCAL", root=root,
                       stamped_at=stamped_at)
        _stamp_last_run(gstate, "repair", "LOCAL", root, stamped_at)
        outs.append(_run(home, project, gstate, settings))

    alarms = [o for o in outs if "orphaned-memory-maint" in o]
    assert len(alarms) == 1, f"exactly one standing finding expected, got {len(alarms)}: {outs!r}"
    assert alarms[0] is not None and outs[0] == alarms[0], "it must alarm on the FIRST window"
    assert len(_ledger_lines(project)) == 1


def test_repeated_orphan_fires_write_the_ledger_once_then_healing_clears_dedupe(tmp_path):
    """Regression guard for the acceptance criterion: 'a consumed (absent) pending
    file emits nothing and clears any prior dedupe state' — a healed key must not
    suppress a genuinely NEW future drop."""
    home, project, gstate, settings, state_dir = _fixture(tmp_path)
    root = str(project / "memory")
    _write_settings(settings, repair_per_day=1000.0)
    now = int(time.time())
    old = now - 500
    _write_pending(state_dir, intervention="repair", scope="LOCAL", root=root, stamped_at=old)
    _stamp_last_run(gstate, "repair", "LOCAL", root, old)

    out1 = _run(home, project, gstate, settings)
    assert "orphaned-memory-maint" in out1
    out2 = _run(home, project, gstate, settings)
    assert out2 == ""  # same (intervention, scope) drop — deduped
    assert len(_ledger_lines(project)) == 1

    # Heal: a newer dispatch supersedes this record (peer session, or this one
    # re-armed and re-dispatched).
    _stamp_last_run(gstate, "repair", "LOCAL", root, now)
    out3 = _run(home, project, gstate, settings)
    assert out3 == ""
    assert len(_ledger_lines(project)) == 1  # still just the one prior entry

    # A brand-new drop on the SAME (intervention, scope) key must re-alarm — proof
    # the dedupe state was actually cleared, not merely quiet because it healed.
    older2 = now - 1000
    _write_pending(state_dir, intervention="repair", scope="LOCAL", root=root, stamped_at=older2)
    _stamp_last_run(gstate, "repair", "LOCAL", root, older2)
    out4 = _run(home, project, gstate, settings)
    assert "orphaned-memory-maint" in out4
    assert len(_ledger_lines(project)) == 2
