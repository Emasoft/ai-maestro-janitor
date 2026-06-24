"""Tests for the dispatcher-stub's C2 verify-before-exec gate (TRDD-T198DT1W).

The stub is the boot-critical bootstrap of the whole janitor (cron → stub →
dispatch.py → daemon). Its one job — pick a cached plugin version and exec its
`dispatch.py` — must now:

  (a) prefer the NEWEST version that verifies clean against its shipped integrity
      manifest,
  (b) on an EXPLICIT corruption (a manifest-listed file whose live hash differs,
      or is gone), walk DOWN to the next-older clean version, and
  (c) FAIL-OPEN on every uncertainty — no/unreadable/malformed/empty manifest, a
      degenerate empty-hash entry, or NO clean version at all — so the heartbeat
      is never bricked by its own integrity gate.

These tests prove all three legs. We load the hyphenated stub file by spec and
stub `os.execv` so `main()` "execs" into a recorded path instead of replacing the
test process.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_STUB_PATH = Path(__file__).resolve().parent.parent / "scripts" / "dispatcher-stub.py"


def _load_stub():
    """Import scripts/dispatcher-stub.py (hyphenated → not importable by name)."""
    spec = importlib.util.spec_from_file_location("dispatcher_stub", _STUB_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Execed(Exception):
    """Raised by the fake os.execv so main() stops at the 'exec' point, exactly as
    the real os.execv would replace the process (never returning)."""


@pytest.fixture
def stub():
    return _load_stub()


# ── fixture builders ────────────────────────────────────────────────────────


def _make_version(cache_root: Path, version: str, *, dispatch: bool = True) -> Path:
    """Create a cached `<version>/scripts/dispatch.py` (unless dispatch=False)."""
    vdir = cache_root / version
    (vdir / "scripts").mkdir(parents=True)
    if dispatch:
        (vdir / "scripts" / "dispatch.py").write_text(
            f"#!/usr/bin/env python3\nprint('dispatch {version}')\n"
        )
    return vdir


def _hash(vdir: Path, rel: str) -> str:
    return hashlib.sha256((vdir / rel).read_bytes()).hexdigest()


def _write_manifest(vdir: Path, files: dict) -> None:
    """Write the wrapped on-disk manifest shape the real writer produces."""
    (vdir / ".integrity").mkdir(parents=True, exist_ok=True)
    (vdir / ".integrity" / "manifest-sha256.json").write_text(
        json.dumps({"version": 1, "files": files})
    )


def _write_raw_manifest(vdir: Path, raw: str) -> None:
    """Write arbitrary bytes as the manifest (malformed-JSON / wrong-shape cases)."""
    (vdir / ".integrity").mkdir(parents=True, exist_ok=True)
    (vdir / ".integrity" / "manifest-sha256.json").write_text(raw)


def _clean_files(vdir: Path) -> dict:
    """Drop a README into the version and return a CORRECT manifest 'files' dict
    (≥2 entries: the dispatch.py + the README) hashed from the live files."""
    (vdir / "README.md").write_text(f"readme for {vdir.name}\n")
    return {
        "scripts/dispatch.py": _hash(vdir, "scripts/dispatch.py"),
        "README.md": _hash(vdir, "README.md"),
    }


def _run_main(monkeypatch, stub, cache_root: Path) -> str:
    """Run stub.main() with PLUGIN_CACHE_ROOT redirected and os.execv stubbed;
    return the path of the dispatch.py that would have been execed."""
    monkeypatch.setattr(stub, "PLUGIN_CACHE_ROOT", cache_root)
    captured: dict[str, str] = {}

    def fake_execv(path, argv):
        captured["path"] = path
        captured["argv"] = argv
        raise _Execed

    monkeypatch.setattr(stub.os, "execv", fake_execv)
    with pytest.raises(_Execed):
        stub.main()
    return captured["path"]


# ── the common path ─────────────────────────────────────────────────────────


def test_clean_latest_execs_latest(stub, tmp_path, monkeypatch):
    """Newest version verifies clean → exec ITS dispatch.py (the 99% case)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.18.1")
    _write_manifest(v1, _clean_files(v1))
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_no_manifest_fail_open_execs_latest(stub, tmp_path, monkeypatch):
    """A version with NO manifest (old releases) is accepted — never blocked."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")  # no manifest at all
    v1 = _make_version(cache, "0.18.1")  # no manifest at all
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


# ── corruption → fall back ──────────────────────────────────────────────────


def test_corrupt_latest_falls_back_to_clean_older(stub, tmp_path, monkeypatch):
    """Latest's manifest no longer matches a live file → walk DOWN to the clean
    older version."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.18.1")
    _write_manifest(v1, _clean_files(v1))
    # Corrupt v1's README AFTER the manifest was written → live hash ≠ manifest.
    (v1 / "README.md").write_text("TAMPERED\n")
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


