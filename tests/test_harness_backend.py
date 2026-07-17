"""harness_backend — the two-world discriminator + server probe (TRDD-PZLVT2RN Phase A).

These pin the SSOT every branch point imports: the harness-session detection (env flags),
the server_owns_family_a probe ladder with its FAIL-SAFE tie-breaking (None ⇒ hands off,
False only when CONFIDENT), and the call-time (never import-frozen) continuity-CLI
feature-detection.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import harness_backend as hb  # noqa: E402

_HARNESS_VARS = (
    "AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH",
    hb.SERVER_STATE_ENV, hb.CONTINUITY_CLI_ENV, "AIMAESTRO_CLI",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """Every test starts OUTSIDE the harness with no overrides — each test opts in."""
    for var in _HARNESS_VARS:
        monkeypatch.delenv(var, raising=False)


def test_backend_is_standalone_outside_the_harness() -> None:
    """A clean env is the #N world."""
    assert hb.is_harness_session({}) is False
    assert hb.backend({}) == hb.BACKEND_STANDALONE


@pytest.mark.parametrize("var,value", [
    ("AIMAESTRO_AGENT", "1"),
    ("AIMAESTRO_AGENT", "true"),
    ("THIS_IS_AIMAESTRO", "yes"),
    ("AMP_AGENT_ID", "some-uuid"),
    ("AID_AUTH", "bearer-token"),
])
def test_backend_is_aimaestro_inside_the_harness(var: str, value: str) -> None:
    """Each documented harness signal flips the backend: the stable flags AND the
    internals fallback (AMP_AGENT_ID / AID_AUTH presence)."""
    env = {var: value}
    assert hb.is_harness_session(env) is True
    assert hb.backend(env) == hb.BACKEND_AIMAESTRO


def test_backend_reads_process_env_when_none_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    """env=None must consult os.environ — the form every call site uses."""
    assert hb.is_harness_session() is False
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    assert hb.is_harness_session() is True


# --- server_owns_family_a: the probe ladder --------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("up", True), ("true", True), ("1", True),
    ("down", False), ("false", False), ("0", False),
    ("unknown", None),
])
def test_server_probe_env_override_wins(monkeypatch: pytest.MonkeyPatch, value, expected) -> None:
    """Rung 1: the operator/test override short-circuits everything (no subprocess)."""
    monkeypatch.setenv(hb.SERVER_STATE_ENV, value)
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: pytest.fail("must not resolve the CLI"))
    assert hb.server_owns_family_a() is expected


def test_server_probe_no_cli_is_the_only_confident_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ai-maestro CLI on the machine ⇒ no server can own anything ⇒ False."""
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: None)
    assert hb.server_owns_family_a() is False


def test_server_probe_list_success_is_a_live_server_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    """`aimaestro-agent.sh list --json` curls the server API — rc 0 + JSON ⇒ True."""
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: "/fake/aimaestro-agent.sh")
    monkeypatch.setattr(
        hb.state, "run_subprocess",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='[{"id": "x"}]', stderr=""),
    )
    assert hb.server_owns_family_a() is True


@pytest.mark.parametrize("proc", [
    None,                                                              # subprocess never ran
    SimpleNamespace(returncode=7, stdout="", stderr="conn refused"),   # server down OR transient
    SimpleNamespace(returncode=0, stdout="not-json", stderr=""),       # garbled reply
])
def test_server_probe_failure_is_none_never_false(monkeypatch: pytest.MonkeyPatch, proc) -> None:
    """THE FAIL-SAFE: a failed probe with the CLI PRESENT is None, never False — a down
    server and a transient error are indistinguishable, and None keeps the daemon's
    harness-exclusion HELD (two owners actuating one agent is the corruption this split
    prevents). False would trigger the fallback-adoption path on a hiccup."""
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: "/fake/aimaestro-agent.sh")
    monkeypatch.setattr(hb.state, "run_subprocess", lambda *_a, **_k: proc)
    assert hb.server_owns_family_a() is None


# --- continuity_cli: call-time feature detection ---------------------------------

def _make_exec(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_continuity_cli_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "continuity.sh"
    _make_exec(script)
    monkeypatch.setenv(hb.CONTINUITY_CLI_ENV, str(script))
    assert hb.continuity_cli() == str(script)


def test_continuity_cli_override_must_be_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken override is None (feature-detect, never trust a path blindly)."""
    plain = tmp_path / "not-exec.sh"
    plain.write_text("", encoding="utf-8")
    monkeypatch.setenv(hb.CONTINUITY_CLI_ENV, str(plain))
    assert hb.continuity_cli() is None


def test_continuity_cli_resolves_home_at_call_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ISOLATION PROOF (the frozen-Path.home() lesson): a HOME set AFTER import must be
    honored — the ladder resolves at call time, so tests (and users moving HOME) never leak
    to the real ~/.local/bin."""
    home = tmp_path / "home"
    script = home / ".local" / "bin" / "aimaestro-continuity.sh"
    _make_exec(script)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(hb.shutil, "which", lambda _n: pytest.fail("must find HOME's copy first"))
    assert hb.continuity_cli() == str(script)


def test_continuity_cli_falls_back_to_path_then_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.setattr(hb.shutil, "which", lambda _n: "/somewhere/aimaestro-continuity.sh")
    assert hb.continuity_cli() == "/somewhere/aimaestro-continuity.sh"
    monkeypatch.setattr(hb.shutil, "which", lambda _n: None)
    assert hb.continuity_cli() is None
