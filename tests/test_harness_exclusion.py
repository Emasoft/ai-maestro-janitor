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


def test_root_under_agents_home_canonicalizes_a_symlinked_agents_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlinked (or otherwise non-canonical) agents home must still match — janitor#142's
    "canonicalize before comparing paths" lesson, applied here.

    `root_under_agents_home` receives `root` from `fleet_scan.find_janitor_root`, which
    ALWAYS runs the scanned instance's cwd through `os.path.realpath`. Before this fix,
    `agents_home()`'s own (possibly non-canonical) string was compared LEXICALLY against
    that realpath'd root, so an agents home reached via a symlink — a symlinked `$HOME`, an
    NFS mount, or `AIMAESTRO_AGENTS_HOME` pointed at a non-canonical path — never matched
    even though the two strings name the SAME directory: the exclusion silently went
    hands-off exactly where it should have been owned.
    """
    real_home = tmp_path / "real-agents-home"
    real_home.mkdir()
    symlinked_home = tmp_path / "symlinked-agents-home"
    symlinked_home.symlink_to(real_home)
    bob_dir = real_home / "bob"
    bob_dir.mkdir()

    monkeypatch.setenv(hb.AGENTS_HOME_ENV, str(symlinked_home))
    # What find_janitor_root would hand in: os.path.realpath of the scanned cwd — resolved
    # THROUGH the symlink, so it never contains the symlinked path's own text.
    realpath_root = str(bob_dir.resolve())
    assert symlinked_home.name not in realpath_root, "test setup: root must not lexically contain the symlink's own path"
    assert hb.root_under_agents_home(realpath_root) is True


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


# --- Phase C: #J thin-mode gating --------------------------------------------------

def test_ensure_daemon_running_refuses_inside_the_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE SPAWN CHOKE POINT: a harness agent must never spawn the machine-global
    daemon (the SERVER is its daemon). Gated inside ensure_daemon_running so all four
    callers are covered; a spawn attempt in this test is an instant failure."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs-c"))
    sys.modules.pop("global_state", None)
    import global_state as gs  # noqa: PLC0415

    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setattr(gs, "spawn_daemon_detached", lambda: pytest.fail("must never spawn inside the harness"))
    monkeypatch.setattr(gs, "daemon_is_alive", lambda **_k: pytest.fail("must refuse before any liveness probe"))
    assert gs.ensure_daemon_running() is False

    # Outside the harness the normal ladder resumes (alive → True, no spawn).
    monkeypatch.delenv("AIMAESTRO_AGENT", raising=False)
    monkeypatch.setattr(gs, "daemon_is_alive", lambda **_k: True)
    assert gs.ensure_daemon_running() is True


def test_dispatch_detector_roster_is_filtered_in_harness() -> None:
    """The thin-mode roster: machine-global mutators + OAuth surfaces are OFF inside;
    workdir-scoped detectors keep running. Pinned by NAME so a future roster addition
    that mutates global state must consciously join the set."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "janitor_dispatch_harness", str(_ROOT / "scripts" / "dispatch.py")
    )
    assert spec is not None and spec.loader is not None
    dispatch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dispatch)

    for name in (
        "marketplace-refresh", "local-plugins-update",
        "project-plugins-update", "version-update", "plugin-updates",
        "oauth-beacon-refresh", "oauth-cookie-reminder", "oauth-login-needed",
        "keychain-health", "window-burn-rate", "fleet-github-config",
    ):
        assert not dispatch._detector_runs_in_harness(name), name
    for name in ("dirty-tree", "trdd-drift", "token-usage-anomaly", "supply-chain-fingerprints",
                 "memory-maintenance", "screenshot-purge",
                 # The 2026-08-02 always-on directive requires BOTH GitHub notification
                 # chores to work "inside ai-maestro harness and outside". Both are
                 # workdir-scoped — issues-watch keeps its seen-map in `.janitor/state/`,
                 # gh-reply-watch its registry in `.janitor/gh-issues-monitor/` — so
                 # neither belongs in the gated set. Pinned so a later roster sweep cannot
                 # quietly gate them and half-revoke the directive.
                 "github-issues-watch", "gh-reply-watch"):
        assert dispatch._detector_runs_in_harness(name), name
        assert name in {n for n, _i, _e in dispatch._DETECTORS}, f"{name} left the roster"
    # Every gated name must actually exist in the roster — a typo here would silently
    # gate nothing.
    roster = {n for n, _i, _e in dispatch._DETECTORS}
    missing = dispatch._NON_HARNESS_DETECTORS - roster
    assert not missing, f"gated names not in the roster: {missing}"


def test_session_start_hook_writes_nothing_outside_the_project_in_harness_mode(
    tmp_path: Path,
) -> None:
    """END-TO-END thin-mode proof: the REAL SessionStart hook, run inside a fake harness
    env with a fully isolated HOME, must not create ~/.claude/rules, ~/.claude/settings.json,
    the reference docs, or the memory mirror — #J writes only the project's .janitor/state.
    The control run (same isolation, no harness flag) must install rules, proving the
    isolation itself didn't mask a regression."""
    import subprocess  # noqa: PLC0415

    def _run_hook(*, harness: bool, home: Path, project: Path) -> None:
        home.mkdir(parents=True, exist_ok=True)
        (home / "gs").mkdir(exist_ok=True)  # the settings-ensurer flock lives here
        project.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "CLAUDE_PROJECT_DIR": str(project),
            "CLAUDE_PLUGIN_ROOT": str(_ROOT),
            "JANITOR_GLOBAL_STATE_DIR": str(home / "gs"),
        }
        if harness:
            env["AIMAESTRO_AGENT"] = "1"
        proc = subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "hooks" / "on-session-start.py")],
            input='{"source": "startup"}',
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr

    thin_home = tmp_path / "thin-home"
    _run_hook(harness=True, home=thin_home, project=tmp_path / "thin-proj")
    assert not (thin_home / ".claude" / "rules").exists(), "thin mode must not install rules"
    assert not (thin_home / ".claude" / "settings.json").exists(), "thin mode must not touch settings"
    assert not (thin_home / ".claude" / "ai-maestro-janitor-memory").exists(), "no mirror sync"
    assert not (thin_home / ".claude" / "plugins").exists(), "no DATA-dir reference docs"

    ctrl_home = tmp_path / "ctrl-home"
    _run_hook(harness=False, home=ctrl_home, project=tmp_path / "ctrl-proj")
    # settings_ensurer CREATES settings.json when missing, unconditionally outside the
    # harness — the one writer that needs no pre-seeded install state. (install_rules
    # is no control here: it only targets scopes whose settings.json already enable
    # the plugin, which a blank isolated HOME never does.)
    assert (ctrl_home / ".claude" / "settings.json").is_file(), (
        "the control run must write settings.json — otherwise the thin-mode assertions "
        "above prove nothing (the isolation, not the gate, would explain the absence)"
    )