def test_manifest_lists_missing_file_falls_back(stub, tmp_path, monkeypatch):
    """A manifest entry whose file is GONE (partial download) → corrupt → fall back."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.18.1")
    files = _clean_files(v1)
    files["skills/ghost/SKILL.md"] = "deadbeef" * 8  # never created on disk
    _write_manifest(v1, files)
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


# ── fail-open on uncertainty ────────────────────────────────────────────────


def test_malformed_manifest_fail_open(stub, tmp_path, monkeypatch):
    """Unparseable manifest JSON → cannot prove corruption → accept (fail-open)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")
    v1 = _make_version(cache, "0.18.1")
    _write_raw_manifest(v1, "{ this is not json ")
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_manifest_wrong_shape_fail_open(stub, tmp_path, monkeypatch):
    """Valid JSON but not the {files:{...}} shape → fail-open accept."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")
    v1 = _make_version(cache, "0.18.1")
    _write_raw_manifest(v1, json.dumps([1, 2, 3]))  # a list, not a dict
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_empty_expected_hash_is_fail_open(stub, tmp_path, monkeypatch):
    """An empty expected hash (compute_manifest records "" for a file that vanished
    at BUILD time) is manifest uncertainty, not tampering → that entry is skipped,
    the version still verifies on its real entries → exec latest."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")
    v1 = _make_version(cache, "0.18.1")
    files = _clean_files(v1)
    files["README.md"] = ""  # degenerate build entry — must NOT fail the version
    _write_manifest(v1, files)
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_all_corrupt_fail_open_execs_newest_runnable(stub, tmp_path, monkeypatch):
    """No version verifies clean → fail-open to the NEWEST runnable version (a
    possibly-corrupt heartbeat beats a dead one — the cardinal rule)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    (v0 / "README.md").write_text("TAMPERED 0\n")
    v1 = _make_version(cache, "0.18.1")
    _write_manifest(v1, _clean_files(v1))
    (v1 / "README.md").write_text("TAMPERED 1\n")
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")  # newest, even though dirty


# ── runnability / preserved behaviors ───────────────────────────────────────


def test_latest_missing_dispatch_skips_to_older(stub, tmp_path, monkeypatch):
    """Newest version has no dispatch.py (broken release) → skip it, run the older
    one (more immortal than the old `sys.exit`)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    _make_version(cache, "0.18.1", dispatch=False)  # no dispatch.py
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


def test_no_versions_exits(stub, tmp_path, monkeypatch):
    """Empty cache root → SystemExit (preserved)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(stub, "PLUGIN_CACHE_ROOT", cache)
    with pytest.raises(SystemExit):
        stub.main()


def test_no_runnable_dispatch_exits(stub, tmp_path, monkeypatch):
    """Versions exist but none carry a dispatch.py → SystemExit (preserved)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0", dispatch=False)
    _make_version(cache, "0.18.1", dispatch=False)
    monkeypatch.setattr(stub, "PLUGIN_CACHE_ROOT", cache)
    with pytest.raises(SystemExit):
        stub.main()


# ── direct unit coverage of the verify primitive ────────────────────────────


def test_verify_version_clean_true(stub, tmp_path):
    v = _make_version(tmp_path, "0.18.1")
    _write_manifest(v, _clean_files(v))
    ok, reason = stub._verify_version(v)
    assert ok and reason == "verified"


def test_verify_version_mismatch_false(stub, tmp_path):
    v = _make_version(tmp_path, "0.18.1")
    _write_manifest(v, _clean_files(v))
    (v / "README.md").write_text("changed\n")
    ok, reason = stub._verify_version(v)
    assert not ok and reason.startswith("mismatch:")


def test_verify_version_no_manifest_true(stub, tmp_path):
    v = _make_version(tmp_path, "0.18.1")  # no manifest
    ok, reason = stub._verify_version(v)
    assert ok and reason == "no-manifest"
