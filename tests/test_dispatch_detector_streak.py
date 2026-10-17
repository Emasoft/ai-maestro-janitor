"""Tests for the detector failure streak (TRDD-P64SR014): K failed passes in a row raise one finding.

Real stamps and a real ledger under tmp_path, a real killed subprocess for the e2e case, no mocks.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

# The REAL ledger of the checkout running the suite, resolved from the env BEFORE any isolation.
_REAL_LEDGER = Path(os.environ.get("CLAUDE_PROJECT_DIR") or _PROJECT_ROOT) / ".janitor" / "state" / "findings-ledger.ndjsonl"
# Unique per run, so a row in the real ledger with one of these names can only come from this run.
# The real ledger is only ever READ (the live heartbeat appends to it concurrently): no size compare.
_RUN = uuid.uuid4().hex[:8]
ALPHA = f"p64-streak-{_RUN}-a"
BETA = f"p64-streak-{_RUN}-b"
SLEEPER = f"p64-streak-{_RUN}-s"


@pytest.fixture
def proj(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point CLAUDE_PROJECT_DIR at a tmp project and reload the state modules."""
    project = tmp_path / "project"
    (project / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "janitor-control"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    for mod in ("dispatch", "state", "global_state", "findings_ledger"):
        sys.modules.pop(mod, None)
    yield project
    # Both candidate real ledgers: the checkout's own, plus the import-time CLAUDE_PROJECT_DIR one if it differs.
    checkout_ledger = _PROJECT_ROOT / ".janitor" / "state" / "findings-ledger.ndjsonl"
    for ledger in dict.fromkeys((checkout_ledger, _REAL_LEDGER)):
        if ledger.exists():
            leaked = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if f"p64-streak-{_RUN}" in ln]
            assert not leaked, f"the test run wrote to the REAL findings ledger {ledger}"


def _import_dispatch():
    """Import scripts/dispatch.py without running main()."""
    import importlib.util as _u

    spec = _u.spec_from_file_location("janitor_dispatch_streak_ut", str(_PROJECT_ROOT / "scripts" / "dispatch.py"))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(proj: Path, code: str | None = None) -> list[dict]:
    """Ledger rows of the tmp project, optionally only those of one code."""
    path = proj / ".janitor" / "state" / "findings-ledger.ndjsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if code is None or r.get("code") == code]


def _fail(dispatch, name: str, outcome: str = "error:timeout") -> None:
    """One failed pass through the real default-outcome seam."""
    dispatch._record_default_outcome(name, outcome, int(time.time()) + 10)


def test_third_failure_raises_exactly_one_high_finding(proj: Path) -> None:
    """Two failures raise nothing; the 3rd raises one HIGH row; the 4th and 5th add none."""
    dispatch = _import_dispatch()
    for _ in range(2):
        _fail(dispatch, ALPHA)
    assert _rows(proj, "DETECTOR-FAIL") == []
    _fail(dispatch, ALPHA)
    rows = _rows(proj, "DETECTOR-FAIL")
    assert len(rows) == 1
    assert rows[0]["sev"] == "HIGH" and rows[0]["src"] == ALPHA
    _fail(dispatch, ALPHA)
    _fail(dispatch, ALPHA)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 1


def test_each_failure_kind_shares_one_counter(proj: Path) -> None:
    """error:timeout, error:rc=1 and error:spawn-failed count toward the same streak."""
    dispatch = _import_dispatch()
    for outcome in ("error:timeout", "error:rc=1", "error:spawn-failed"):
        _fail(dispatch, ALPHA, outcome)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 1


def test_success_resets_count_and_removes_stamp(proj: Path) -> None:
    """An ok pass deletes the stamp, so 2 + ok + 2 failures never alert."""
    dispatch = _import_dispatch()
    stamp = proj / ".janitor" / "state" / f"detector-fail-streak-{ALPHA}.ts"
    _fail(dispatch, ALPHA)
    _fail(dispatch, ALPHA)
    assert stamp.exists()
    _fail(dispatch, ALPHA, "ok")
    assert not stamp.exists()
    _fail(dispatch, ALPHA)
    _fail(dispatch, ALPHA)
    assert _rows(proj, "DETECTOR-FAIL") == []


