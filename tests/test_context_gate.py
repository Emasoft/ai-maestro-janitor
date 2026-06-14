"""Tests for the ai-maestro context gate + terminal detection (TRDD-db169d9e).

The janitor is installed at USER scope, so it runs in EVERY project. These
primitives are what the ai-maestro-SPECIFIC detectors/skills consult to
self-deactivate outside ai-maestro, and what the terminal self-trigger scripts
consult to pick a send mechanism. Phase 1 ships them pure + tested, with no
behavior change to any detector yet.

`project_is_ai_maestro` / `ai_maestro_marketplace_members` are lru-cached and
read env + disk, so each case clears the caches and isolates env to tmp dirs.
`terminal_kind` / `in_ai_maestro_agent_env` are pure (take an explicit `env`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def _reset_caches() -> None:
    state.project_root.cache_clear()
    state.project_is_ai_maestro.cache_clear()
    state.ai_maestro_marketplace_members.cache_clear()


def _make_project(tmp_path: Path, name: str | None) -> Path:
    """A project dir with (optionally) a .claude-plugin/plugin.json `name`."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    if name is not None:
        meta = proj / ".claude-plugin"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    return proj


def _empty_plugins_root(tmp_path: Path) -> Path:
    """A plugins root with NO ai-maestro marketplace catalog → hardcoded fallback."""
    root = tmp_path / "plugins"
    (root / "marketplaces").mkdir(parents=True, exist_ok=True)
    return root


def _isolate(monkeypatch, project: Path, plugins_root: Path) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_PLUGINS_ROOT", str(plugins_root))
    monkeypatch.delenv("JANITOR_FORCE_AI_MAESTRO", raising=False)
    _reset_caches()


# --- project_is_ai_maestro -------------------------------------------------

def test_fleet_member_is_ai_maestro(monkeypatch, tmp_path):
    """A project whose plugin name is a fleet member → gate ON."""
    proj = _make_project(tmp_path, "ai-maestro-janitor")
    _isolate(monkeypatch, proj, _empty_plugins_root(tmp_path))
    assert state.project_is_ai_maestro() is True


def test_non_plugin_project_is_not_ai_maestro(monkeypatch, tmp_path):
    """A plain project with NO plugin.json → gate OFF."""
    proj = _make_project(tmp_path, None)
    _isolate(monkeypatch, proj, _empty_plugins_root(tmp_path))
    assert state.project_is_ai_maestro() is False


def test_foreign_plugin_is_not_ai_maestro(monkeypatch, tmp_path):
    """A plugin project whose name is NOT a marketplace member → gate OFF."""
    proj = _make_project(tmp_path, "some-random-community-plugin")
    _isolate(monkeypatch, proj, _empty_plugins_root(tmp_path))
    assert state.project_is_ai_maestro() is False


def test_force_on_override_wins_without_manifest(monkeypatch, tmp_path):
    """JANITOR_FORCE_AI_MAESTRO=1 forces the gate ON even with no manifest."""
    proj = _make_project(tmp_path, None)
    _isolate(monkeypatch, proj, _empty_plugins_root(tmp_path))
    monkeypatch.setenv("JANITOR_FORCE_AI_MAESTRO", "1")
    _reset_caches()
    assert state.project_is_ai_maestro() is True


def test_force_off_override_wins_for_fleet_member(monkeypatch, tmp_path):
    """JANITOR_FORCE_AI_MAESTRO=0 forces the gate OFF even for a fleet member."""
    proj = _make_project(tmp_path, "ai-maestro-janitor")
    _isolate(monkeypatch, proj, _empty_plugins_root(tmp_path))
    monkeypatch.setenv("JANITOR_FORCE_AI_MAESTRO", "off")
    _reset_caches()
    assert state.project_is_ai_maestro() is False


