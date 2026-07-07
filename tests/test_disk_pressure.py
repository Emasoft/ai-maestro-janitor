"""Tests for the S7 dual disk metric (TRDD-1T53EKTN).

Pure plist parsing on fixtures (a synthetic purgeable-carrying plist AND the exact
key shape verified on this host, which carries NO purgeable key), plus one live
fail-open run of disk_pressure() itself.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import disk_pressure as dp  # noqa: E402

_GIB = 1024**3


def _plist(d: dict) -> bytes:
    return plistlib.dumps(d)


def test_parse_purgeable_key_when_present() -> None:
    """A macOS that exposes a purgeable-class byte count yields the GB estimate."""
    data = _plist({"APFSContainerFree": 14 * _GIB, "PurgeableSpace": 25 * _GIB})
    assert dp.parse_diskutil_purgeable_gb(data) == 25.0


def test_parse_matches_any_purgeable_spelling() -> None:
    """The key match is spelling-resilient (case-insensitive substring) — macOS renames
    plist keys across versions more often than it ships colliding 'purgeable' keys."""
    data = _plist({"APFSVolumePurgeableBytes": 3 * _GIB})
    assert dp.parse_diskutil_purgeable_gb(data) == 3.0


def test_parse_this_hosts_real_shape_yields_unknown() -> None:
    """Verified on Darwin 25.5 (2026-07-07): diskutil info -plist / carries ONLY
    APFSContainerFree — no purgeable key. The honest answer is None (unknown)."""
    data = _plist({"APFSContainerFree": 14_880_436_224, "FreeSpace": 0})
    assert dp.parse_diskutil_purgeable_gb(data) is None


def test_parse_junk_bytes_fail_open() -> None:
    """Garbage in → None out, never an exception (the fail-open contract)."""
    assert dp.parse_diskutil_purgeable_gb(b"this is not a plist") is None
    assert dp.parse_diskutil_purgeable_gb(b"") is None
    assert dp.parse_diskutil_purgeable_gb(_plist({"Purgeable": "not-a-number"})) is None


def test_label_formats_both_ways() -> None:
    known = dp.DiskPressure(writable_gb=13.9, purgeable_gb=25.2)
    unknown = dp.DiskPressure(writable_gb=13.9, purgeable_gb=None)
    assert known.label == "13.9 GB writable / +25.2 GB purgeable"
    assert unknown.label == "13.9 GB writable / purgeable unknown"


def test_live_disk_pressure_never_raises() -> None:
    """The live probe on / returns a positive writable figure and never raises —
    purgeable may be None (this host) or a float (other macOS versions), both legal."""
    p = dp.disk_pressure("/")
    assert p.writable_gb > 0
    assert p.purgeable_gb is None or p.purgeable_gb >= 0
    assert "GB writable" in p.label
