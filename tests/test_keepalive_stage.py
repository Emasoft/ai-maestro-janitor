"""Closure-stager contract for the L0 keepalive (TRDD-71ABD7V7).

Proves the SHAPE 2 DATA stage is (1) bounded and excludes the ~200 pattern libs,
(2) actually SUFFICIENT — a REAL subprocess that imports the staged entry (which static-
imports the staged daemon) must succeed, the completeness guarantee static analysis alone
cannot give — and (3) byte-identical to the scanned repo files (the verbatim-copy invariant).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))

import keepalive_stage  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_janitor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every janitor global-state / DATA / HOME path to a per-test tmp tree so no
    keepalive test can read or write the real ~/.claude/janitor-global-state/ or the real
    plugin DATA dir. A frozen module constant (keepalive_boot's old _LOG_DIR,
    launchd_keepalive._DATA_DIR) let these tests pollute production state and corrupt the
    real staged closure, driving a 39 GB fseventsd runaway (TRDD-ZNN0UK5K). Env-based so the
    subprocess that re-imports the entry (→ verify_or_restage) inherits the SAME isolated
    tree instead of writing the real boot log."""
    home = tmp_path / "_home"
    # Keep the FIXED DATA suffix so data_dir()'s shape assertion still holds on a tmp tree.
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


def test_closure_is_bounded_and_excludes_pattern_libs() -> None:
    """The daemon closure stays small (a few dozen files) and contains none of the
    ~200 *_patterns.py libs.

    The bound guards against an import accidentally dragging in a large subtree; it
    is deliberately loose (headroom for legitimate new daemon modules) because the
    sharp assertion is the pattern-lib leak check below. Raised 30 -> 40 when
    `daemon_path.py` legitimately joined the closure (TRDD-VQ4LX7ND), and 40 -> 45
    when `oauth_rotator/burn_gate.py` did the same (TRDD-FQXBURNR, 2026-08-02) — the
    burn-aware rotation gate is genuinely daemon-imported, so the cap was simply stale
    and the suite had been red since. Headroom widened to 45 rather than nudged to 41
    so the NEXT legitimate module does not re-break the build; a leap past 50 is the
    signal this bound exists to catch.

    45 -> 50 when `cross_project_issue.py` joined (TRDD-WP7TCRME Rule 4, 2026-08-12): the
    daemon files fleet findings on the repos that own them, and the module MUST be staged —
    a lazy import would keep this number small by making the feature fail under launchd,
    where the daemon runs from the staged copy and nothing else is importable.

    50 -> 55 when `gh_notify_inbox.py` joined (TRDD-079778RM, 2026-08-20) — and that module
    is the WORKED EXAMPLE of the sentence above, not another routine bump. Its first version
    kept the closure at 50 by having the daemon shell out to
    `scripts/gh_issues_monitor/gh_notify_poll.py` instead of importing anything. That tree is
    not staged, so on the daemon's own copy the path did not exist: the chore logged
    `done in 0s` every 60 s and never wrote a byte, while every test here stayed green
    because tests run from the repo. Shipped in 3.3.25, caught only by watching the live
    daemon. Keeping this number down by NOT importing is how the feature breaks, so the
    bound is raised rather than defended.
    """
    closure = keepalive_stage.daemon_closure(SCRIPTS)
    assert 0 < len(closure) <= 55, f"closure unexpectedly large: {len(closure)}"
    leaked = [p.name for p in closure if p.name.endswith("_patterns.py")]
    assert not leaked, f"pattern libs leaked into the closure: {leaked}"


def test_closure_excludes_detectors_and_reuses_wake_modules() -> None:
    """D1 v1 balloon guard (TRDD-X07E7HTN, MF5): the daemon-owned rate-limit wake reuses ONLY
    modules already in the L0 daemon closure (fleet_inject / fleet_scan / global_state / state)
    — so the closure MUST contain ZERO `detectors/` paths and ZERO `*_patterns.py`, and stay
    small. If the wake work ever imports a detector or a pattern lib into the L0 daemon, this
    FAILS the build instead of letting the daemon crash-loop on a bloated stage exactly in the
    all-sessions-down scenario the keepalive exists for."""
    closure = keepalive_stage.daemon_closure(SCRIPTS)
    assert 0 < len(closure) <= 55, f"closure unexpectedly large: {len(closure)}"
    detectors = [str(p) for p in closure if "detectors" in p.parts]
    assert not detectors, f"detector modules leaked into the L0 daemon closure: {detectors}"
    assert not [p.name for p in closure if p.name.endswith("_patterns.py")]
    # The wake's actuation modules are already staged (it adds NO new import), so their
    # presence proves the reuse rather than a new dependency edge.
    names = {p.name for p in closure}
    for required in ("fleet_inject.py", "fleet_scan.py", "global_state.py", "state.py"):
        assert required in names, f"{required} must already be in the closure (wake reuses it)"