def test_new_episode_after_recovery_alerts_again(proj: Path) -> None:
    """Fail x3, recover, fail x3 gives two FAIL rows and one RECOVERED row."""
    dispatch = _import_dispatch()
    for _ in range(3):
        _fail(dispatch, ALPHA)
    _fail(dispatch, ALPHA, "ok")
    for _ in range(3):
        _fail(dispatch, ALPHA)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 2
    assert len(_rows(proj, "DETECTOR-RECOVERED")) == 1


def test_non_error_outcome_counts_as_success(proj: Path) -> None:
    """Fail x3, applied, fail x3 gives 2 FAIL rows and 1 RECOVERED row (applied is a pass that ran)."""
    dispatch = _import_dispatch()
    for _ in range(3):
        _fail(dispatch, ALPHA)
    _fail(dispatch, ALPHA, "applied")
    for _ in range(3):
        _fail(dispatch, ALPHA)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 2
    assert len(_rows(proj, "DETECTOR-RECOVERED")) == 1


def test_declined_outcome_also_resets(proj: Path) -> None:
    """A declined:<why> outcome resets the streak like ok does."""
    dispatch = _import_dispatch()
    _fail(dispatch, ALPHA)
    _fail(dispatch, ALPHA, "declined:no-pane")
    assert not (proj / ".janitor" / "state" / f"detector-fail-streak-{ALPHA}.ts").exists()


def test_streak_is_per_detector(proj: Path) -> None:
    """Interleaved failures of two detectors are counted separately."""
    dispatch = _import_dispatch()
    for _ in range(2):
        _fail(dispatch, ALPHA)
        _fail(dispatch, BETA)
    assert _rows(proj, "DETECTOR-FAIL") == []
    _fail(dispatch, ALPHA)
    rows = _rows(proj, "DETECTOR-FAIL")
    assert [r["src"] for r in rows] == [ALPHA]


def test_garbled_stamp_reads_as_zero(proj: Path) -> None:
    """A garbled stamp starts a fresh streak instead of crashing the heartbeat."""
    dispatch = _import_dispatch()
    (proj / ".janitor" / "state" / f"detector-fail-streak-{ALPHA}.ts").write_text("garbage", encoding="utf-8")
    _fail(dispatch, ALPHA)
    assert (proj / ".janitor" / "state" / f"detector-fail-streak-{ALPHA}.ts").read_text(encoding="utf-8").startswith("1 ")


