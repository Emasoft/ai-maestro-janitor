"""harness_backend — the two-world discriminator + server probe (TRDD-PZLVT2RN Phase A).

These pin the SSOT every branch point imports: the harness-session detection (env flags),
the server_owns_family_a probe ladder with its FAIL-SAFE tie-breaking (None ⇒ hands off,
False only when CONFIDENT), and the call-time (never import-frozen) continuity-CLI
feature-detection.
"""

from __future__ import annotations

import json
import stat
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import harness_backend as hb  # noqa: E402

_HARNESS_VARS = (
    "AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH",
    hb.SERVER_STATE_ENV, hb.CONTINUITY_CLI_ENV, "AIMAESTRO_CLI",
    hb.LIVENESS_FILE_ENV,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Every test starts OUTSIDE the harness with no overrides — each test opts in.
    The liveness probe is pointed at a guaranteed-absent file so no test can read a
    REAL `~/.aimaestro/server-liveness.json` on a machine that runs the server."""
    for var in _HARNESS_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent-liveness.json"))


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
# Since TRDD-N9YAH5E7 the canonical signal is the auth-free probe FILE the server
# rewrites every 30 s (`~/.aimaestro/server-liveness.json`, #100 §6.1); the legacy
# `list --json` subprocess rung is gone (liveness is not capability).


def _write_liveness(path: Path, *, ts: float, caps: list) -> None:
    path.write_text(json.dumps({"ts": ts, "pid": 4242, "capabilities": caps}), encoding="utf-8")


@pytest.mark.parametrize("value,expected", [
    ("up", True), ("true", True), ("1", True),
    ("down", False), ("false", False), ("0", False),
    ("unknown", None),
])
def test_server_probe_env_override_wins(monkeypatch: pytest.MonkeyPatch, value, expected) -> None:
    """Rung 1: the operator/test override short-circuits everything (no file, no CLI)."""
    monkeypatch.setenv(hb.SERVER_STATE_ENV, value)
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: pytest.fail("must not resolve the CLI"))
    monkeypatch.setattr(hb, "server_capabilities", lambda **_k: pytest.fail("must not read the file"))
    assert hb.server_owns_family_a() is expected


def test_server_probe_no_cli_is_the_only_confident_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """No fresh probe file AND no ai-maestro CLI on the machine ⇒ no server can own
    anything ⇒ False (the only confident False without a fresh claim)."""
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: None)
    assert hb.server_owns_family_a() is False


def test_fresh_probe_file_with_token_is_confident_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rung 2: a fresh file whose capabilities carry `family-a` ⇒ True — the server's
    own self-report, no CLI needed (the whole point: auth-free, daemon-readable)."""
    f = tmp_path / "liveness.json"
    _write_liveness(f, ts=time.time(), caps=["family-a"])
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: pytest.fail("file rung must decide"))
    assert hb.server_owns_family_a() is True


def test_fresh_probe_file_without_token_is_confident_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE #100 §6.2 RULE: a LIVE server that does not claim a class does not own it —
    a fresh file without `family-a` is a CONFIDENT False (tokens are present ONLY while
    the class is live and running), so the OAuth chores keep running."""
    f = tmp_path / "liveness.json"
    _write_liveness(f, ts=time.time(), caps=[])
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    assert hb.server_owns_family_a() is False


@pytest.mark.parametrize("content", [
    "not-json",                                            # garbled
    '{"capabilities": ["family-a"]}',                      # missing ts
    '{"ts": true, "capabilities": ["family-a"]}',          # bool masquerading as ts
    '{"ts": 1, "capabilities": "family-a"}',               # caps not a list
])
def test_malformed_probe_file_is_no_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """A malformed file is NO CLAIM: with the CLI present the answer is None (a down or
    pre-probe server — capability unknowable), never a guessed True/False."""
    f = tmp_path / "liveness.json"
    f.write_text(content, encoding="utf-8")
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: "/fake/aimaestro-agent.sh")
    assert hb.server_owns_family_a() is None


def test_stale_probe_file_is_no_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE FAIL-SAFE: a file older than the 90 s staleness window is NO CLAIM — with
    the CLI present the answer is None, keeping the daemon's harness-exclusion HELD
    (a crashed server must not read as 'owns family-a' off its last stale beat) while
    the chores' own None-policy keeps them RUNNING."""
    f = tmp_path / "liveness.json"
    _write_liveness(f, ts=time.time() - hb.LIVENESS_STALE_AFTER_S - 5, caps=["family-a"])
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: "/fake/aimaestro-agent.sh")
    assert hb.server_owns_family_a() is None


def test_stale_probe_file_with_no_cli_is_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale claim + no CLI anywhere ⇒ the machine has no live ai-maestro ⇒ False."""
    f = tmp_path / "liveness.json"
    _write_liveness(f, ts=time.time() - 10_000, caps=["family-a"])
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    monkeypatch.setattr(hb, "_resolve_agent_cli", lambda: None)
    assert hb.server_owns_family_a() is False


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
