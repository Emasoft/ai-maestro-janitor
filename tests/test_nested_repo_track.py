"""TRDD-IEBZ4JC5 (a): nested-repo projects get maintenance via .janitor/track-repo.

A project folder that is not itself a git repo but registers a relative subfolder in
`.janitor/track-repo` delegates its git-bound maintenance to that subrepo; without
the registration the detectors say the skip out loud instead of exiting silently.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, cwd=str(path))


def _clear_caches() -> None:
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.tracked_repo):
        fn.cache_clear()


def test_repo_root_returns_its_own_toplevel(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "proj"
    _git_init(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    _clear_caches()
    assert state.tracked_repo(str(repo)) == repo.resolve()


def test_track_repo_resolves_the_registered_subfolder(tmp_path, monkeypatch) -> None:
    proj = tmp_path / "bundle"  # NOT a repo
    sub = proj / "svc" / "backend"
    _git_init(sub)
    (proj / ".janitor").mkdir(parents=True)
    (proj / ".janitor" / "track-repo").write_text("svc/backend\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    _clear_caches()
    assert state.tracked_repo(str(proj)) == sub.resolve()


def test_track_repo_absent_or_bad_is_none(tmp_path, monkeypatch) -> None:
    proj = tmp_path / "plain"
    proj.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    _clear_caches()
    assert state.tracked_repo(str(proj)) is None
    (proj / ".janitor").mkdir()
    (proj / ".janitor" / "track-repo").write_text("../escape", encoding="utf-8")
    _clear_caches()
    assert state.tracked_repo(str(proj)) is None  # parent-escaping value refused


def _load(name: str, tag: str):
    spec = importlib.util.spec_from_file_location(f"{name}-{tag}", _ROOT / "scripts" / "detectors" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_gitignore_coverage_runs_against_the_track_repo(tmp_path, monkeypatch, capsys) -> None:
    mod = _load("gitignore-coverage", "track")
    proj = tmp_path / "bundle"
    sub = proj / "svc" / "backend"
    _git_init(sub)
    (proj / ".janitor").mkdir(parents=True)
    (proj / ".janitor" / "track-repo").write_text("svc/backend", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    _clear_caches()
    monkeypatch.chdir(tmp_path)
    rc = mod.main()
    assert rc == 0
    # The detector exercised git against the SUBrepo (no skip line either way).
    out = capsys.readouterr().out
    assert "not a git repo" not in out


def test_gitignore_coverage_says_the_skip_out_loud(tmp_path, monkeypatch, capsys) -> None:
    mod = _load("gitignore-coverage", "noreg")
    proj = tmp_path / "plain"
    proj.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    _clear_caches()
    log = tmp_path / "logs"
    monkeypatch.setenv("JANITOR_LOG_DIR", str(log))
    rc = mod.main()
    assert rc == 0
    assert (log / "gitignore-coverage.log").read_text(encoding="utf-8").count(
        "no .janitor/track-repo is registered"
    ) == 1
