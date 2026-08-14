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

import math
import re
import sys
from pathlib import Path

import tiktoken

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import rules_installer  # noqa: E402

_DST_NAME = "demo-rule.md"


def _body(path: Path) -> bytes:
    """The installed file MINUS its monotonic stamp line — i.e. the shipped content.

    Since #141 every installed file leads with a `version=`/`sha=` stamp, so a raw byte-compare
    against the source no longer holds. The BODY is what must still match exactly, and asserting on
    it (rather than loosening to a substring check) keeps these tests catching a truncated or
    mangled copy.
    """
    return rules_installer.split_stamp(path.read_bytes())[1]


def _body_text(path: Path) -> str:
    return _body(path).decode("utf-8")


def _make_plugin(plugin_root: Path, body: str, *, version: str | None = None) -> None:
    rules = plugin_root / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / _DST_NAME).write_text(body, encoding="utf-8")
    if version is not None:
        meta = plugin_root / ".claude-plugin"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "plugin.json").write_text(
            '{"name":"ai-maestro-janitor","version":"%s"}' % version, encoding="utf-8"
        )


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
    assert _body_text(dst) == "RULE BODY v1\n"
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
    assert _body_text(dst) == "RULE BODY v2 - now a different length\n"
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
    assert _body_text(dst) == new_body
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
        assert _body(dst) == (src_dir / name).read_bytes(), f"{name} not byte-identical to source"
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
    text = _body_text(victim)
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
#
# MEASURED RAISE 52_000 -> 52_400 (D5, TRDD-82JRK0CY, 2026-07-23): the ratified heartbeat-
# protocol shrink adds the explicit `[janitor-quiet]` idle-fire token + the "act on EACH bare
# token" forgery-hardening reframe to janitor-heartbeat-protocol.md. The corpus was AT the cap
# (52,000 B exactly), so a net protocol addition has no redundant old content to displace; the
# rule was compressed to its informational floor (3,856 B, +275 B vs the old 3,581 B — the
# reframe already cut the verbose intermediate drafts). The +275 B (~69 tokens) buys a
# diagnosable quiet path + a closed main()-payload forgery gap on the SURVIVAL-critical
# overnight-continuity rule; over-compressing it further would be a reliability false economy.
# This is the "measured justification" the ratchet above requires. Bring it back DOWN if a
# future rule move frees room.
#
# MEASURED RAISE 52_400 -> 53_300 (janitor#104 + janitor#116/#93, 2026-07-28): two FIELD-REPORTED
# defects in `trdd-design-tasks.md`, both reported by other fleet members against the shipped rule.
# (1) The rule said lookups are case-insensitive and then shipped a case-SENSITIVE `find -name`;
# agents paste the command, so the documented resume lookup failed on the 76% of one live board's
# ids that are legacy lowercase — and the same flag in the COLLISION check calls a case-folding id
# free, so the write silently overwrites an existing card on a case-insensitive filesystem. (2) §12
# "terminal columns are frozen" forbade, as written, the very edit that CLOSES a card, so the
# archival protocol was unimplementable and `published → completed` destroyed the shipped fact;
# ai-maestro#93 is open on that contradiction. Both fixes are normative rule TEXT — there is no
# reference-material equivalent to displace, and the corpus was at 52,395 B (5 B of headroom), so
# nothing redundant existed to trade against.
# Paid for as far as honestly possible first: the additions were +967 B raw and the same file was
# compressed by ~125 B (scope-routing prose, the STATE-block checklist, the authoring recipe) for a
# net +842 B (~210 tokens). Compressing further would have deleted normative content to satisfy a
# byte budget — the false economy this comment block already warns about. Bring it back DOWN when a
# rule move frees room.
#
# MEASURED LOWER 53_300 -> 53_100, and the metric now counts what is actually INSTALLED
# (#141/#150, 2026-07-31). Two things happened at once and they must not be netted silently:
#   +230 B  the #150 fix — the memory-assignment sidecar named ABSOLUTELY plus the STOP-don't-guess
#           clause. Normative text; it landed over the old cap, which is how this was found.
#   +432 B  the monotonic install stamp (#141) — 54 B on each of the 8 INSTALLED copies. The old
#           measurement read the repo sources, which carry no stamp, so it under-reported the real
#           machine floor. The cap is therefore RE-BASED onto the installed size (53_300 + 432 =
#           53_732, rounded to 53_700): same strictness, honest metric. Calling a metric change a
#           tightening would be the dishonest way to book this.
#   -448 B  compressing the 8 identical provenance header comments (228 B -> 172 B each). Pure
#           boilerplate: it keeps the marker, the "safe to delete after uninstall", and the "never a
#           MEMORY store" guardrail, and drops only wording.
# Measured installed floor: 53,400 B — 16 B BELOW the pre-change installed floor of 53,416 B, so the
# stamp is fully paid for. It also bought the smallest form that does the job: version only, no
# digest (an integrity field nothing verifies is decoration charged to every cold subagent).
_RULES_FLOOR_CAP_BYTES = 53_700
_SINGLE_RULE_CAP_BYTES = 12_000


