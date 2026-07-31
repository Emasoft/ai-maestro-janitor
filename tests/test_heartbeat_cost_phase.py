"""Tests for dispatch._phase_heartbeat_cost (janitor#78, TRDD-EFTQB9RR sibling).

The phase runs a USER-CONFIGURED command that reports the previous fire's exact cost
and appends its first stdout line to the `heartbeat-cost` log. Two contracts dominate:

1. **Silence on stdout, always.** The heartbeat's zero-output contract means every byte
   a fire prints forces the model to spend output tokens surfacing it on EVERY fire —
   a per-fire stdout cost line would tax the exact thing it exists to measure. The
   series lives in the log file.
2. **Fail-open, per the CLI's own fail-fast design.** A non-zero exit, timeout, missing
   binary, or unparseable command string means "no cost line this fire" — the fire is
   never blocked and never noisier for it.

All commands here are REAL subprocesses (echo / false / sh) — no mocks.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Point project + global state at tmp dirs; hand back a fresh dispatch module."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND", raising=False)
    for mod in ("dispatch", "global_state", "state"):
        sys.modules.pop(mod, None)

    import importlib.util as _u

    spec = _u.spec_from_file_location(
        "janitor_dispatch_cost_test", str(_PROJECT_ROOT / "scripts" / "dispatch.py")
    )
    assert spec is not None and spec.loader is not None
    dispatch = _u.module_from_spec(spec)
    spec.loader.exec_module(dispatch)
    dispatch.state.init_state()
    return {"dispatch": dispatch, "project": project}


def _run_capturing_stdout(fn) -> str:
    buf, old = StringIO(), sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


def _cost_log(project: Path) -> Path:
    return project / ".janitor" / "logs" / "heartbeat-cost.log"


def test_default_off_runs_nothing(iso) -> None:
    """Unset option → the phase is a silent no-op: no log file, no stdout.

    DEFAULT-OFF is load-bearing — the cost CLI is machine-local opt-in tooling, so a
    fleet-wide default would fail (harmlessly but pointlessly) on every other machine.
    """
    out = _run_capturing_stdout(iso["dispatch"]._phase_heartbeat_cost)
    assert out == ""
    assert not _cost_log(iso["project"]).exists()


def test_successful_command_logs_first_line_and_prints_nothing(
    iso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rc 0 → the FIRST stdout line lands in the heartbeat-cost log; stdout stays empty.

    Stdout-silence is contract #1: a printed line would be surfaced by the model on
    every fire, spending output tokens to report token spend.
    """
    monkeypatch.setenv(
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND",
        "echo 'The last heartbeat cost 42 tokens'",
    )
    out = _run_capturing_stdout(iso["dispatch"]._phase_heartbeat_cost)
    assert out == ""
    text = _cost_log(iso["project"]).read_text(encoding="utf-8")
    assert "The last heartbeat cost 42 tokens" in text


def test_multiline_stdout_logs_only_the_first_line(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """A chatty CLI must not flood the log — one fire, one line."""
    monkeypatch.setenv(
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND",
        "sh -c 'echo cost-line; echo debug-noise'",
    )
    _run_capturing_stdout(iso["dispatch"]._phase_heartbeat_cost)
    text = _cost_log(iso["project"]).read_text(encoding="utf-8")
    assert "cost-line" in text
    assert "debug-noise" not in text


def test_nonzero_exit_logs_nothing(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI is fail-fast (prints FAIL, exits non-zero when the server is down).

    Contract #2: non-zero == "no cost line this fire". Logging its FAIL output would
    grow the log unboundedly on every fire while the server is stopped.
    """
    monkeypatch.setenv(
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND",
        "sh -c 'echo FAIL: server unreachable; exit 1'",
    )
    out = _run_capturing_stdout(iso["dispatch"]._phase_heartbeat_cost)
    assert out == ""
    assert not _cost_log(iso["project"]).exists()


def test_missing_binary_never_raises_and_never_salts_the_series(
    iso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command that doesn't exist must not break the fire NOR write to the series.

    run_subprocess logs its failure to dispatch.log (detector_name="dispatch" is
    deliberate) — heartbeat-cost.log stays a pure cost series even while the CLI is
    misconfigured or its server is down.
    """
    monkeypatch.setenv(
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND",
        "/nonexistent/agentlens-heartbeat-cost --oneline",
    )
    out = _run_capturing_stdout(iso["dispatch"]._phase_heartbeat_cost)
    assert out == ""
    assert not _cost_log(iso["project"]).exists()
    dispatch_log = iso["project"] / ".janitor" / "logs" / "dispatch.log"
    assert dispatch_log.exists(), "the failure diagnostic should land in dispatch.log"


def test_unparseable_command_string_never_raises(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unbalanced quote in the configured string is a config typo, not a crash."""
    monkeypatch.setenv(
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND", "node 'unclosed quote"
    )
    out = _run_capturing_stdout(iso["dispatch"]._phase_heartbeat_cost)
    assert out == ""
    assert not _cost_log(iso["project"]).exists()


def test_whitespace_only_stdout_logs_nothing(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """rc 0 with blank output → nothing worth a log line."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND", "echo ''")
    _run_capturing_stdout(iso["dispatch"]._phase_heartbeat_cost)
    assert not _cost_log(iso["project"]).exists()


def test_main_calls_the_phase_on_every_fire_that_is_not_a_recovery() -> None:
    """The call site must sit among the cheap survival phases, above the detector roster.

    It used to be pinned above the MAINTENANCE early-return, because a call site below it
    would have blinded the cost series to exactly the mode built for long idle stretches.
    Maintenance is gone (owner directive 2026-07-31), so there is no early-return left to
    straddle — but the phase must still not drift down among the expensive chores, where a
    fire that returns early for any other reason would stop recording the previous fire's
    cost and leave holes in the series. Source-order assertion, same technique as the
    markdown-spec guards: the invariant lives in code layout no unit call can observe.
    """
    src = (_PROJECT_ROOT / "scripts" / "dispatch.py").read_text(encoding="utf-8")
    body = src[src.index("def main(") :]
    assert 'if mode == "maintenance":' not in body, "the maintenance early-return must be gone"
    call = body.index("_phase_heartbeat_cost()")
    detectors = body.index("_phase_cadence_tier()")
    assert call < detectors, "_phase_heartbeat_cost() must stay with the cheap survival phases"