def test_live_catalog_member_is_recognised(monkeypatch, tmp_path):
    """A name present only in the live marketplace catalog (not the hardcoded
    fallback) is still recognised — the union picks it up."""
    plugins_root = tmp_path / "plugins"
    catalog = plugins_root / "marketplaces" / "ai-maestro-plugins" / ".claude-plugin"
    catalog.mkdir(parents=True, exist_ok=True)
    (catalog / "marketplace.json").write_text(
        json.dumps({"name": "ai-maestro-plugins", "plugins": [{"name": "ai-maestro-brand-new"}]}),
        encoding="utf-8",
    )
    proj = _make_project(tmp_path, "ai-maestro-brand-new")
    _isolate(monkeypatch, proj, plugins_root)
    assert state.project_is_ai_maestro() is True


# --- ai_maestro_marketplace_members ----------------------------------------

def test_members_include_hardcoded_fleet_without_catalog(monkeypatch, tmp_path):
    """With no catalog on disk, the hardcoded fleet is the floor."""
    _isolate(monkeypatch, _make_project(tmp_path, None), _empty_plugins_root(tmp_path))
    members = state.ai_maestro_marketplace_members()
    assert "ai-maestro-janitor" in members
    assert "ai-maestro-maintainer-agent" in members


def test_members_union_live_catalog(monkeypatch, tmp_path):
    """Live catalog members are unioned with the hardcoded fleet."""
    plugins_root = tmp_path / "plugins"
    catalog = plugins_root / "marketplaces" / "ai-maestro-plugins" / ".claude-plugin"
    catalog.mkdir(parents=True, exist_ok=True)
    (catalog / "marketplace.json").write_text(
        json.dumps({"name": "ai-maestro-plugins", "plugins": [{"name": "ai-maestro-future"}]}),
        encoding="utf-8",
    )
    _isolate(monkeypatch, _make_project(tmp_path, None), plugins_root)
    members = state.ai_maestro_marketplace_members()
    assert "ai-maestro-future" in members      # from the live catalog
    assert "ai-maestro-janitor" in members     # from the hardcoded fallback


# --- is_ai_maestro_plugin_id (R2 daemon exclusion) -------------------------

def test_plugin_id_fleet_member_by_marketplace_suffix(monkeypatch, tmp_path):
    monkeypatch.setenv("JANITOR_PLUGINS_ROOT", str(_empty_plugins_root(tmp_path)))
    state.ai_maestro_marketplace_members.cache_clear()
    assert state.is_ai_maestro_plugin_id("ai-maestro-maintainer-agent@ai-maestro-plugins") is True
    # The janitor's OWN id is excluded here too (self-update is task_version_update).
    assert state.is_ai_maestro_plugin_id("ai-maestro-janitor@ai-maestro-plugins") is True


def test_plugin_id_foreign_marketplace_is_not_fleet(monkeypatch, tmp_path):
    monkeypatch.setenv("JANITOR_PLUGINS_ROOT", str(_empty_plugins_root(tmp_path)))
    state.ai_maestro_marketplace_members.cache_clear()
    assert state.is_ai_maestro_plugin_id("some-community-tool@other-marketplace") is False


def test_plugin_id_bare_member_name_is_fleet(monkeypatch, tmp_path):
    monkeypatch.setenv("JANITOR_PLUGINS_ROOT", str(_empty_plugins_root(tmp_path)))
    state.ai_maestro_marketplace_members.cache_clear()
    assert state.is_ai_maestro_plugin_id("ai-maestro-janitor") is True


def test_plugin_id_empty_is_false():
    assert state.is_ai_maestro_plugin_id("") is False


# --- terminal_kind: PROCESS ANCESTRY, not env inference --------------------
#
# Each snapshot is `pid ppid command` per line — the format of
# `ps -axo pid=,ppid=,command=`. terminal_kind walks parent PIDs from `pid`
# toward the launching terminal and identifies it from the ancestor's command.

