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


# ---- provenance-marked orphan cleanup (TRDD-H9IBY95W) ---------------------

_MARKER = rules_installer.PROVENANCE_MARKER
_MARKED_BODY = f"<!-- {_MARKER} — installed by the janitor -->\n# Some rule\nbody\n"


def _mk_home(monkeypatch, tmp_path, *, user_installed: bool, data_dir: bool) -> Path:
    """Isolate a HOME with the janitor optionally user-installed (settings.json ref) and
    its data dir optionally present. Clears CLAUDE_PROJECT_DIR (the daemon has none)."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    if user_installed:
        (home / ".claude" / "settings.json").write_text(
            '{"enabledPlugins":["ai-maestro-janitor@marketplace"]}', encoding="utf-8"
        )
    if data_dir:
        (home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins").mkdir(
            parents=True, exist_ok=True
        )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return home


def test_shipped_rules_all_carry_the_provenance_marker():
    """Every real shipped rule under rules/ carries the marker — else the cleanup can't
    recognize it as janitor-installed and it would never be removed after uninstall."""
    rules_dir = _PROJECT_ROOT / "rules"
    md = sorted(rules_dir.glob("*.md"))
    assert md, "expected shipped rules under rules/"
    missing = [p.name for p in md if _MARKER not in p.read_text(encoding="utf-8")]
    assert not missing, f"shipped rules missing the provenance marker: {missing}"


def test_janitor_uninstalled_requires_no_scope_and_no_data_dir(tmp_path, monkeypatch):
    _mk_home(monkeypatch, tmp_path, user_installed=False, data_dir=False)
    assert rules_installer.janitor_uninstalled() is True
    # A present data dir alone → NOT uninstalled (installed elsewhere / --keep-data).
    _mk_home(monkeypatch, tmp_path, user_installed=False, data_dir=True)
    assert rules_installer.janitor_uninstalled() is False
    # A settings.json reference alone (e.g. still enabled, or DISABLED) → NOT uninstalled.
    _mk_home(monkeypatch, tmp_path, user_installed=True, data_dir=False)
    assert rules_installer.janitor_uninstalled() is False


def test_cleanup_removes_marked_user_rules_only_when_uninstalled(tmp_path, monkeypatch):
    home = _mk_home(monkeypatch, tmp_path, user_installed=False, data_dir=False)
    rules = home / ".claude" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    marked = rules / "commit-discipline.md"
    marked.write_text(_MARKED_BODY, encoding="utf-8")
    mine = rules / "my-own-rule.md"
    mine.write_text("# my own rule, no janitor marker\n", encoding="utf-8")

    removed = rules_installer.cleanup_user_orphans_if_uninstalled()
    assert str(marked) in removed
    assert not marked.exists(), "the janitor-marked orphan is removed"
    assert mine.exists(), "a user's own (unmarked) rule is NEVER removed"


def test_cleanup_is_noop_while_still_installed(tmp_path, monkeypatch):
    home = _mk_home(monkeypatch, tmp_path, user_installed=True, data_dir=True)
    rules = home / ".claude" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    marked = rules / "commit-discipline.md"
    marked.write_text(_MARKED_BODY, encoding="utf-8")

    assert rules_installer.cleanup_user_orphans_if_uninstalled() == []
    assert marked.exists(), "an installed janitor must never remove its own live rules"


def test_cleanup_never_touches_non_rule_or_memory_files(tmp_path, monkeypatch):
    home = _mk_home(monkeypatch, tmp_path, user_installed=False, data_dir=False)
    rules = home / ".claude" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "commit-discipline.md").write_text(_MARKED_BODY, encoding="utf-8")
    # A memory-store markdown OUTSIDE ~/.claude/rules/ (cleanup globs rules/*.md only).
    mem = home / ".claude" / "projects" / "slug" / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    note = mem / "some-memory.md"
    note.write_text(f"<!-- {_MARKER} -->\na memory note\n", encoding="utf-8")  # even WITH the marker
    # A non-.md file inside rules/ carrying the marker text.
    idx = rules / "index.db"
    idx.write_text(_MARKER, encoding="utf-8")

    rules_installer.cleanup_user_orphans_if_uninstalled()
    assert note.exists(), "cleanup must NEVER touch a memory store, even a marker-bearing one outside rules/"
    assert idx.exists(), "cleanup only removes *.md rule files, never other artifacts"


def test_remove_orphaned_rules_clears_redundant_project_mirror(tmp_path, monkeypatch):
    """User-scope install → the user rules dir is the only target; a janitor-marked copy
    in the PROJECT .claude/rules/ is a redundant orphan and is removed (issue #36)."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "settings.json").write_text(
        '{"enabledPlugins":["ai-maestro-janitor@marketplace"]}', encoding="utf-8"
    )
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "settings.json").write_text(
        '{"enabledPlugins":["ai-maestro-janitor@marketplace"]}', encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    proj_rules = project / ".claude" / "rules"
    proj_rules.mkdir(parents=True, exist_ok=True)
    orphan = proj_rules / "commit-discipline.md"
    orphan.write_text(_MARKED_BODY, encoding="utf-8")
    user_own = proj_rules / "my-own.md"
    user_own.write_text("# mine, unmarked\n", encoding="utf-8")

    removed = rules_installer.remove_orphaned_rules()
    assert str(orphan) in removed
    assert not orphan.exists(), "the redundant project mirror of a janitor rule is removed"
    assert user_own.exists(), "a user's own project rule is spared"


def test_installs_rule_to_project_scope(tmp_path, monkeypatch):
    """install_rules copies a shipped rule into <project>/.claude/rules/ with matching content."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE BODY v1\n")
    copied = rules_installer.install_rules(plugin)
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == "RULE BODY v1\n"
    assert str(dst) in copied


def test_idempotent_identical_content_skips(tmp_path, monkeypatch):
    """A second install with byte-identical content is a no-op (issue #37 content-exact)."""
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


def test_overwrite_on_same_size_different_content(tmp_path, monkeypatch):
    """Issue #37 blind spot: a rule edit that PRESERVES the byte count but changes
    content STILL overwrites — byte-exact comparison catches what a size-only check
    would silently skip (the stale-rule failure mode #37 is about)."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE BODY v1\n")
    rules_installer.install_rules(plugin)
    # Same byte length, different content — a size-only check would WRONGLY skip this.
    new_body = "RULE BODY v2\n"
    assert len(new_body) == len("RULE BODY v1\n")
    _make_plugin(plugin, new_body)
    copied = rules_installer.install_rules(plugin)
    assert dst.read_text(encoding="utf-8") == new_body
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


# ---- issue #73: the 3 IND governance rules shipped via rules_installer -----

# The universal (ai-maestro-INDEPENDENT) governance rules shipped by the janitor.
_IND_RULES = ("trdd-design-tasks.md", "prrd-design-rules.md", "universal-kanban.md")
# DEP-only overlays the janitor must NEVER ship — the ai-maestro server installs
# them into agent workdirs as aimaestro-*.md; the janitor's cleanup keeps ignoring
# their old (unmarked) hand-placed globals too.
_DEP_ONLY_RULES = ("trdd-approval-tiers.md", "manager-approval-defaults.md")


def test_ind_governance_rules_shipped_with_guard_block():
    """The 3 IND governance rules ship under rules/, each wrapped with the provenance
    marker AND the conditional inert-guard, and each keeps its body H1 + Layering note."""
    rules_dir = _PROJECT_ROOT / "rules"
    for name in _IND_RULES:
        p = rules_dir / name
        assert p.is_file(), f"expected shipped IND rule {name}"
        text = p.read_text(encoding="utf-8")
        assert _MARKER in text, f"{name} missing the provenance marker"
        assert "> [!IMPORTANT]" in text, f"{name} missing the conditional inert-guard"
        assert text.startswith("<!-- " + _MARKER), f"{name} guard must lead the file"
        assert "\n# " in text, f"{name} lost its body H1 heading under the wrap"
        # The IND "Layering note" naming the DEP overlay is kept verbatim (issue #73).
        assert "Layering note" in text, f"{name} lost its Layering note"


def test_dep_only_rules_are_not_shipped():
    """The two DEP-only overlays must NOT be shipped by the janitor (issue #73)."""
    rules_dir = _PROJECT_ROOT / "rules"
    for name in _DEP_ONLY_RULES:
        assert not (rules_dir / name).exists(), f"{name} must NOT ship with the janitor"


def test_ind_rules_install_and_are_content_idempotent(tmp_path, monkeypatch):
    """Installing the REAL shipped rules lands the 3 IND rules byte-identical to source,
    and a second install re-copies nothing — the acceptance criterion "byte-stable across
    sessions (content-idempotent)"."""
    rules_dst_dir = _isolate_project_scope(
        monkeypatch, tmp_path / "home", tmp_path / "proj"
    ).parent
    src_dir = _PROJECT_ROOT / "rules"
    copied = rules_installer.install_rules(_PROJECT_ROOT)
    for name in _IND_RULES:
        dst = rules_dst_dir / name
        assert dst.is_file(), f"{name} was not installed"
        assert dst.read_bytes() == (src_dir / name).read_bytes(), f"{name} not byte-identical to source"
        assert str(dst) in copied
    # Re-install is a no-op: the on-disk copies are already byte-exact.
    assert rules_installer.install_rules(_PROJECT_ROOT) == []


def test_ind_rule_takes_over_unmarked_same_named_file(tmp_path, monkeypatch):
    """Takeover semantics (issue #73): install_rules compares BYTES, not markers, so a
    user's pre-existing UNMARKED trdd-design-tasks.md is OVERWRITTEN by the janitor's
    wrapped IND copy — the content-based overwrite IS the one-shot migration. This pins
    that behavior so a future marker-gating of the install path can't silently break the
    takeover (marker-gating guards only the REMOVAL path, never the install)."""
    rules_dst_dir = _isolate_project_scope(
        monkeypatch, tmp_path / "home", tmp_path / "proj"
    ).parent
    rules_dst_dir.mkdir(parents=True, exist_ok=True)
    victim = rules_dst_dir / "trdd-design-tasks.md"
    victim.write_text("# OLD hand-placed global, no janitor marker\n", encoding="utf-8")
    assert _MARKER not in victim.read_text(encoding="utf-8")

    copied = rules_installer.install_rules(_PROJECT_ROOT)
    text = victim.read_text(encoding="utf-8")
    assert _MARKER in text, "the unmarked same-named file must be overwritten by the marked IND copy"
    assert text == (_PROJECT_ROOT / "rules" / "trdd-design-tasks.md").read_text(encoding="utf-8")
    assert str(victim) in copied


# ---- the context floor (TRDD-YRPUSIFY axis B) -----------------------------
#
# Everything in a `.claude/rules/` dir is loaded into the context PREFIX of every
# session AND every cold subagent, machine-wide. A byte shipped here is a byte
# re-written into cache by every fan-out agent that ever starts — which is why the
# bulky reference material moved to `<DATA>/rules-reference/` (read on demand, zero
# tokens until needed). These tests are the ratchet that stops the floor growing back.

# A RATCHET, not a budget: it may go DOWN, never up. Set after the 2026-07-11 burn
# investigation, when the 8 shipped rules totalled 112,889 B (~28k tokens) — 48% of the
# machine's whole rules floor — because three of them carried full schemas, transition
# matrices, grep cheat-sheets and migration guides. Moving those to rules/references/
# (read on demand) brought the corpus to 49,894 B, a 56% cut. The cap sits just above
# that with room for one small new rule. Raising it needs a measured justification:
# every byte here is re-written into cache by every cold subagent on the machine.
_RULES_FLOOR_CAP_BYTES = 52_000
_SINGLE_RULE_CAP_BYTES = 12_000


def test_shipped_rules_stay_under_the_context_floor_cap():
    """The whole shipped-rules corpus must stay under the floor cap — it is re-written
    into cache by every cold subagent, machine-wide."""
    md = sorted((_PROJECT_ROOT / "rules").glob("*.md"))
    total = sum(p.stat().st_size for p in md)
    assert total <= _RULES_FLOOR_CAP_BYTES, (
        f"shipped rules total {total} B > cap {_RULES_FLOOR_CAP_BYTES} B. "
        "Move reference material to rules/references/ (on-demand), do not grow the floor."
    )


def test_no_single_shipped_rule_is_a_reference_document():
    """No individual rule may balloon into a reference doc — that is what
    rules/references/ is for."""
    md = sorted((_PROJECT_ROOT / "rules").glob("*.md"))
    fat = [(p.name, p.stat().st_size) for p in md if p.stat().st_size > _SINGLE_RULE_CAP_BYTES]
    assert not fat, f"rules over the per-file cap (move detail to rules/references/): {fat}"


def test_references_are_never_installed_as_rules(tmp_path, monkeypatch):
    """rules/references/*.md must NOT land in a .claude/rules/ dir — putting them there
    would re-inflate the very context floor they exist to avoid."""
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "# demo\n")
    refs = plugin / "rules" / "references"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "big-full.md").write_text("x" * 5000, encoding="utf-8")

    home = tmp_path / "home"
    project = tmp_path / "project"
    dst = _isolate_project_scope(monkeypatch, home, project)
    rules_installer.install_rules(plugin)

    assert dst.exists(), "the real rule is installed"
    assert not (dst.parent / "big-full.md").exists(), "a reference doc must NEVER be installed as a rule"
    assert not (dst.parent / "references").exists()


def test_install_references_writes_to_the_data_dir(tmp_path, monkeypatch):
    """The full docs land in <DATA>/rules-reference/ — persistent, and outside every
    context-loaded rules dir."""
    plugin = tmp_path / "plugin"
    refs = plugin / "rules" / "references"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "trdd-design-tasks-full.md").write_text("FULL DOC BODY", encoding="utf-8")
    _mk_home(monkeypatch, tmp_path, user_installed=True, data_dir=True)

    written = rules_installer.install_references(plugin)
    dst = rules_installer.references_dir() / "trdd-design-tasks-full.md"
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == "FULL DOC BODY"
    assert str(dst) in written
    # Byte-identical second call is a no-op (same idempotency contract as install_rules).
    assert rules_installer.install_references(plugin) == []


def test_install_references_is_a_noop_without_a_references_dir(tmp_path, monkeypatch):
    """A plugin with no rules/references/ installs nothing and never raises."""
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "# demo\n")
    _mk_home(monkeypatch, tmp_path, user_installed=True, data_dir=True)
    assert rules_installer.install_references(plugin) == []


def test_every_slimmed_rule_points_at_its_full_reference():
    """A rule whose detail moved out MUST tell the reader where the full doc is, or the
    knowledge is simply lost. Each shipped reference doc must be named by its rule."""
    refs = sorted((_PROJECT_ROOT / "rules" / "references").glob("*-full.md"))
    assert refs, "expected the on-demand reference docs"
    for ref in refs:
        rule = _PROJECT_ROOT / "rules" / ref.name.replace("-full.md", ".md")
        assert rule.is_file(), f"reference {ref.name} has no owning rule"
        body = rule.read_text(encoding="utf-8")
        assert ref.name in body, f"{rule.name} does not point at its full reference {ref.name}"
        assert "rules-reference" in body, f"{rule.name} does not give the reference dir path"
