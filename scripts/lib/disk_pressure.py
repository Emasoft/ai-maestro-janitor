"""disk_pressure — the S7 shared dual disk metric (TRDD-1T53EKTN, fseventsd plan).

`shutil.disk_usage().free` reports WRITABLE-NOW bytes, which on APFS contradicts the OS
UI's "available" figure (writable + purgeable) — during the 39 GB fseventsd incident that
mismatch made humans dismiss (or over-trust) low-disk findings. Every janitor disk check
therefore reports BOTH numbers through this one helper — single source of truth, no
per-detector reimplementation (the S5 detector TRDD-HK7IZ21Z consumes it too).

Purgeable is an ESTIMATE parsed from `diskutil info -plist /` when the running macOS
exposes a purgeable-class key. Verified 2026-07-07 on this host (Darwin 25.5): the plist
carries ONLY `APFSContainerFree` — no purgeable key — so `purgeable_gb` is honestly None
("unknown") there; versions that do expose one (any key containing "purgeable",
case-insensitive) get the real estimate. Fail-open everywhere: subprocess/parse failure ⇒
writable-only, never a crash, never a blocked caller.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_GIB = 1024**3


@dataclass(frozen=True)
class DiskPressure:
    """Both numbers a human needs to judge disk pressure. `purgeable_gb` None = unknown."""

    writable_gb: float
    purgeable_gb: float | None

    @property
    def label(self) -> str:
        """The canonical report string: 'NN.N GB writable / +NN.N GB purgeable'."""
        if self.purgeable_gb is None:
            return f"{self.writable_gb:.1f} GB writable / purgeable unknown"
        return f"{self.writable_gb:.1f} GB writable / +{self.purgeable_gb:.1f} GB purgeable"


def parse_diskutil_purgeable_gb(plist_bytes: bytes) -> float | None:
    """Purgeable GB from a `diskutil info -plist` payload, or None when the running
    macOS doesn't expose one. Matches ANY key containing 'purgeable' (case-insensitive)
    with a numeric value — resilient to the key's exact spelling drifting across
    macOS versions, which is likelier than a colliding non-byte 'purgeable' key."""
    try:
        info = plistlib.loads(plist_bytes)
    except Exception:  # plistlib raises several unrelated types — fail-open is the contract
        return None
    if not isinstance(info, dict):
        return None
    for key, value in info.items():
        if "purgeable" in str(key).lower() and isinstance(value, (int, float)) and value >= 0:
            return float(value) / _GIB
    return None


def disk_pressure(path: str | Path = "/") -> DiskPressure:
    """The dual metric for the filesystem holding `path`. Never raises."""
    try:
        writable = shutil.disk_usage(path).free / _GIB
    except OSError:
        writable = 0.0
    purgeable: float | None = None
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["diskutil", "info", "-plist", str(path)],
                capture_output=True, timeout=10,
            )
            if out.returncode == 0:
                purgeable = parse_diskutil_purgeable_gb(out.stdout)
        except (OSError, subprocess.SubprocessError):
            purgeable = None
    return DiskPressure(writable_gb=writable, purgeable_gb=purgeable)
