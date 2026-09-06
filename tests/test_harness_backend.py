"""harness_backend — the two-world discriminator + server probe (TRDD-PZLVT2RN Phase A).

These pin the SSOT every branch point imports: the harness-session detection (env flags),
the BINARY server-liveness switch (TRDD-LU0C5KAR: fresh probe file ⇒ the server runs and
owns all absorbed chores; absent/stale/malformed ⇒ the janitor keeps them — fail-safe),
and the call-time (never import-frozen) continuity-CLI feature-detection.
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


# --- server_is_alive / server_runs_chores: the binary liveness switch -------------
# Since TRDD-LU0C5KAR (owner directive 2026-07-17) the signal is BINARY: a fresh
# probe file (`~/.aimaestro/server-liveness.json`, rewritten every 30 s) means the
# server is RUNNING and owns ALL absorbed chores; absent/stale/malformed means it is
# not, and the janitor runs them all. The capability tokens are informational.


def _write_liveness(path: Path, *, ts: float, caps: list) -> None:
    path.write_text(json.dumps({"ts": ts, "pid": 4242, "capabilities": caps}), encoding="utf-8")


@pytest.mark.parametrize("value,expected", [
    ("up", True), ("true", True), ("1", True),
    ("down", False), ("false", False), ("0", False),
])
def test_server_chores_env_override_wins(
    monkeypatch: pytest.MonkeyPatch, value, expected
) -> None:
    """The operator/test override short-circuits the probe read entirely."""
    monkeypatch.setenv(hb.SERVER_STATE_ENV, value)
    monkeypatch.setattr(hb, "server_capabilities", lambda **_k: pytest.fail("must not read the file"))
    assert hb.server_runs_chores() is expected


def test_unknown_override_falls_through_to_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unrecognized override value is no answer — the probe decides (absent file ⇒
    server not running ⇒ the janitor keeps the chores). The None tri-state died with
    the per-class design."""
    monkeypatch.setenv(hb.SERVER_STATE_ENV, "unknown")
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent.json"))
    assert hb.server_runs_chores() is False


def test_fresh_probe_file_means_alive_regardless_of_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE binary rule: a fresh file ⇒ the server is RUNNING ⇒ it owns the chores —
    even when it advertises NO capabilities. A running server that does not execute an
    absorbed chore is a SERVER bug (owner: "any other event is a bug"), never a reason
    for the janitor to keep it."""
    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    for caps in (["family-a"], []):
        _write_liveness(f, ts=time.time(), caps=caps)
        assert hb.server_is_alive() is True, caps
        assert hb.server_runs_chores() is True, caps


@pytest.mark.parametrize("content", [
    "not-json",                                            # garbled
    '{"capabilities": ["family-a"]}',                      # missing ts
    '{"ts": true, "capabilities": ["family-a"]}',          # bool masquerading as ts
    '{"ts": 1, "capabilities": "family-a"}',               # caps not a list
])
def test_malformed_probe_file_is_not_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """A malformed file is NO liveness claim ⇒ the janitor keeps every chore (fail-safe:
    a machine with no provable server must never lose its chores)."""
    f = tmp_path / "liveness.json"
    f.write_text(content, encoding="utf-8")
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    assert hb.server_is_alive() is False
    assert hb.server_runs_chores() is False


def test_stale_probe_file_means_the_server_exited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE HANDBACK: the server rewrites the file every 30 s, so one older than the
    90 s staleness window means it exited/crashed — the janitor switches every absorbed
    chore back ON (the owner's rule: only while it runs are they its responsibility)."""
    f = tmp_path / "liveness.json"
    _write_liveness(f, ts=time.time() - hb.LIVENESS_STALE_AFTER_S - 5, caps=["family-a"])
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    assert hb.server_is_alive() is False
    assert hb.server_runs_chores() is False