def _installed_size(path: Path) -> int:
    """Bytes this rule occupies ONCE INSTALLED — source plus its monotonic stamp line.

    The stamp (#141) is added at install time, so measuring the repo source alone under-reports the
    real context floor by one stamp per rule. The floor is charged per cold subagent, machine-wide,
    so it has to be measured as the agent actually receives it.
    """
    return len(rules_installer._stamped_bytes(path.read_bytes(), "0.66.1"))


def test_shipped_rules_stay_under_the_context_floor_cap():
    """The whole shipped-rules corpus must stay under the floor cap — it is re-written
    into cache by every cold subagent, machine-wide."""
    md = sorted((_PROJECT_ROOT / "rules").glob("*.md"))
    total = sum(_installed_size(p) for p in md)
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
    assert _body_text(dst) == "FULL DOC BODY"
    assert str(dst) in written
    # Byte-identical second call is a no-op (same idempotency contract as install_rules).
    assert rules_installer.install_references(plugin) == []


def test_install_references_is_a_noop_without_a_references_dir(tmp_path, monkeypatch):
    """A plugin with no rules/references/ installs nothing and never raises."""
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "# demo\n")
    _mk_home(monkeypatch, tmp_path, user_installed=True, data_dir=True)
    assert rules_installer.install_references(plugin) == []


# ---- issue #141: the installed contract must only ever move FORWARD ------

def test_the_guard_refuses_an_older_version_over_a_newer_one(tmp_path, monkeypatch):
    """THE regression. A host keeps several cached plugin versions and any session may run any of
    them; before this, `install_rules` overwrote on ANY byte difference, in EITHER direction, so the
    installed rule converged on whichever session started LAST. Measured live:
    `~/.claude/rules/janitor-heartbeat-protocol.md` was 0.60.1's copy while 0.66.1 was cached — six
    versions of contract fixes silently reverted, including the `[janitor-quiet]` marker the
    dispatcher emits but that older rule does not list, which the rule's own security clause tells an
    agent to refuse. Newest must win regardless of who runs last.
    """
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")

    new_plugin = tmp_path / "plugin-new"
    _make_plugin(new_plugin, "RULE v0.66.1 — documents [janitor-quiet]\n", version="0.66.1")
    assert rules_installer.install_rules(new_plugin) == [str(dst)]

    old_plugin = tmp_path / "plugin-old"
    _make_plugin(old_plugin, "RULE v0.60.1 — no [janitor-quiet] here\n", version="0.60.1")
    assert rules_installer.install_rules(old_plugin) == [], "an older session must not reinstall"
    assert _body_text(dst) == "RULE v0.66.1 — documents [janitor-quiet]\n"


