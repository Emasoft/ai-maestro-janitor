"""#321 — one command flips BOTH sides of OAuth rotation: the janitor opt-in flag and the
ai-maestro server's R16 flag file (``<home>/.aimaestro/oauth-rotator-tick.enabled``, presence
enables, the server only does ``existsSync``). Real temp dirs, real subprocess, no mocks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "oauth_rotation_toggle.py"


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    """A fake plugin DATA dir and a fake HOME."""
    data, home = tmp_path / "data", tmp_path / "home"
    data.mkdir()
    home.mkdir()
    return data, home


def run(data: Path, home: Path, action: str) -> subprocess.CompletedProcess[str]:
    """Run the toggle against the temp dirs."""
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(data), "HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), action], env=env, capture_output=True, text=True
    )


def janitor_flag(data: Path) -> Path:
    return data / "oauth-rotator" / "opt-in.flag"


def server_flag(home: Path) -> Path:
    return home / ".aimaestro" / "oauth-rotator-tick.enabled"


def test_on_sets_both_flags(dirs: tuple[Path, Path]) -> None:
    """ON creates the janitor flag and the server flag."""
    data, home = dirs
    r = run(data, home, "on")
    assert r.returncode == 0, r.stderr
    assert janitor_flag(data).read_text() == "on"
    assert server_flag(home).is_file()


def test_off_clears_both_flags(dirs: tuple[Path, Path]) -> None:
    """OFF removes the janitor flag and renames the server flag to a .DISABLED-* file."""
    data, home = dirs
    assert run(data, home, "on").returncode == 0
    r = run(data, home, "off")
    assert r.returncode == 0, r.stderr
    assert not janitor_flag(data).exists()
    assert not server_flag(home).exists()
    assert list(server_flag(home).parent.glob("oauth-rotator-tick.enabled.DISABLED-*"))


def test_disagreeing_sides_are_fixed_to_requested_state(dirs: tuple[Path, Path]) -> None:
    """Janitor on + server off, then OFF: both end off; the reverse then ON: both end on."""
    data, home = dirs
    janitor_flag(data).parent.mkdir(parents=True)
    janitor_flag(data).write_text("on")
    assert run(data, home, "off").returncode == 0
    assert not janitor_flag(data).exists() and not server_flag(home).exists()
    server_flag(home).parent.mkdir(parents=True, exist_ok=True)
    server_flag(home).write_text("")
    assert run(data, home, "on").returncode == 0
    assert janitor_flag(data).is_file() and server_flag(home).is_file()


def test_idempotent(dirs: tuple[Path, Path]) -> None:
    """Running the same action twice succeeds both times."""
    data, home = dirs
    for action in ("on", "on", "off", "off"):
        assert run(data, home, action).returncode == 0


def test_second_write_failure_undoes_first(dirs: tuple[Path, Path]) -> None:
    """If the server side cannot be written, the janitor flag is restored and the exit is non-zero."""
    data, home = dirs
    # ~/.aimaestro is a plain FILE, so creating the server flag under it must fail.
    (home / ".aimaestro").write_text("not a dir")
    r = run(data, home, "on")
    assert r.returncode != 0
    assert not janitor_flag(data).exists()


def test_off_failure_restores_janitor_flag(dirs: tuple[Path, Path]) -> None:
    """If OFF cannot rename the server flag, the janitor flag it cleared is put back."""
    data, home = dirs
    assert run(data, home, "on").returncode == 0
    # Read-only state dir: the rename inside it must fail.
    server_flag(home).parent.chmod(0o500)
    try:
        r = run(data, home, "off")
    finally:
        server_flag(home).parent.chmod(0o700)
    assert r.returncode != 0
    assert janitor_flag(data).read_text() == "on"
    assert server_flag(home).is_file()


def test_unknown_action_and_missing_data_dir(dirs: tuple[Path, Path]) -> None:
    """A bad action or an unset CLAUDE_PLUGIN_DATA fails non-zero and writes nothing."""
    data, home = dirs
    assert run(data, home, "toggle").returncode != 0
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
    env["HOME"] = str(home)
    r = subprocess.run([sys.executable, str(SCRIPT), "on"], env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert not server_flag(home).exists()