# The timeout IS the subject: opt out of the suite-wide subprocess-timeout scaling.
@pytest.mark.no_timeout_scale
def test_killed_detector_alerts_on_third_run_only(proj: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A real sleeper killed by the 1 s timeout prints the finding line on the 3rd run only."""
    dispatch = _import_dispatch()
    fake_root = proj / "fake_plugin_root"
    (fake_root / "detectors").mkdir(parents=True)
    script = fake_root / "detectors" / f"{SLEEPER}.py"
    script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(dispatch, "_HERE", fake_root)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT", "1")
    import state

    state.init_state()
    for i in (1, 2, 3):
        start = time.monotonic()
        dispatch._run_detector(SLEEPER, interval=0)
        assert time.monotonic() - start < 16.0
        out = capsys.readouterr().out
        if i < 3:
            assert "DETECTOR-FAIL" not in out
        else:
            assert "DETECTOR-FAIL" in out and SLEEPER in out
    assert len(_rows(proj, "DETECTOR-FAIL")) == 1


def test_streak_stamp_does_not_affect_due(proj: Path) -> None:
    """Regression guard: a streak stamp must never feed `_detector_is_due`."""
    dispatch = _import_dispatch()
    for _ in range(3):
        _fail(dispatch, ALPHA)
    assert dispatch._detector_is_due(ALPHA, 3600) is True
    (proj / ".janitor" / "state" / f"last-run-{ALPHA}.ts").write_text(str(int(time.time())), encoding="utf-8")
    assert dispatch._detector_is_due(ALPHA, 3600) is False



def test_guard_streak_resets_on_completed_run(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard: 3 spawn failures alert once, a completed run recovers, 3 more alert a second time."""
    dispatch = _import_dispatch()
    fake_root = proj / "fake_plugin_root"
    (fake_root / "guard").mkdir(parents=True)
    script = fake_root / "guard" / "branch_protection_apply.py"
    # Real executables, no timeout wait: a script whose interpreter does not exist makes
    # subprocess.run raise OSError (the spawn-failed path); a real script exiting 0 completes.
    broken = "#!/nonexistent/interpreter\n"
    working = "#!/bin/sh\nexit 0\n"
    monkeypatch.setattr(dispatch, "_HERE", fake_root)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GUARD_BRANCH_PROTECTION_INTERVAL", "0")
    import state

    state.init_state()
    last_run = proj / ".janitor" / "state" / "last-run-guard-branch-protection.ts"

    def run_guard(body: str, times: int) -> None:
        script.write_text(body, encoding="utf-8")
        script.chmod(0o755)
        for _ in range(times):
            last_run.unlink(missing_ok=True)
            dispatch._phase_guard_branch_protection()

    run_guard(broken, 2)
    assert _rows(proj, "DETECTOR-FAIL") == []
    run_guard(broken, 1)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 1
    run_guard(working, 1)
    assert len(_rows(proj, "DETECTOR-RECOVERED")) == 1
    assert not (proj / ".janitor" / "state" / "detector-fail-streak-guard-branch-protection.ts").exists()
    run_guard(broken, 3)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 2

def test_guard_nonzero_rc_counts_as_crash(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard: rc 1 three times alerts exactly once; a following rc 0 run records recovery."""
    dispatch = _import_dispatch()
    fake_root = proj / "fake_plugin_root"
    (fake_root / "guard").mkdir(parents=True)
    script = fake_root / "guard" / "branch_protection_apply.py"
    monkeypatch.setattr(dispatch, "_HERE", fake_root)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GUARD_BRANCH_PROTECTION_INTERVAL", "0")
    import state

    state.init_state()
    last_run = proj / ".janitor" / "state" / "last-run-guard-branch-protection.ts"

    def run_guard(body: str, times: int) -> None:
        script.write_text(body, encoding="utf-8")
        script.chmod(0o755)
        for _ in range(times):
            last_run.unlink(missing_ok=True)
            dispatch._phase_guard_branch_protection()

    run_guard("#!/bin/sh\nexit 1\n", 3)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 1
    # WHY: a crashing guard must stamp its outcome, else the stamp keeps a stale healthy value.
    outcome_stamp = proj / ".janitor" / "state" / "last-outcome-guard-branch-protection.ts"
    assert outcome_stamp.read_text(encoding="utf-8").strip().endswith("error:rc=1")
    run_guard("#!/bin/sh\nexit 0\n", 1)
    assert len(_rows(proj, "DETECTOR-RECOVERED")) == 1



def test_streak_counts_when_detector_self_stamped(proj: Path) -> None:
    """A fresh self-written outcome stamp hits the early return, yet the failures still count."""
    dispatch = _import_dispatch()
    import state

    state.init_state()
    now = int(time.time())
    (proj / ".janitor" / "state" / f"last-outcome-{ALPHA}.ts").write_text(f"{now} declined:x", encoding="utf-8")
    for _ in range(3):
        dispatch._record_default_outcome(ALPHA, "error:rc=1", now - 10)
    assert len(_rows(proj, "DETECTOR-FAIL")) == 1