def test_absent_probe_file_means_not_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No file at all (no server ever started on this build, or none installed) ⇒ not
    alive ⇒ the janitor runs everything."""
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent.json"))
    assert hb.server_is_alive() is False
    assert hb.server_runs_chores() is False


# --- server_liveness_probe: the reason behind a None (TRDD-HXZ8B0IS) --------------
# `server_capabilities()` collapsed absent/malformed/stale/read-error to one None so a
# chore-coordination flap could never explain itself. These pin the sibling that keeps
# server_capabilities()'s own signature unchanged while exposing WHY.


def test_probe_reports_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent.json"))
    probe = hb.server_liveness_probe()
    assert probe.reason == "absent"
    assert probe.ts is None and probe.age is None
    assert probe.describe() == "absent"


@pytest.mark.parametrize("content", [
    '{"capabilities": ["family-a"]}',              # missing ts
    '{"ts": true, "capabilities": ["family-a"]}',  # bool masquerading as ts
    '{"ts": 1, "capabilities": "family-a"}',       # caps not a list
    '[]',                                          # valid JSON, not an object at all
    '"just a string"',                             # ditto — used to surface as read-error
])
def test_probe_reports_malformed_for_a_wrong_shaped_but_valid_json_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """Valid JSON, wrong shape (missing/misstyped `ts` or `capabilities`) ⇒ "malformed" —
    distinct from a file that fails to parse at all (see the read-error test below)."""
    f = tmp_path / "liveness.json"
    f.write_text(content, encoding="utf-8")
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    probe = hb.server_liveness_probe()
    assert probe.reason == "malformed"
    assert probe.describe() == "malformed"


def test_probe_reports_read_error_for_a_partial_json_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated/garbled file (what a partial read mid-non-atomic-rewrite looks like)
    fails json.loads itself ⇒ "read-error", carrying the exception TYPE name."""
    f = tmp_path / "liveness.json"
    f.write_text('{"ts": 1, "capabilities": [', encoding="utf-8")  # truncated mid-write
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    probe = hb.server_liveness_probe()
    assert probe.reason == "read-error"
    assert probe.exc_type == "JSONDecodeError"
    assert probe.describe() == "read-error(JSONDecodeError)"


def test_probe_reports_stale_with_the_computed_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """91 s old — just past the 90 s window — ⇒ "stale", carrying `ts` and the age."""
    f = tmp_path / "liveness.json"
    now = time.time()
    _write_liveness(f, ts=now - 91, caps=["family-a"])
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    probe = hb.server_liveness_probe(now=now)
    assert probe.reason == "stale"
    assert probe.ts == pytest.approx(now - 91)
    assert probe.age == pytest.approx(91, abs=0.5)
    assert probe.describe() == f"stale(age={probe.age:.1f})"
    assert probe.capabilities is None


def test_probe_reports_alive_with_ts_age_and_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """89 s old — just inside the 90 s window — ⇒ "alive", carrying `ts`, age, and caps."""
    f = tmp_path / "liveness.json"
    now = time.time()
    _write_liveness(f, ts=now - 89, caps=["family-a"])
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    probe = hb.server_liveness_probe(now=now)
    assert probe.reason == "alive"
    assert probe.ts == pytest.approx(now - 89)
    assert probe.age == pytest.approx(89, abs=0.5)
    assert probe.describe() == "alive"
    assert probe.capabilities == frozenset({"family-a"})


def test_server_capabilities_still_delegates_and_keeps_its_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """server_capabilities()'s return type is unchanged: None on every non-alive reason,
    the capability frozenset on alive — this is the delegation contract the fix requires."""
    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    now = time.time()
    _write_liveness(f, ts=now, caps=["family-a"])
    assert hb.server_capabilities(now=now) == frozenset({"family-a"})
    _write_liveness(f, ts=now - hb.LIVENESS_STALE_AFTER_S - 5, caps=["family-a"])
    assert hb.server_capabilities(now=now) is None


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