def test_a_newer_version_still_installs_over_an_older_one(tmp_path, monkeypatch):
    """The guard is one-directional — it must not freeze the rule. Shipping a fix has to reach the
    host, which is the entire reason overwrite-on-difference existed in the first place."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")

    old_plugin = tmp_path / "plugin-old"
    _make_plugin(old_plugin, "RULE v0.60.1\n", version="0.60.1")
    rules_installer.install_rules(old_plugin)

    new_plugin = tmp_path / "plugin-new"
    _make_plugin(new_plugin, "RULE v0.66.1\n", version="0.66.1")
    assert rules_installer.install_rules(new_plugin) == [str(dst)]
    assert _body_text(dst) == "RULE v0.66.1\n"


def test_same_version_with_changed_content_still_installs(tmp_path, monkeypatch):
    """Development on an unbumped version must keep working — the guard compares versions, and an
    equal version is NOT newer, so content changes still land."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "RULE a\n", version="0.66.1")
    rules_installer.install_rules(plugin)
    _make_plugin(plugin, "RULE b\n", version="0.66.1")
    assert rules_installer.install_rules(plugin) == [str(dst)]
    assert _body_text(dst) == "RULE b\n"


def test_an_unstamped_file_is_taken_over_even_by_an_old_version(tmp_path, monkeypatch):
    """First run, a pre-#141 installed copy, and a hand-placed global all look the same: no stamp.
    All three must be taken over, or an upgrade could never establish the stamp it needs to guard —
    and the one-shot takeover of a user's hand-placed same-named global (issue #73) would break."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("# hand-placed, no stamp\n", encoding="utf-8")

    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "SHIPPED RULE\n", version="0.1.0")
    assert rules_installer.install_rules(plugin) == [str(dst)]
    assert _body_text(dst) == "SHIPPED RULE\n"


def test_an_unknown_source_version_never_blocks_the_install(tmp_path, monkeypatch):
    """An unreadable plugin.json must degrade to the OLD behaviour, not to a frozen file.

    The guard's only job is to stop an older version overwriting a newer one. If the source version
    is unknown we cannot make that judgement — and refusing would lock the destination against every
    future install, which is the failure the guard exists to prevent, inverted and permanent.
    """
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    stamped = tmp_path / "plugin-stamped"
    _make_plugin(stamped, "RULE from 9.9.9\n", version="9.9.9")
    rules_installer.install_rules(stamped)

    unknown = tmp_path / "plugin-unknown"          # no .claude-plugin/plugin.json at all
    _make_plugin(unknown, "RULE from an unversioned tree\n")
    assert rules_installer.install_rules(unknown) == [str(dst)]
    assert _body_text(dst) == "RULE from an unversioned tree\n"


def test_the_stamp_records_the_writing_version(tmp_path, monkeypatch):
    """The stamp is also the DIAGNOSTIC. Finding the live skew took real work precisely because the
    installed file carried no provenance; `head -1` must now answer "which version wrote this?"."""
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "BODY\n", version="1.2.3")
    rules_installer.install_rules(plugin)

    first = dst.read_text(encoding="utf-8").splitlines()[0]
    assert "ai-maestro-janitor:rule-stamp" in first
    assert "version=1.2.3" in first
    assert rules_installer.split_stamp(dst.read_bytes())[0] == "1.2.3"


def test_an_unversioned_source_stamps_unknown_and_stays_replaceable(tmp_path, monkeypatch):
    """A stamp must never write a PARSEABLE placeholder for an unknown version.

    `0.0.0` would outrank a genuinely unknown source on the next install and could freeze the file
    permanently; `unknown` sorts below every real version and therefore cannot.
    """
    dst = _isolate_project_scope(monkeypatch, tmp_path / "home", tmp_path / "proj")
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, "BODY\n")  # no plugin.json
    rules_installer.install_rules(plugin)
    assert rules_installer.split_stamp(dst.read_bytes())[0] == "unknown"

    later = tmp_path / "plugin-later"
    _make_plugin(later, "NEWER BODY\n")  # also unversioned — must still replace it
    assert rules_installer.install_rules(later) == [str(dst)]
    assert _body_text(dst) == "NEWER BODY\n"


def test_references_are_guarded_the_same_way(tmp_path, monkeypatch):
    """The rules POINT at these docs, so an older session reverting a reference makes the rule cite
    content that no longer says what the rule promises — a skew harder to notice than a stale rule,
    because nothing surfaces it until an agent reads the reference and acts on it."""
    _mk_home(monkeypatch, tmp_path, user_installed=True, data_dir=True)

    def _mk_refs(root: Path, body: str, version: str) -> None:
        refs = root / "rules" / "references"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "demo-full.md").write_text(body, encoding="utf-8")
        meta = root / ".claude-plugin"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "plugin.json").write_text(
            '{"name":"ai-maestro-janitor","version":"%s"}' % version, encoding="utf-8"
        )

    new_plugin = tmp_path / "ref-new"
    _mk_refs(new_plugin, "FULL DOC v2\n", "0.66.1")
    rules_installer.install_references(new_plugin)

    old_plugin = tmp_path / "ref-old"
    _mk_refs(old_plugin, "FULL DOC v1\n", "0.60.1")
    assert rules_installer.install_references(old_plugin) == []

    dst = rules_installer.references_dir() / "demo-full.md"
    assert _body_text(dst) == "FULL DOC v2\n"


# ---- should_install: the pure decision -----------------------------------

def test_should_install_decision_table():
    """The four branches, stated directly, so a future edit that inverts one is caught here rather
    than six versions later on a user's machine."""
    assert rules_installer.should_install(None, False, "1.0.0")[0] is True       # unstamped
    assert rules_installer.should_install("1.0.0", True, "2.0.0")[0] is False    # already this body
    assert rules_installer.should_install("2.0.0", False, "1.0.0")[0] is False   # THE guard
    assert rules_installer.should_install("1.0.0", False, "2.0.0")[0] is True    # source newer
    assert rules_installer.should_install("1.0.0", False, "1.0.0")[0] is True    # same version
    assert rules_installer.should_install("2.0.0", False, "")[0] is True         # unknown source


