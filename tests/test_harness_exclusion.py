"""Daemon-side harness exclusion (TRDD-PZLVT2RN Phase B).

The owner's contract (janitor#100): "neither touches the other's agents". These pin the
whole exclusion chain: the pure ownership decision (`instance_is_server_owned`), the
`server_owned` diagnosis and its None recovery (which is what auto-skips the liveness
ladder AND the hard rungs), the last-known-roots cache that holds the exclusion through
a server hiccup, and the fleet-stop policy skip.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import fleet_stop  # noqa: E402
import harness_backend as hb  # noqa: E402
import session_liveness as sl  # noqa: E402


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """NEVER touch real global state (the keepalive test-isolation lesson)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.delenv(hb.SERVER_STATE_ENV, raising=False)
    sys.modules.pop("global_state", None)  # its dir resolution reads the env at import-ish paths


# --- the pure ownership decision --------------------------------------------------

def test_tagged_instance_is_owned() -> None:
    """The tag came from THIS scan's successful server list — it doubles as the
    live-server proof, so tagged ⇒ owned."""
    assert hb.instance_is_server_owned(
        tagged=True, root="/a", cli_present=True, list_ok=True, cached_roots=[], override=None,
    ) is True


def test_no_cli_is_never_owned() -> None:
    """No ai-maestro CLI ⇒ no server exists here — the confident False."""
    assert hb.instance_is_server_owned(
        tagged=True, root="/a", cli_present=False, list_ok=False, cached_roots=["/a"], override=None,
    ) is False


def test_override_false_forces_adoption() -> None:
    """The operator's escape hatch: forced 'down' un-owns even a tagged instance."""
    assert hb.instance_is_server_owned(
        tagged=True, root="/a", cli_present=True, list_ok=True, cached_roots=[], override=False,
    ) is False


def test_list_failure_holds_the_exclusion_via_the_cache() -> None:
    """THE FAIL-SAFE: server down or hiccuping (list failed) is indistinguishable, so a
    root the server LAST claimed stays hands-off — 'cannot see' must never become
    'free to actuate'."""
    cached = ["/Users/x/agents/foo"]
    assert hb.instance_is_server_owned(
        tagged=False, root="/Users/x/agents/foo", cli_present=True, list_ok=False,
        cached_roots=cached, override=None,
    ) is True
    # Subdirectory of a cached workdir is the same agent's tree.
    assert hb.instance_is_server_owned(
        tagged=False, root="/Users/x/agents/foo/sub", cli_present=True, list_ok=False,
        cached_roots=cached, override=None,
    ) is True
    # An unrelated root (including a prefix-LOOKALIKE) is not owned.
    assert hb.instance_is_server_owned(
        tagged=False, root="/Users/x/agents/foobar", cli_present=True, list_ok=False,
        cached_roots=cached, override=None,
    ) is False


def test_untagged_with_healthy_server_is_not_owned() -> None:
    """The list SUCCEEDED and this instance matched no agent ⇒ it is an ordinary
    outside session; the cache must NOT leak ownership onto it."""
    assert hb.instance_is_server_owned(
        tagged=False, root="/Users/x/code/proj", cli_present=True, list_ok=True,
        cached_roots=["/Users/x/code/proj"], override=None,
    ) is False