# --- runs_chores_from / claimed_chores_from: one probe drives both (TRDD-ARTTXA7P) ---
# The daemon tick used to call `server_runs_chores()`, `claimed_chores()` and
# `server_liveness_probe()` separately — up to three reads of a file the server rewrites
# non-atomically every 30 s, so the logged reason could describe a different read than the
# one that drove the decision. These pin that `*_from(probe)` matches the live wrapper for
# a fresh file, and that ONE probe, held across a simulated fresh->stale flip, still reports
# the OLD probe's answer for both derived facts — i.e. the mismatch is impossible by
# construction because there is only one probe object to derive from.


def test_runs_chores_from_matches_server_runs_chores_for_a_fresh_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    _write_liveness(f, ts=time.time(), caps=["family-a"])
    probe = hb.server_liveness_probe()
    assert hb.runs_chores_from(probe) == hb.server_runs_chores() is True


def test_claimed_chores_from_matches_claimed_chores_for_a_partial_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    _write_liveness(f, ts=time.time(), caps=["session-liveness"])
    probe = hb.server_liveness_probe()
    assert hb.claimed_chores_from(probe) == hb.claimed_chores() == frozenset({"session-liveness"})


def test_one_probe_holds_its_own_answer_across_a_fresh_to_stale_flip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The construction proof: take ONE probe while the file is fresh, then let the file
    go stale (simulating the server exiting mid-tick). A caller that re-reads (the old
    `claimed_chores()` shape) now disagrees with the decision already made; a caller that
    derives everything from the ORIGINAL probe object cannot — there is nothing left to
    re-read."""
    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    _write_liveness(f, ts=time.time(), caps=["family-a"])
    probe = hb.server_liveness_probe()
    assert hb.runs_chores_from(probe) is True
    assert hb.claimed_chores_from(probe) == hb.SERVER_ABSORBED_TASKS

    # The file now reads stale (server gone) — a FRESH read disagrees with `probe`.
    _write_liveness(f, ts=time.time() - hb.LIVENESS_STALE_AFTER_S - 5, caps=["family-a"])
    assert hb.server_runs_chores() is False
    assert hb.claimed_chores() == frozenset()

    # The ORIGINAL probe object still answers exactly as it did when it was taken — a
    # message built from it can never contradict the decision built from it.
    assert hb.runs_chores_from(probe) is True
    assert hb.claimed_chores_from(probe) == hb.SERVER_ABSORBED_TASKS


@pytest.mark.parametrize("caps,age_s,expected", [
    (sorted(hb.GLOBAL_CHORES), 0.0, True),                 # fresh, every chore claimed
    (["session-liveness"], 0.0, False),                    # fresh, partial claim
    (sorted(hb.GLOBAL_CHORES), hb.LIVENESS_STALE_AFTER_S + 5, False),  # full claim, stale
])
def test_owns_every_chore_from_matches_server_owns_every_chore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caps: list[str], age_s: float, expected: bool
) -> None:
    """The daemon's exit gate derives from the tick's one probe; the spawn gate calls the
    wrapper. Both must answer the same question or the daemon spawn/exit-flaps (the d45a843a
    incident), so the helper is pinned to the wrapper for all three shapes."""
    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    _write_liveness(f, ts=time.time() - age_s, caps=caps)
    probe = hb.server_liveness_probe()
    assert hb.owns_every_chore_from(probe) is hb.server_owns_every_chore() is expected


def test_runs_chores_from_still_honors_the_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator override must win even when handed a probe that disagrees with it."""
    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    _write_liveness(f, ts=time.time(), caps=[])  # alive, claims nothing
    probe = hb.server_liveness_probe()
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "down")
    assert hb.runs_chores_from(probe) is False
    assert hb.server_runs_chores() is False


def test_claimed_chores_from_still_honors_the_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent.json"))
    probe = hb.server_liveness_probe()
    assert probe.reason == "absent"
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    assert hb.claimed_chores_from(probe) == hb.SERVER_ABSORBED_TASKS == hb.claimed_chores()