def test_semver_comparison_is_numeric_not_lexicographic():
    """0.9.0 vs 0.10.0 is the classic trap: string order says 0.9.0 wins and would let a session six
    releases old revert the newest contract — exactly the bug, re-introduced by a sloppy compare."""
    assert rules_installer.should_install("0.9.0", False, "0.10.0")[0] is True
    assert rules_installer.should_install("0.10.0", False, "0.9.0")[0] is False


def test_split_stamp_leaves_an_unstamped_file_whole():
    """An unstamped file's body is the WHOLE file, so a pre-#141 copy compares exactly as the old
    byte-compare did. If this mis-parsed, every existing install would look content-changed and be
    rewritten on every session."""
    assert rules_installer.split_stamp(b"# a rule\nbody\n") == (None, b"# a rule\nbody\n")
    assert rules_installer.split_stamp(b"no trailing newline") == (None, b"no trailing newline")
    stamped = b"<!-- ai-maestro-janitor:rule-stamp version=1.2.3 -->\nbody\n"
    assert rules_installer.split_stamp(stamped) == ("1.2.3", b"body\n")


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


def test_every_full_reference_pointer_resolves_to_a_shipped_file():
    """The COMPLEMENT of the test above, and the direction that actually goes wrong.

    That one iterates over references that EXIST and proves each has an owning rule, so a rule
    pointing at a reference that was never written — or was renamed — is invisible to it. This
    walks the pointers instead. It is the failure mode the corpus cap actively pushes you into:
    the sanctioned way to stay under the cap is to move detail out and leave a pointer, so every
    trim is a chance to ship a pointer with nothing behind it. A reader who follows one and finds
    nothing does not go looking — the knowledge reads as deleted."""
    shipped = {p.name for p in (_PROJECT_ROOT / "rules" / "references").glob("*.md")}
    pointer = re.compile(r"rules-reference/([A-Za-z0-9._-]+\.md)")
    dangling = [
        (rule.name, name)
        for rule in sorted((_PROJECT_ROOT / "rules").glob("*.md"))
        for name in pointer.findall(rule.read_text(encoding="utf-8"))
        if name not in shipped
    ]
    assert not dangling, f"rules point at references that are not shipped: {dangling}"