def _tree(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def test_terminal_iterm_from_ancestor():
    snap = _tree(
        "100 90 -zsh",
        "90 50 /usr/bin/node claude",
        "50 1 /Applications/iTerm.app/Contents/MacOS/iTerm2",
        "1 0 /sbin/launchd",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "iterm"


def test_terminal_tmux_when_server_is_ancestor():
    # A tmux pane's shell is a child of the tmux server (daemonized).
    snap = _tree(
        "100 90 -zsh",
        "90 50 tmux: server",
        "50 1 /sbin/launchd",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "tmux"


def test_terminal_tmux_takes_precedence_over_gui_further_up():
    # tmux is the NEAREST terminal ancestor → wins over an iTerm further up.
    snap = _tree(
        "100 90 -zsh",
        "90 50 tmux: server",
        "50 40 /Applications/iTerm.app/Contents/MacOS/iTerm2",
        "40 1 /sbin/launchd",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "tmux"


def test_terminal_apple_terminal_from_ancestor():
    snap = _tree(
        "100 90 -zsh",
        "90 1 /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
        "1 0 /sbin/launchd",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "apple-terminal"


def test_terminal_wezterm_macos_bundle():
    snap = _tree(
        "100 90 -zsh",
        "90 1 /Applications/WezTerm.app/Contents/MacOS/wezterm-gui",
        "1 0 /sbin/launchd",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "wezterm"


def test_terminal_kitty_linux_executable():
    snap = _tree(
        "100 90 /bin/bash",
        "90 1 /usr/bin/kitty",
        "1 0 /sbin/init",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "kitty"


def test_terminal_vscode_from_code_helper():
    snap = _tree(
        "100 90 /bin/zsh -i",
        "90 50 /Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper (Plugin).app/Contents/MacOS/Code Helper (Plugin)",
        "50 1 /sbin/launchd",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "vscode"


def test_terminal_unknown_when_no_terminal_ancestor():
    snap = _tree(
        "100 90 -zsh",
        "90 1 /sbin/launchd",
        "1 0 /sbin/launchd",
    )
    assert state.terminal_kind(ps_text=snap, pid=100) == "unknown"


def test_terminal_cycle_in_snapshot_does_not_hang():
    snap = _tree("100 90 a", "90 100 b")   # 100 ↔ 90 cycle
    assert state.terminal_kind(ps_text=snap, pid=100) == "unknown"


def test_terminal_real_process_returns_a_string():
    # Smoke: the real ps walk runs and never raises; result is a known label.
    kind = state.terminal_kind()
    assert kind in {
        "iterm", "apple-terminal", "tmux", "kitty", "wezterm",
        "vscode", "ghostty", "alacritty", "hyper", "warp", "unknown",
    }


# --- parse_ps_table / process_ancestry primitives --------------------------

def test_parse_ps_table_basic():
    table = state.parse_ps_table("100 90 /usr/bin/node claude\n90 1 -zsh\n")
    assert table[100] == (90, "/usr/bin/node claude")
    assert table[90] == (1, "-zsh")


def test_parse_ps_table_skips_malformed_rows():
    table = state.parse_ps_table("\nheader junk\n100 90 cmd\nbad line\n")
    assert table == {100: (90, "cmd")}


def test_process_ancestry_nearest_first():
    table = state.parse_ps_table(_tree(
        "100 90 child",
        "90 50 parent",
        "50 1 grandparent",
        "1 0 init",
    ))
    assert state.process_ancestry(100, table) == ["parent", "grandparent"]


# --- in_ai_maestro_agent_env (pure) ----------------------------------------

def test_agent_env_true_via_explicit_flag():
    assert state.in_ai_maestro_agent_env({"AIMAESTRO_AGENT": "1"}) is True


def test_agent_env_true_via_user_proposed_flag():
    # The user's literally-proposed spelling is honoured too.
    assert state.in_ai_maestro_agent_env({"THIS_IS_AIMAESTRO": "true"}) is True


def test_agent_env_explicit_flag_falsy_is_false():
    assert state.in_ai_maestro_agent_env({"AIMAESTRO_AGENT": "0"}) is False


def test_agent_env_true_via_amp_agent_id():
    assert state.in_ai_maestro_agent_env({"AMP_AGENT_ID": "abc123"}) is True


def test_agent_env_true_via_aid_auth():
    assert state.in_ai_maestro_agent_env({"AID_AUTH": "token"}) is True


def test_agent_env_false_without_signals():
    assert state.in_ai_maestro_agent_env({"PATH": "/usr/bin"}) is False
