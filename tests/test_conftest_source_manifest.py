"""_source_manifest prunes target/ and __pycache__/ during the walk, not after it (TRDD-TASA9ACJ)."""

import hashlib
import os
from pathlib import Path

import pytest
from conftest import _source_manifest


def test_source_manifest_matches_hand_built_dict(tmp_path: Path) -> None:
    """The manifest for a fixture tree equals a hand-built {relpath: sha256} dict."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "y.py").write_bytes(b"y-content")
    (tmp_path / "src" / "z.sh").write_bytes(b"z-content")
    (tmp_path / "src" / "notes.txt").write_bytes(b"ignored-extension")
    (tmp_path / "target" / "deep").mkdir(parents=True)
    (tmp_path / "target" / "deep" / "x.py").write_bytes(b"must-not-be-hashed")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "c.py").write_bytes(b"must-not-be-hashed-either")

    manifest = _source_manifest(tmp_path)

    assert sorted(manifest.keys()) == ["src/y.py", "src/z.sh"]
    expected = {
        "src/y.py": hashlib.sha256(b"y-content").hexdigest(),
        "src/z.sh": hashlib.sha256(b"z-content").hexdigest(),
    }
    assert manifest == expected


def test_source_manifest_never_descends_into_target_or_pycache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.walk is pruned in place — no yielded dirpath ever falls under target/ or __pycache__/."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "y.py").write_bytes(b"y-content")
    (tmp_path / "target" / "deep").mkdir(parents=True)
    (tmp_path / "target" / "deep" / "x.py").write_bytes(b"must-not-be-visited")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "c.py").write_bytes(b"must-not-be-visited-either")

    visited_dirpaths: list[str] = []
    real_walk = os.walk

    def spy_walk(top, *args, **kwargs):  # type: ignore[no-untyped-def]
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            visited_dirpaths.append(dirpath)
            yield dirpath, dirnames, filenames

    import conftest as _conftest

    monkeypatch.setattr(_conftest.os, "walk", spy_walk)

    manifest = _conftest._source_manifest(tmp_path)

    assert manifest == {"src/y.py": hashlib.sha256(b"y-content").hexdigest()}
    # Without this the loop below is vacuous: a revert to `rglob` never calls os.walk,
    # visited_dirpaths stays empty, and the test passes while proving nothing.
    assert visited_dirpaths, "os.walk was not used — the in-place prune cannot have run"
    for dirpath in visited_dirpaths:
        parts = Path(dirpath).parts
        assert "target" not in parts
        assert "__pycache__" not in parts
