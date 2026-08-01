"""Backend selection for /janitor-plugin-{install,uninstall,upgrade}.

The one thing these tests exist to protect: the backend is chosen from whether THIS SESSION
is a harness agent, NOT from whether an ai-maestro server is running. Those two questions are
adjacent, both answered by `harness_backend`, and the janitor's chore logic deliberately uses
the OTHER one — so the confusion is live, and it inverts behaviour silently.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))

import harness_backend  # noqa: E402
import plugin_target as pt  # noqa: E402

SCRIPT = _ROOT / "scripts" / "plugin_manage.py"


def _import_pm():
    import importlib.util

    spec = importlib.util.spec_from_file_location("plugin_manage_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- backend selection ----------------------------------------------


def test_standalone_uses_the_claude_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH"):
        monkeypatch.delenv(var, raising=False)
    assert harness_backend.backend() == harness_backend.BACKEND_STANDALONE
    pm = _import_pm()
    cmds = pm.build_argv(
        "install",
        pt.parse_target("foo@bar"),
        scope="user",
        backend=harness_backend.BACKEND_STANDALONE,
        agent_ref=None,
        cli=None,
    )
    assert cmds == [["claude", "plugin", "install", "foo@bar", "--scope", "user"]]


def test_a_running_server_does_NOT_change_a_standalone_session(tmp_path: Path) -> None:
    """THE inversion guard. A live server makes the janitor yield its CHORES, but it must not
    make a standalone Claude route its own plugins through the agent CLI — that CLI targets an
    AGENT this session is not.

    Driven through the SCRIPT as a real process, deliberately. The first version of this test
    asserted on `harness_backend.backend()` instead, and a mutation that rewrote the script's
    own selection to `server_is_alive()` left all 12 tests GREEN — the test could not observe
    the line it existed to protect. Asserting on the script's printed backend is what makes
    the mutation fail."""
    import json
    import os
    import time

    live = tmp_path / "server-liveness.json"
    live.write_text(
        json.dumps({"ts": int(time.time()), "pid": 1, "capabilities": ["all"]}), encoding="utf-8"
    )
    env = {**os.environ, harness_backend.LIVENESS_FILE_ENV: str(live), "HOME": str(tmp_path)}
    for var in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH"):
        env.pop(var, None)

    # Precondition: the server really does read as alive, or the test proves nothing.
    assert harness_backend.server_capabilities is not None
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(SCRIPT), "install", "foo@bar", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "backend=standalone" in proc.stdout, (
        "a LIVE server flipped a standalone session onto the agent CLI — the backend must be "
        f"chosen from the session, not server liveness. stdout={proc.stdout!r}"
    )


def test_harness_session_uses_the_agent_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    assert harness_backend.backend() == harness_backend.BACKEND_AIMAESTRO
    pm = _import_pm()
    cmds = pm.build_argv(
        "install",
        pt.parse_target("foo@bar"),
        scope="local",
        backend=harness_backend.BACKEND_AIMAESTRO,
        agent_ref="agent-7",
        cli="/opt/aimaestro-agent.sh",
    )
    assert cmds == [
        ["/opt/aimaestro-agent.sh", "plugin", "install", "agent-7", "foo@bar", "--scope", "local"]
    ]


def test_harness_without_the_cli_REFUSES_rather_than_falling_back() -> None:
    """Falling back to `claude` inside the harness would mutate config the server owns, and the
    next reconcile would revert it — a failure that looks like success at the time."""
    pm = _import_pm()
    with pytest.raises(RuntimeError, match="aimaestro-agent.sh was not found"):
        pm.build_argv(
            "install",
            pt.parse_target("foo@bar"),
            scope="local",
            backend=harness_backend.BACKEND_AIMAESTRO,
            agent_ref="agent-7",
            cli=None,
        )


def test_harness_without_a_self_agent_ref_refuses() -> None:
    pm = _import_pm()
    with pytest.raises(RuntimeError, match="own id could not be resolved"):
        pm.build_argv(
            "install",
            pt.parse_target("foo@bar"),
            scope="local",
            backend=harness_backend.BACKEND_AIMAESTRO,
            agent_ref=None,
            cli="/opt/aimaestro-agent.sh",
        )


# ---------- marketplace registration ----------------------------------------


def test_a_source_bearing_target_registers_the_marketplace_first() -> None:
    """Order matters: installing before the marketplace exists fails on an unknown name."""
    pm = _import_pm()
    cmds = pm.build_argv(
        "install",
        pt.parse_target("cpv@Emasoft/emasoft-plugins"),
        scope="user",
        backend=harness_backend.BACKEND_STANDALONE,
        agent_ref=None,
        cli=None,
    )
    assert cmds[0] == ["claude", "plugin", "marketplace", "add", "Emasoft/emasoft-plugins"]
    assert cmds[1] == ["claude", "plugin", "install", "cpv@emasoft-plugins", "--scope", "user"]


def test_a_bare_source_refuses_because_the_plugin_is_unknown() -> None:
    """`owner/repo` names a marketplace that may ship several plugins. Installing a guess is
    worse than refusing, so the caller is told to name one."""
    pm = _import_pm()
    with pytest.raises(RuntimeError, match="names a marketplace SOURCE"):
        pm.build_argv(
            "install",
            pt.parse_target("Emasoft/ai-maestro-plugins"),
            scope="user",
            backend=harness_backend.BACKEND_STANDALONE,
            agent_ref=None,
            cli=None,
        )


@pytest.mark.parametrize("action", ["install", "uninstall", "update"])
def test_all_three_actions_build_symmetrically(action: str) -> None:
    pm = _import_pm()
    cmds = pm.build_argv(
        action,
        pt.parse_target("foo@bar"),
        scope="user",
        backend=harness_backend.BACKEND_STANDALONE,
        agent_ref=None,
        cli=None,
    )
    assert cmds == [["claude", "plugin", action, "foo@bar", "--scope", "user"]]


# ---------- end to end, as a real process -----------------------------------


def test_dry_run_executes_nothing_and_names_the_backend(tmp_path: Path) -> None:
    """Run the script the way a skill does. --dry-run must print the plan and run none of it."""
    env = {
        **{k: v for k, v in __import__("os").environ.items()},
        "HOME": str(tmp_path),
    }
    for var in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH"):
        env.pop(var, None)
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(SCRIPT), "install", "foo@bar", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "backend=standalone" in proc.stdout
    assert "claude plugin install foo@bar --scope user" in proc.stdout
    assert "dry-run: nothing executed" in proc.stdout


def test_a_refused_argument_exits_nonzero_without_running_anything(tmp_path: Path) -> None:
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(SCRIPT), "install", "--scope", "user", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0


# ---------- local directories ------------------------------------------------


def test_a_local_marketplace_dir_registers_then_installs_by_name(tmp_path: Path) -> None:
    """A real directory on disk, classified from its manifests — not a string heuristic."""
    import json

    mk = tmp_path / "mk"
    (mk / ".claude-plugin").mkdir(parents=True)
    (mk / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "mk"}))
    (mk / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "pg"}))

    pm = _import_pm()
    resolved = pm.resolve_local(pt.parse_target(str(mk)))
    cmds = pm.build_argv(
        "install", resolved, scope="user",
        backend=harness_backend.BACKEND_STANDALONE, agent_ref=None, cli=None,
    )
    assert cmds[0] == ["claude", "plugin", "marketplace", "add", str(mk)]
    assert cmds[1] == ["claude", "plugin", "install", "pg@mk", "--scope", "user"]


def test_a_lone_plugin_dir_refuses_with_an_actionable_message(tmp_path: Path) -> None:
    """No command exists for this shape, so emitting one would fail with an unrelated error."""
    import json

    pg = tmp_path / "pg"
    (pg / ".claude-plugin").mkdir(parents=True)
    (pg / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "pg"}))

    pm = _import_pm()
    with pytest.raises(RuntimeError, match="cannot install a bare directory"):
        pm.resolve_local(pt.parse_target(str(pg)))


def test_uninstall_refuses_a_directory(tmp_path: Path) -> None:
    """Resolving a path on uninstall would ADD a marketplace while removing a plugin."""
    import json
    import os

    mk = tmp_path / "mk"
    (mk / ".claude-plugin").mkdir(parents=True)
    (mk / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "mk"}))

    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(SCRIPT), "uninstall", str(mk), "--dry-run"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "HOME": str(tmp_path)},
    )
    assert proc.returncode != 0
    assert "not a directory" in proc.stderr or "NOT a directory" in proc.stderr or "directory" in proc.stderr


def test_uninstall_never_registers_a_marketplace() -> None:
    """REGRESSION, found by running the script rather than by a test. `plugin@owner/market`
    on uninstall was emitting `marketplace add` first — so removing a plugin ADDED a
    marketplace that then outlived it. Removal must never acquire anything."""
    pm = _import_pm()
    cmds = pm.build_argv(
        "uninstall",
        pt.parse_target("cpv@Emasoft/emasoft-plugins"),
        scope="user",
        backend=harness_backend.BACKEND_STANDALONE,
        agent_ref=None,
        cli=None,
    )
    assert len(cmds) == 1, f"uninstall must emit exactly one command, got {cmds}"
    assert cmds[0] == ["claude", "plugin", "uninstall", "cpv@emasoft-plugins", "--scope", "user"]
    assert not any("marketplace" in c for cmd in cmds for c in cmd)


def test_install_of_the_same_target_DOES_register() -> None:
    """The paired assertion: the skip is specific to uninstall, not a lost feature."""
    pm = _import_pm()
    cmds = pm.build_argv(
        "install",
        pt.parse_target("cpv@Emasoft/emasoft-plugins"),
        scope="user",
        backend=harness_backend.BACKEND_STANDALONE,
        agent_ref=None,
        cli=None,
    )
    assert len(cmds) == 2 and cmds[0][2] == "marketplace"
