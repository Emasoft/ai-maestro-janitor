"""memgrep-binary-stale: a memgrep build older than the installed plugin's memgrep source (TRDD-V5V1CBLM).

Fixtures in tests/fixtures/memgrep_stale/ are REAL `gh api .../compare/<base>...<head>` responses
captured 2026-10-07 (ahead.json has `patch`, `commits`, the base commits and per-file shas/urls
stripped to stay small and pass the privacy scan; the detector reads only `status` and
`files[].filename`). No mocks: tests that need a tool missing
run the detector with a PATH that lacks it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
DETECTOR = ROOT / "scripts" / "detectors" / "memgrep-binary-stale.py"
FIX = ROOT / "tests" / "fixtures" / "memgrep_stale"

_spec = importlib.util.spec_from_file_location("memgrep_binary_stale", DETECTOR)
assert _spec and _spec.loader
det = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(det)

MEMGREP = shutil.which("memgrep")
needs_memgrep = pytest.mark.skipif(MEMGREP is None, reason="memgrep not installed on this machine")


def _fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _run(tmp_path: Path, *, path: str, memgrep: str | None, installed: str | None = "288a2777387c5aa106fbd0ba722e5aea4bec7ff5", version: str = "3.8.7", extra_env: dict[str, str] | None = None) -> str:
    """Run the detector as the dispatcher does, in an isolated HOME / project / global-state dir."""
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    if installed:
        entry = [{"scope": "user", "gitCommitSha": installed, "version": version}]
        (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"plugins": {det._PLUGIN_KEY: entry}}), encoding="utf-8"
        )
    env = {
        "HOME": str(home),
        "PATH": path,
        "CLAUDE_PROJECT_DIR": str(tmp_path / "proj"),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gs"),
    }
    if memgrep:
        env["MEMGREP_BIN"] = memgrep
    env.update(extra_env or {})
    (tmp_path / "proj").mkdir(exist_ok=True)
    proc = subprocess.run([sys.executable, str(DETECTOR)], env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_ahead_with_memgrep_changes_is_stale() -> None:
    """Real compare 5497043...288a2777: ahead, with memgrep source files changed."""
    assert det.classify(_fixture("ahead")) > 0


def test_behind_is_quiet() -> None:
    """A dev build newer than the release (status behind) is not stale."""
    assert det.classify(_fixture("behind")) == 0


def test_behind_with_memgrep_files_is_quiet() -> None:
    """Only ahead/diverged can be stale: a `behind` compare that lists memgrep files is still not stale."""
    data = _fixture("ahead")
    data["status"] = "behind"
    assert det.classify(data) == 0


def test_identical_is_quiet() -> None:
    """Same commit on both sides is not stale."""
    assert det.classify(_fixture("identical")) == 0


def test_ahead_without_memgrep_changes_is_quiet() -> None:
    """The plugin moved but no file under scripts/memgrep/ did: the binary is still current."""
    data = _fixture("ahead")
    data["files"] = [f for f in data["files"] if not f["filename"].startswith("scripts/memgrep/")]
    assert det.classify(data) == 0


def test_stamp_parsing() -> None:
    """The build stamp is the commit in `memgrep --version`; `unknown` means no stamp."""
    assert det.parse_stamp("memgrep 0.2.0 (5497043, 2026-10-07)") == "5497043"
    assert det.parse_stamp("memgrep 0.1.0 (unknown, unknown)") is None
    assert det.parse_stamp("") is None


def test_no_memgrep_is_one_advisory(tmp_path: Path) -> None:
    """Can't tell: no memgrep on PATH, HOME or env gives one advisory line and no fix proposal."""
    out = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=None)
    assert "cannot tell" in out and "no memgrep binary found" in out
    assert "cargo install" not in out


@needs_memgrep
def test_no_gh_is_one_advisory(tmp_path: Path) -> None:
    """Can't tell: a real memgrep but a PATH without gh gives an advisory, never STALE."""
    out = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=MEMGREP, installed="f" * 40)
    assert "cannot tell" in out and "compare failed" in out
    assert "cargo install" not in out


@needs_memgrep
def test_no_user_scope_install_is_one_advisory(tmp_path: Path) -> None:
    """Can't tell: no user-scope janitor entry in installed_plugins.json."""
    out = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=MEMGREP, installed=None)
    assert "cannot tell" in out and "no user-scope janitor install" in out


def test_second_run_on_same_pair_prints_nothing(tmp_path: Path) -> None:
    """Machine-wide dedupe: the same finding is announced once, not on every fire."""
    first = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=None)
    second = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=None)
    assert first and second == ""


@needs_memgrep
def test_cached_pair_needs_no_gh(tmp_path: Path) -> None:
    """The compare result is cached per (stamp, sha): a seeded cache yields STALE with no gh."""
    stamp = det.parse_stamp(subprocess.run([MEMGREP or "", "--version"], capture_output=True, text=True).stdout)
    assert stamp
    sha = "e" * 40
    (tmp_path / "gs").mkdir()
    (tmp_path / "gs" / det._CACHE_FILE).write_text(
        json.dumps({f"{stamp}...{sha}": {"status": "ahead", "memgrep_files": ["scripts/memgrep/src/a.rs"]}}),
        encoding="utf-8",
    )
    out = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=MEMGREP, installed=sha)
    assert "1 memgrep source file(s)" in out and "cargo install --path scripts/memgrep" in out
    assert str(Path.home()) not in out


