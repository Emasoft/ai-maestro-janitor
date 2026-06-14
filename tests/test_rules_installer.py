"""Tests for rules_installer.install_rules — behavior + the atomic-write fix.

install_rules copies plugin-shipped rules into the active scope's
.claude/rules/. It runs per-session (SessionStart hook), so N sessions can
write the same file concurrently; the copy is now atomic (tmp + os.replace)
to keep that torn-free. These tests pin the install / idempotency / overwrite
behavior (previously untested) and assert the atomic write leaves no temp
residue. HOME + CLAUDE_PROJECT_DIR are redirected to tmp dirs so the real
~/.claude/rules/ is never read or written.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import rules_installer  # noqa: E402

_DST_NAME = "demo-rule.md"


def _make_plugin(plugin_root: Path, body: str) -> None:
    rules = plugin_root / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / _DST_NAME).write_text(body, encoding="utf-8")


def _isolate_project_scope(monkeypatch, home: Path, project: Path) -> Path:
    # Redirect HOME so the real ~/.claude is never touched (user-scope is then
    # absent → only project scope fires), and point CLAUDE_PROJECT_DIR at tmp.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    claude = project / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "settings.json").write_text(
        '{"enabledPlugins":["ai-maestro-janitor@marketplace"]}', encoding="utf-8"
    )
    return claude / "rules" / _DST_NAME


def test_installs_rule_to_project_scope(tmp_path, monkeypatch):
    """install_rules copies a shipped rule into <project>/.claude/rules/ with matching content."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE BODY v1\n")
    copied = rules_installer.install_rules(plugin)
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == "RULE BODY v1\n"
    assert str(dst) in copied


def test_idempotent_same_size_skips(tmp_path, monkeypatch):
    """A second install with identical content (same byte size) is a no-op."""
    _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE BODY v1\n")
    rules_installer.install_rules(plugin)
    assert rules_installer.install_rules(plugin) == []


def test_overwrite_on_size_change(tmp_path, monkeypatch):
    """A source whose byte size changed overwrites the installed copy."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE BODY v1\n")
    rules_installer.install_rules(plugin)
    _make_plugin(plugin, "RULE BODY v2 - now a different length\n")
    copied = rules_installer.install_rules(plugin)
    assert dst.read_text(encoding="utf-8") == "RULE BODY v2 - now a different length\n"
    assert str(dst) in copied


def test_user_scope_wins_no_project_copy(tmp_path, monkeypatch):
    """When the plugin is installed at BOTH user and project scope, the rule goes
    ONLY to the user scope — no redundant project-local copy (issue #36). User-
    scope rules already load for every project, so a project copy is pure noise."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    user_claude = home / ".claude"
    user_claude.mkdir(parents=True)
    (user_claude / "settings.json").write_text(
        '{"enabledPlugins":["ai-maestro-janitor@mp"]}', encoding="utf-8"
    )
    proj_claude = project / ".claude"
    proj_claude.mkdir(parents=True)
    (proj_claude / "settings.json").write_text(
        '{"enabledPlugins":["ai-maestro-janitor@mp"]}', encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE BODY\n")
    copied = rules_installer.install_rules(plugin)

    user_dst = user_claude / "rules" / _DST_NAME
    proj_dst = proj_claude / "rules" / _DST_NAME
    assert user_dst.is_file(), "rule must be installed at user scope"
    assert not proj_dst.exists(), "no redundant project-local copy (user-scope wins)"
    assert str(user_dst) in copied
    assert str(proj_dst) not in copied


def test_atomic_write_leaves_no_temp_residue(tmp_path, monkeypatch):
    """The atomic copy (tmp + os.replace) leaves no stray .tmp files behind."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE BODY v1\n")
    rules_installer.install_rules(plugin)
    leftovers = [p.name for p in dst.parent.iterdir() if p.name != _DST_NAME]
    assert leftovers == [], f"unexpected temp residue: {leftovers}"