def test_closure_includes_entry_and_daemon() -> None:
    """The launched entry and the daemon it imports are both in the stage list."""
    names = {p.name for p in keepalive_stage.daemon_closure(SCRIPTS)}
    assert "daemon_keepalive_entry.py" in names
    assert "daemon.py" in names


def test_closure_includes_daemon_path_module() -> None:
    """`daemon_path` MUST be staged: the launchd daemon imports it at startup, so a
    closure that omitted it would raise ImportError on every boot -> OS relaunch ->
    crash-loop -> the C4 breaker quarantines a perfectly good version. The closure is
    computed by BFS over imports, so this holds automatically; the test pins it so a
    future refactor of the seed list cannot silently drop it. (TRDD-VQ4LX7ND)
    """
    names = {p.name for p in keepalive_stage.daemon_closure(SCRIPTS)}
    assert "daemon_path.py" in names


def test_staged_closure_really_imports_via_the_entry(tmp_path: Path) -> None:
    """Staging to a bare tree and importing the entry (→ static import daemon) from it succeeds."""
    staged = keepalive_stage.stage_closure(SCRIPTS, tmp_path)
    assert staged, "nothing was staged"
    # Exactly the launch path minus main(): only the entry's dir on sys.path; the entry +
    # daemon self-bootstrap lib/ + oauth_rotator/ from their own __file__.
    code = (
        f"import sys; sys.path.insert(0, {str(tmp_path)!r}); "
        "import daemon_keepalive_entry; print('ok')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"staged daemon failed to import:\n{proc.stderr}"
    assert "ok" in proc.stdout


def test_staged_files_are_verbatim_copies(tmp_path: Path) -> None:
    """Every staged file is byte-identical to its scanned repo source (no edit/template)."""
    keepalive_stage.stage_closure(SCRIPTS, tmp_path)
    for src in keepalive_stage.daemon_closure(SCRIPTS):
        dst = tmp_path / src.relative_to(SCRIPTS)
        assert dst.read_bytes() == src.read_bytes(), f"staged copy differs from source: {src.name}"


# ---------------------------------------------------------------------------
# The source-tree write guard (TRDD-RYZCVVKA).
#
# On 2026-07-11 this repo's entire daemon closure was overwritten with the INSTALLED
# plugin's v0.39.0 copies — silently reverting committed work and clearing exec bits. The
# mechanism is a stage whose destination resolved to the repo instead of the DATA dir. The
# closure is only EVER staged into the DATA dir, so a source-repo destination is always a
# bug; refusing the write makes the whole class impossible instead of merely detectable.
# ---------------------------------------------------------------------------
def _fake_plugin_repo(root: Path) -> Path:
    """A directory that looks like a plugin SOURCE checkout: a git work tree whose root
    carries a plugin manifest."""
    (root / ".git").mkdir(parents=True)
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    return root


def test_stage_refuses_a_plugin_source_checkout(tmp_path: Path) -> None:
    """The incident, as a test: staging into a plugin source tree must RAISE, and must not
    write a single file."""
    repo = _fake_plugin_repo(tmp_path / "repo")
    dest = repo / "scripts"

    with pytest.raises(keepalive_stage.UnsafeStageDestination, match="SOURCE checkout"):
        keepalive_stage.stage_closure(SCRIPTS, dest)

    assert not (dest / "daemon.py").exists()  # nothing was written


def test_stage_allows_a_git_repo_that_is_not_a_plugin(tmp_path: Path) -> None:
    """THE false-positive that would matter more than the bug. Plenty of people keep `~` or
    `~/.claude` in a dotfiles repo, and the REAL data dir lives under `~/.claude/plugins/
    data/…`. A naive "inside any git repo" guard would refuse the legitimate production
    stage and silently kill the L0 keepalive. Only a PLUGIN checkout (git + a manifest at
    the root) may be refused."""
    dotfiles = tmp_path / "dotfiles"
    (dotfiles / ".git").mkdir(parents=True)          # a git repo, but NOT a plugin
    dest = dotfiles / ".claude" / "plugins" / "data" / "janitor" / "scripts"

    staged = keepalive_stage.stage_closure(SCRIPTS, dest)

    assert (dest / "daemon.py").is_file()
    assert staged


def test_stage_allows_an_ordinary_destination(tmp_path: Path) -> None:
    """No git anywhere above it — the plain case must keep working."""
    dest = tmp_path / "data" / "scripts"
    keepalive_stage.stage_closure(SCRIPTS, dest)
    assert (dest / "daemon.py").is_file()


def test_this_repo_is_recognised_as_a_plugin_source_checkout() -> None:
    """The guard must actually fire on the real thing it failed to prevent: THIS repo's
    scripts dir. A predicate that refuses a synthetic fixture but not the actual victim
    would be theatre."""
    assert keepalive_stage.is_plugin_source_checkout(SCRIPTS) is True