def test_truncated_compare_is_not_a_verdict() -> None:
    """A compare with no `files` key, or 300 files (GitHub's cap), is truncated: can't tell, never current."""
    assert det.is_truncated({"status": "ahead"})
    assert det.is_truncated({"status": "diverged", "files": [{"filename": "x"}] * 300})
    assert not det.is_truncated({"status": "ahead", "files": [{"filename": "x"}] * 299})
    assert not det.is_truncated({"status": "behind"})
    assert not det.is_truncated(_fixture("ahead"))


def test_cached_404_has_its_own_reason(tmp_path: Path) -> None:
    """A cached 404 (build commit unknown to GitHub) reads as local/fork build, not as 'gh missing'."""
    stub = tmp_path / "memgrep"
    stub.write_text("#!/bin/sh\necho 'memgrep 0.2.0 (abc1234, 2026-10-07)'\n", encoding="utf-8")
    stub.chmod(0o755)
    sha = "d" * 40
    (tmp_path / "gs").mkdir()
    (tmp_path / "gs" / det._CACHE_FILE).write_text(json.dumps({f"abc1234...{sha}": {"status": "not-found"}}), encoding="utf-8")
    out = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=str(stub), installed=sha)
    assert "the build commit is not on GitHub (local or fork build)" in out
    assert "gh missing" not in out


@pytest.mark.real_subprocess("gh")
@pytest.mark.skipif(shutil.which("gh") is None, reason="gh not installed")
def test_real_404_has_its_own_reason(tmp_path: Path) -> None:
    """Real gh against GitHub: a stamp that is no commit there gives the local/fork-build reason."""
    stub = tmp_path / "memgrep"
    stub.write_text("#!/bin/sh\necho 'memgrep 0.2.0 (abc1234, 2026-10-07)'\n", encoding="utf-8")
    stub.chmod(0o755)
    # Why: CI passes its token under this test-only name so no other gh-calling test sees a login; _run isolates HOME, so locally fall back to the gh credential.
    token = os.environ.get("JANITOR_TEST_GH_TOKEN") or subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, env={**os.environ, "HOME": pwd.getpwuid(os.getuid()).pw_dir}
    ).stdout.strip()
    # Why: a CI runner has gh installed but not logged in; the unauthenticated compare call errors
    # instead of returning the 404 this test asserts, so without a token there is nothing to test.
    if not token:
        pytest.skip("gh not authenticated")
    out = _run(tmp_path, path=os.environ["PATH"], memgrep=str(stub), installed="f" * 40, extra_env={"GH_TOKEN": token})
    assert "the build commit is not on GitHub (local or fork build)" in out, out


def test_cant_tell_dedupes_per_installed_sha(tmp_path: Path) -> None:
    """The same reason for two different installed shas is two advisories (the seen file never expires)."""
    first = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=None, installed="a" * 40)
    second = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=None, installed="b" * 40)
    assert first and second


def test_stale_line_names_the_release_download(tmp_path: Path) -> None:
    """The STALE advice is concrete: `gh release download v<version>` for the installed version."""
    stub = tmp_path / "memgrep"
    stub.write_text("#!/bin/sh\necho 'memgrep 0.2.0 (abc1234, 2026-10-07)'\n", encoding="utf-8")
    stub.chmod(0o755)
    sha = "c" * 40
    (tmp_path / "gs").mkdir()
    (tmp_path / "gs" / det._CACHE_FILE).write_text(
        json.dumps({f"abc1234...{sha}": {"status": "ahead", "memgrep_files": ["scripts/memgrep/src/a.rs"]}}), encoding="utf-8"
    )
    out = _run(tmp_path, path=str(tmp_path / "empty"), memgrep=str(stub), installed=sha, version="3.8.7")
    assert "gh release download v3.8.7 -R Emasoft/ai-maestro-janitor -p memgrep-" in out
    assert "cargo install --path scripts/memgrep" in out


@needs_memgrep
@pytest.mark.real_subprocess("gh")
@pytest.mark.skipif(shutil.which("gh") is None, reason="gh not installed")
def test_live_machine_run_is_clean(tmp_path: Path) -> None:
    """LIVE: this machine's real memgrep and plugin install give no output or one detector line, exit 0."""
    # conftest points $HOME at a fake tree; the live run needs the OS-recorded real home.
    real_home = pwd.getpwuid(os.getuid()).pw_dir
    env = {**os.environ, "HOME": real_home, "CLAUDE_PROJECT_DIR": str(tmp_path), "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gs")}
    proc = subprocess.run([sys.executable, str(DETECTOR)], env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) <= 1 and all(line.startswith("[memgrep-binary-stale]") for line in lines), proc.stdout
