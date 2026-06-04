"""Tests for scripts/lib/janitor_integrity.py — the resilient daemon's backup +
corruption-recovery primitives (TRDD-7100178d, Pillar 2). All real: writes/reads on
a tmp dir, no mocks. Each test function carries a one-line description for the report.
"""

from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MOD = _HERE.parent / "scripts" / "lib" / "janitor_integrity.py"


def _load():
    spec = importlib.util.spec_from_file_location("janitor_integrity_under_test", _MOD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ji = _load()


def test_atomic_write_bytes_is_0600_and_makes_parent(tmp_path: Path) -> None:
    """atomic_write_bytes creates missing parent dirs and writes owner-only (0600)."""
    target = tmp_path / "sub" / "dir" / "f.bin"
    ji.atomic_write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_backup_and_write_roundtrips_with_sidecar(tmp_path: Path) -> None:
    """backup_and_write writes the data + a matching .sha256 sidecar that read_or_restore returns."""
    p = tmp_path / "state.json"
    ji.backup_and_write(p, b'{"v":1}')
    assert (p.with_name("state.json.sha256")).is_file()
    assert ji.read_or_restore(p) == b'{"v":1}'


def test_every_write_mirrors_current_content_into_backup(tmp_path: Path) -> None:
    """Each write mirrors the CURRENT content into .bak (a redundant copy, not the previous version) — even the very first write is protected."""
    p = tmp_path / "state.json"
    bak = p.with_name("state.json.bak")
    ji.backup_and_write(p, b"one")
    assert bak.read_bytes() == b"one"   # first write IS mirrored (no first-write gap)
    ji.backup_and_write(p, b"two")
    assert bak.read_bytes() == b"two"   # mirror tracks the current content, not the previous
    assert ji.read_or_restore(p) == b"two"


def test_corrupt_primary_restores_current_from_mirror(tmp_path: Path) -> None:
    """A corrupted primary (sidecar mismatch) is auto-restored from the mirror to the CURRENT value (no rollback) and re-healed."""
    p = tmp_path / "state.json"
    ji.backup_and_write(p, b"good-1")
    ji.backup_and_write(p, b"good-2")  # both primary AND mirror now hold good-2
    p.write_bytes(b"CORRUPTED-GARBAGE")  # simulate truncation/garble (sidecar now mismatches)
    assert not ji._matches_sidecar(p)
    restored = ji.read_or_restore(p)
    assert restored == b"good-2"           # the CURRENT value recovered, not a stale one
    assert p.read_bytes() == b"good-2"     # primary re-healed on disk
    assert ji._matches_sidecar(p)          # sidecar re-pointed to the restored content


def test_missing_primary_restores_current_from_mirror(tmp_path: Path) -> None:
    """A deleted primary is rebuilt from the mirror to the current value."""
    p = tmp_path / "state.json"
    ji.backup_and_write(p, b"first")
    ji.backup_and_write(p, b"second")  # mirror = second (current)
    p.unlink()
    assert ji.read_or_restore(p) == b"second"
    assert p.is_file()


def test_corrupt_primary_and_corrupt_backup_returns_none(tmp_path: Path) -> None:
    """When BOTH primary and backup fail their sidecars, read_or_restore returns None (no silent garbage — caller rebuilds)."""
    p = tmp_path / "state.json"
    ji.backup_and_write(p, b"a")
    ji.backup_and_write(p, b"b")  # .bak=a, primary=b
    p.write_bytes(b"garbage-primary")
    p.with_name("state.json.bak").write_bytes(b"garbage-backup")  # both now mismatch their sidecars
    assert ji.read_or_restore(p) is None


def test_unsidecared_legacy_file_is_trusted(tmp_path: Path) -> None:
    """A plain file with NO sidecar (written before the integrity layer) is returned as-is."""
    p = tmp_path / "legacy.json"
    p.write_bytes(b"legacy-content")
    assert ji.read_or_restore(p) == b"legacy-content"


def test_read_or_restore_missing_everything_is_none(tmp_path: Path) -> None:
    """No primary and no backup => None."""
    assert ji.read_or_restore(tmp_path / "nope.json") is None


def test_sha256_bytes_matches_hashlib() -> None:
    """sha256_bytes is the plain hex sha256 of the input."""
    import hashlib
    assert ji.sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()
