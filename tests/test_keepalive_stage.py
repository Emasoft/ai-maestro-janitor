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
    """The daemon closure is small (~16 files) and contains none of the ~200 *_patterns.py libs."""
    closure = keepalive_stage.daemon_closure(SCRIPTS)
    assert 0 < len(closure) <= 30, f"closure unexpectedly large: {len(closure)}"
    leaked = [p.name for p in closure if p.name.endswith("_patterns.py")]
    assert not leaked, f"pattern libs leaked into the closure: {leaked}"


def test_closure_includes_entry_and_daemon() -> None:
    """The launched entry and the daemon it imports are both in the stage list."""
    names = {p.name for p in keepalive_stage.daemon_closure(SCRIPTS)}
    assert "daemon_keepalive_entry.py" in names
    assert "daemon.py" in names


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