_SKILL_TOKEN_CAP = 5000


def _skill_body_claude_tokens(path: Path) -> int:
    """Reproduce CPV's own per-skill measure exactly (validated 2026-08-12 against CPV's
    reported number, byte for byte): strip the YAML frontmatter, encode the remainder with
    o200k_base, multiply by 1.3, round up. A char-count proxy would drift from the authority
    it stands in for, so a green run here would stop being evidence (TRDD-IAJS6M9Z)."""
    src = path.read_text(encoding="utf-8")
    body = re.sub(r"\A---\n.*?\n---\n", "", src, flags=re.S)
    enc = tiktoken.get_encoding("o200k_base")
    return math.ceil(len(enc.encode(body)) * 1.3)


def test_every_skill_body_stays_under_the_context_token_cap():
    """Every skills/*/SKILL.md body must stay under the 5000-Claude-token cap CPV enforces
    at publish stage 4/11 — locally, so a breach fails in seconds instead of costing a full
    publish run (lint + the whole test suite) to discover it (TRDD-IAJS6M9Z)."""
    skills = sorted((_PROJECT_ROOT / "skills").glob("*/SKILL.md"))
    # Measure once per skill: the comprehension's condition and its value would otherwise
    # each encode the same body, doubling the BPE work on every run of the suite.
    measured = [(p.parent.name, _skill_body_claude_tokens(p)) for p in skills]
    over = [(name, tokens) for name, tokens in measured if tokens > _SKILL_TOKEN_CAP]
    assert not over, (
        f"skills over the per-skill token cap ({_SKILL_TOKEN_CAP}): {over}. "
        "Move detail to that skill's references/ dir, do not grow the cap."
    )


_SKILL_DESC_TOKEN_CAP = 200


def _skill_description_claude_tokens(path: Path) -> int:
    """Same measure as the body gate, applied to the frontmatter `description:` alone.

    The value is read as a YAML scalar (it may be folded across lines) and whitespace is
    collapsed before encoding, because CPV measures the STRING the harness ends up with,
    not the source layout — a wrapped description and a single-line one of the same words
    must score identically or this gate would disagree with the authority it stands in for.
    """
    src = path.read_text(encoding="utf-8")
    m = re.search(r"^description:\s*(.*?)(?=\n[a-zA-Z-]+:\s|\n---)", src, flags=re.S | re.M)
    if m is None:
        return 0
    desc = " ".join(m.group(1).split())
    enc = tiktoken.get_encoding("o200k_base")
    return math.ceil(len(enc.encode(desc)) * 1.3)


def test_every_skill_description_stays_under_the_frontmatter_token_cap():
    """Every skills/*/SKILL.md `description:` must stay under CPV's 200-Claude-token cap.

    The BODY cap already had this local gate; the DESCRIPTION cap did not, and was enforced
    only by CPV at publish time. On 2026-08-14 that cost a full publish: ~45 minutes of green
    lint and 15,414 green tests, then a MAJOR at the CPV stage for ONE description at 214
    tokens. Same lesson as TRDD-IAJS6M9Z, one field over: a limit whose only enforcement is
    45 minutes away is a limit you discover by violating it.

    Six descriptions currently sit within 10 tokens of the cap, so the next routine wording
    edit is what this catches.
    """
    skills = sorted((_PROJECT_ROOT / "skills").glob("*/SKILL.md"))
    measured = [(p.parent.name, _skill_description_claude_tokens(p)) for p in skills]
    over = [(name, tokens) for name, tokens in measured if tokens > _SKILL_DESC_TOKEN_CAP]
    assert not over, (
        f"skill descriptions over the cap ({_SKILL_DESC_TOKEN_CAP}): {over}. "
        "A description states WHEN to invoke the skill; move the how/why into the body."
    )