def test_agents_home_is_the_registry_free_signal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE F6 REALITY (verified live 2026-07-17): `aimaestro-agent.sh list` answers
    HTTP 401 to a caller without AID_AUTH — the daemon has none — so tag+cache can never
    fire from the daemon's context. An instance under the agents home must be owned
    ANYWAY (registry-free), or the exclusion is inert exactly where it matters."""
    assert hb.instance_is_server_owned(
        tagged=False, root="/Users/x/agents/foo", cli_present=True, list_ok=False,
        cached_roots=[], override=None, under_agents_home=True,
    ) is True
    # The override still forces adoption; a missing CLI still wins.
    assert hb.instance_is_server_owned(
        tagged=False, root="/Users/x/agents/foo", cli_present=True, list_ok=False,
        cached_roots=[], override=False, under_agents_home=True,
    ) is False
    assert hb.instance_is_server_owned(
        tagged=False, root="/Users/x/agents/foo", cli_present=False, list_ok=False,
        cached_roots=[], override=None, under_agents_home=True,
    ) is False
    # The path helper itself: env override + call-time HOME, exact-prefix semantics.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(hb.AGENTS_HOME_ENV, raising=False)
    assert hb.root_under_agents_home(str(tmp_path / "agents" / "bob")) is True
    assert hb.root_under_agents_home(str(tmp_path / "agents-other" / "bob")) is False
    assert hb.root_under_agents_home(None) is False
    monkeypatch.setenv(hb.AGENTS_HOME_ENV, "/srv/aim-agents")
    assert hb.root_under_agents_home("/srv/aim-agents/carol") is True


# --- the roots cache ---------------------------------------------------------------

def test_agent_roots_cache_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs2"))
    sys.modules.pop("global_state", None)
    (tmp_path / "gs2").mkdir()
    assert hb.recall_agent_roots() == []
    hb.remember_agent_roots(["/b", "/a"])
    assert hb.recall_agent_roots() == ["/a", "/b"]  # sorted, stable
    hb.remember_agent_roots(["/a", "/b"])  # unchanged content → no churn, still readable
    assert hb.recall_agent_roots() == ["/a", "/b"]


def test_agent_roots_cache_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Garbage in the cache file reads as [] — a corrupt cache must not break a scan."""
    gs = tmp_path / "gs3"
    gs.mkdir()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gs))
    sys.modules.pop("global_state", None)
    (gs / hb._AGENT_ROOTS_CACHE).write_text("not-json", encoding="utf-8")
    assert hb.recall_agent_roots() == []
    (gs / hb._AGENT_ROOTS_CACHE).write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert hb.recall_agent_roots() == []


def test_agent_workdirs_reads_both_shapes() -> None:
    agents = [
        {"workingDirectory": "/a"},
        {"session": {"workingDirectory": "/b"}},
        {"workingDirectory": "/a"},  # dupe collapses
        {"noDir": True},
        "not-a-dict",
    ]
    assert hb.agent_workdirs(agents) == ["/a", "/b"]


# --- the diagnosis + recovery mapping ----------------------------------------------

def test_server_owned_diagnosis_outranks_everything_but_unarmed() -> None:
    """Even a STUCK harness agent (stale + rate-limited — normally 'frozen', the one
    diagnosis the hard-restart rungs may kill) is the SERVER's to recover."""
    assert sl.diagnose_instance(
        deliberately_unarmed=False, pane_alive=True, transcript_stale=True,
        rate_limited=True, version_stale=False, server_owned=True,
    ) == "server_owned"
    # The user's own opt-out still ranks above it (both map to hands-off anyway).
    assert sl.diagnose_instance(
        deliberately_unarmed=True, pane_alive=True, transcript_stale=True,
        rate_limited=True, version_stale=False, server_owned=True,
    ) == "unarmed"


def test_server_owned_has_no_recovery() -> None:
    """recovery None is THE skip: daemon's liveness loop leaves the instance alone and
    the hard rungs (which require 'frozen') can never fire on it."""
    assert sl.recovery_for_diagnosis("server_owned") is None
    assert "server_owned" in sl.DIAGNOSES


def test_default_is_not_server_owned() -> None:
    """server_owned defaults False — every existing caller keeps its exact behavior."""
    assert sl.diagnose_instance(
        deliberately_unarmed=False, pane_alive=True, transcript_stale=True,
        rate_limited=True, version_stale=False,
    ) == "frozen"


# --- fleet-stop policy skip --------------------------------------------------------

def _sess(pid: int, *, server_owned: bool = False) -> dict:
    return {
        "pid": pid,
        "command": "claude --resume",
        "terminal": {"tmux_pane": "%1"},
        "server_owned": server_owned,
    }


def test_fleet_stop_skips_server_owned_sessions() -> None:
    """Harness agents get their global control from the SERVER — the daemon's stop
    injection must pass over them AND not burn a dedupe stamp for them."""
    plans = fleet_stop.select_stop_targets(
        [_sess(101, server_owned=True), _sess(102)],
        flag_state="disarm",
        self_pid=1,
        daemon_pid=2,
        already_injected=set(),
        user_active_pids=set(),
    )
    assert [p["pid"] for p in plans] == [102]


def test_fleet_stop_missing_key_is_not_owned() -> None:
    """Sessions built by older adapters (no 'server_owned' key) behave exactly as before."""
    sess = {"pid": 103, "command": "claude", "terminal": {}}
    plans = fleet_stop.select_stop_targets(
        [sess], flag_state="pause", self_pid=1, daemon_pid=2,
        already_injected=set(), user_active_pids=set(),
    )
    assert [p["pid"] for p in plans] == [103]
