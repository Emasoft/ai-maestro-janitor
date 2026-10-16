"""Branch coverage for the git listing that replaced the detector tree walks (TRDD-XRT9LOQL).

`git_utils.own_files` (timeout and missing-git branches) and the three detector helpers
built on it (`repo-trust-score` `_tree_paths` / `_has_test_files`, `supply-chain-fingerprints`
`_find_named`): non-entry into ignored folders, tolerance of a tracked file deleted from
disk, and the unchanged full-walk fallback on a plain folder.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DETECTORS = _PROJECT_ROOT / "scripts" / "detectors"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import git_utils  # type: ignore[import-not-found]  # noqa: E402


def _load(filename: str, modname: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(modname, _DETECTORS / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.git_utils.own_files.cache_clear()
    return mod


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def _ignored_corpus_repo(root: Path) -> None:
    """Repo whose `downloads_dev/` is ignored and holds a test file, a setup.py and an exe."""
    (root / "downloads_dev").mkdir(parents=True)
    (root / "downloads_dev" / "test_corpus.py").write_text("x = 1\n", encoding="utf-8")
    (root / "downloads_dev" / "setup.py").write_text("x = 1\n", encoding="utf-8")
    (root / "downloads_dev" / "dropper.exe").write_bytes(b"MZ")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("/downloads_dev/\n", encoding="utf-8")
    _init_repo(root)
    subprocess.run(["git", "add", ".gitignore", "src/main.py"], cwd=root, check=True)


def _no_walk(self: Path, pattern: str):
    raise AssertionError(f"rglob({pattern!r}) walked {self}")


# ---------- git_utils.own_files: the two failure branches ----------------


def test_own_files_logs_then_returns_none_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A git timeout is logged to the caller's log name, then None (full walk).

    The 30 s timeout is hard-coded inside `own_files`, so the only way to reach this branch
    without a 30 s sleep is to make the narrow `run_git_readonly` seam raise TimeoutExpired.
    """
    root = tmp_path / "repo"
    _init_repo(root)
    logged: list[tuple[str, str]] = []

    def _timeout(cmd: list[str], **_k: object):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(git_utils, "run_git_readonly", _timeout)
    monkeypatch.setattr(git_utils.state, "log_line", lambda n, m: logged.append((n, m)))
    git_utils.own_files.cache_clear()

    assert git_utils.own_files(root, log_name="t") is None
    assert len(logged) == 1
    assert logged[0][0] == "t"
    assert "timed out" in logged[0][1]


def test_own_files_is_silent_none_when_git_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no git on PATH (real OSError from the real subprocess call) ⇒ None, nothing logged."""
    root = tmp_path / "repo"
    _init_repo(root)
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir()
    logged: list[tuple[str, str]] = []
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setattr(git_utils.state, "log_line", lambda n, m: logged.append((n, m)))
    git_utils.own_files.cache_clear()

    assert git_utils.own_files(root, log_name="t") is None
    assert logged == []


# ---------- non-entry into ignored folders --------------------------------


def test_trust_score_tree_paths_never_walks_when_git_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_tree_paths` answers from the listing: no `rglob`, and the ignored corpus is absent."""
    _ignored_corpus_repo(tmp_path)
    mod = _load("repo-trust-score.py", "rts_tree_paths_under_test")
    monkeypatch.setattr(Path, "rglob", _no_walk)

    paths = mod._tree_paths(tmp_path)

    assert tmp_path / "src" / "main.py" in paths
    assert not any("downloads_dev" in p.parts for p in paths)


def test_trust_score_has_test_files_never_walks_when_git_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_has_test_files` ignores a test file inside an ignored folder and never calls `rglob`."""
    _ignored_corpus_repo(tmp_path)
    mod = _load("repo-trust-score.py", "rts_has_tests_under_test")
    monkeypatch.setattr(Path, "rglob", _no_walk)

    assert mod._has_test_files(tmp_path) is False

    (tmp_path / "src" / "test_own.py").write_text("x = 1\n", encoding="utf-8")
    mod.git_utils.own_files.cache_clear()
    assert mod._has_test_files(tmp_path) is True


def test_fingerprints_find_named_never_walks_when_git_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_find_named` returns only the project's own setup.py and never calls `rglob`."""
    _ignored_corpus_repo(tmp_path)
    (tmp_path / "src" / "setup.py").write_text("x = 1\n", encoding="utf-8")
    mod = _load("supply-chain-fingerprints.py", "scf_find_named_under_test")
    monkeypatch.setattr(Path, "rglob", _no_walk)

    assert mod._find_named(tmp_path, "setup.py") == [tmp_path / "src" / "setup.py"]


# ---------- a tracked file deleted from disk is tolerated -----------------


def _tracked_then_deleted(root: Path, rel: str, content: bytes) -> Path:
    _init_repo(root)
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    subprocess.run(["git", "add", rel], cwd=root, check=True)
    target.unlink()
    return target


def test_trust_score_tolerates_a_tracked_binary_deleted_from_disk(tmp_path: Path) -> None:
    """`git ls-files --cached` still lists the deleted .exe; the binary walk must skip it."""
    gone = _tracked_then_deleted(tmp_path, "image/tool.exe", b"MZ")
    mod = _load("repo-trust-score.py", "rts_deleted_under_test")

    assert gone in mod._tree_paths(tmp_path)
    assert mod._enumerate_suspicious_binaries(tmp_path) == []


def test_fingerprints_tolerate_a_tracked_setup_py_deleted_from_disk(tmp_path: Path) -> None:
    """A listed-but-deleted setup.py must not crash the AST check or the content signature."""
    gone = _tracked_then_deleted(tmp_path, "setup.py", b"import os\n")
    mod = _load("supply-chain-fingerprints.py", "scf_deleted_under_test")

    assert gone in mod._find_named(tmp_path, "setup.py")
    assert mod._check_setup_py_ast(tmp_path) == []
    assert isinstance(mod._content_signature(tmp_path), str)


def test_typosquat_tolerates_a_tracked_lockfile_deleted_from_disk(tmp_path: Path) -> None:
    """The real detector run exits 0 and prints no traceback when a tracked lockfile is gone."""
    _tracked_then_deleted(tmp_path, "package-lock.json", b"{}")
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env.pop("CLAUDE_PLUGIN_OPTION_TYPOSQUAT_WATCHER_ENABLED", None)

    r = subprocess.run(
        [str(_DETECTORS / "typosquat-watcher.py")],
        env=env, capture_output=True, text=True, timeout=60,
    )

    assert r.returncode == 0
    assert "Traceback" not in r.stderr


# ---------- fallback on a plain folder ------------------------------------


def test_has_test_files_fallback_on_a_plain_folder_is_the_unfiltered_walk(tmp_path: Path) -> None:
    """Not a repo ⇒ `_has_test_files` keeps the pre-rewrite unfiltered `rglob`: a test file under
    a vendored dir counts, and a tree with none answers False."""
    mod = _load("repo-trust-score.py", "rts_plain_under_test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    assert mod._has_test_files(tmp_path) is False

    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "a.test.js").write_text("x\n", encoding="utf-8")
    mod.git_utils.own_files.cache_clear()
    assert mod._has_test_files(tmp_path) is True
