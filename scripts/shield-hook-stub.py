#!/usr/bin/env python3
"""Janitor shield pre-commit stub: finds a VERIFIED cached janitor and runs its staged-content scan.

Installed by `shield_hook.py install` into the janitor DATA dir, a path outside the
version-stamped plugin cache, so a plugin update needs no hook reinstall (TRDD-NYKNE7MY).
The git pre-commit hook calls this file; it re-resolves the cached version on every commit.

SUPPLY-CHAIN GATE: this runs in every protected repo on every commit, so it never runs a cached
version that is PROVEN bad. The proof is the SAME routines dispatcher-stub.py uses (loaded from the
dispatcher-stub.py installed beside this file, never copied, so the two cannot drift): the quarantine
list, the C2 integrity manifest check, and the C3 HMAC anchor. Selection is the dispatcher walk, newest
to oldest, first acceptable version wins. No key, or an anchor naming another version, counts as
accepted, so a stale anchor cannot block every commit. Differences by design: a version with no usable
manifest is rejected (the dispatcher accepts it), and when NO version is acceptable the commit is REFUSED
(the dispatcher would run the newest anyway; a gate must not run code proven tampered).

Every refusal exits 1 with the failure named, the repair command, and the way on.
`--plugin-root <folder>` (written into the hook by `install --plugin-root`) names a folder the user chose
at install time; it skips the cache lookup and its verification.

Stdlib only, Python 3.9 compatible: it runs under whatever `python3` the git hook finds.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

INSTALL_JANITOR = "claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope user"
UPDATE_JANITOR = "claude plugin update ai-maestro-janitor@ai-maestro-plugins --scope user"
REPIN = "/janitor-repin-integrity"
REINSTALL_HOOK = "/janitor-secrets-shield-scan --install-hook"


def _refuse(failure: str, repair: str) -> int:
    """Print the fail-closed refusal: what failed, the repair command, how to proceed."""
    sys.stderr.write(
        f"janitor shield pre-commit: commit REFUSED, {failure}.\n"
        f"  repair:  {repair}\n"
        "  then proceed: run the same `git commit` again (the hook re-checks on every commit).\n"
    )
    return 1


def _load_dispatcher() -> Optional[ModuleType]:
    """Load the dispatcher-stub.py installed beside this file, or None when it is absent or does not load."""
    path = Path(__file__).resolve().parent / "dispatcher-stub.py"
    spec = importlib.util.spec_from_file_location("janitor_dispatcher_stub", path)
    if not path.is_file() or spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - any failure to load the verifier is a refusal, never a pass
        return None
    return module


def _unverified(d: ModuleType, data_root: Path, version_dir: Path) -> Optional[str]:
    """None when dispatcher-stub.py accepts the cached version, else the failure in words.

    The routines are dispatcher-stub.py own (never copied): quarantine list, C2 manifest check, C3 HMAC
    anchor. Like the dispatcher, only proven corruption or tamper rejects the C3 anchor: no key, or an anchor
    naming another version, is accepted, so a stale anchor cannot block every commit on a host that leaves
    it behind. Two differences from the dispatcher: a version with no usable manifest is REJECTED, and when
    NO version is accepted the caller refuses the commit instead of running the newest one anyway.
    """
    name = version_dir.name
    if name in d._read_quarantine(data_root):
        return "the version is quarantined"
    ok, reason = d._verify_version(version_dir)
    if not ok:
        return f"integrity manifest check failed ({reason})"
    if reason != "verified":
        # The dispatcher accepts a missing, unreadable or empty manifest (fail-open: a heartbeat must not die).
        # A commit gate must not: every shipped version carries a manifest, so one without it would let anyone
        # who can write the cache delete the manifest and be accepted.
        return f"no usable integrity manifest ({reason})"
    if d._pin_rejects(version_dir, name, data_root):
        return "the manifest does not match the C3 integrity anchor (pin-mismatch: the cached version was changed)"
    return None


def _resolve_verified_root() -> Optional[Path]:
    """The newest cached version that ships the hook script and passes the strict check; prints the refusal and returns None otherwise."""
    d = _load_dispatcher()
    if d is None:
        _refuse("dispatcher-stub.py (the integrity verifier) is missing or unloadable in the janitor DATA dir", REINSTALL_HOOK)
        return None
    try:
        cache, data_root, version_key = d.PLUGIN_CACHE_ROOT, d.PLUGIN_DATA_ROOT, d._version_key
        versions = sorted((p for p in cache.iterdir() if p.is_dir()), key=version_key) if cache.is_dir() else []
        candidates = [v for v in reversed(versions) if (v / "scripts" / "shield_hook.py").is_file()]
        if not candidates:
            _refuse("no cached ai-maestro-janitor version ships the shield hook script (scripts/shield_hook.py)", UPDATE_JANITOR + "  (or, if it is not installed at all: " + INSTALL_JANITOR + ")")
            return None
        failures = []
        for version_dir in candidates:
            why = _unverified(d, data_root, version_dir)
            if why is None:
                return version_dir
            failures.append(f"{version_dir.name}: {why}")
    except AttributeError:
        # WHY /janitor-arm and not the hook reinstall: install leaves an existing dispatcher-stub.py alone (the armed cron fires it); arm refreshes it.
        _refuse("the dispatcher-stub.py in the janitor DATA dir lacks the verifier routines this hook needs (it is older than this plugin)", "/janitor-arm  (re-installs dispatcher-stub.py into the DATA dir)")
        return None
    _refuse("no cached ai-maestro-janitor version passes the integrity check (" + "; ".join(failures) + ")", REPIN + "  (re-certifies the anchor), or " + UPDATE_JANITOR)
    return None


def main(argv: list[str]) -> int:
    """Resolve the plugin folder (--plugin-root pin, else the newest verified cached version) and run scan-staged."""
    if argv[:1] == ["--plugin-root"] and len(argv) == 2:
        root: Optional[Path] = Path(argv[1])
    elif argv:
        sys.stderr.write("shield-hook-stub: the only accepted argument is --plugin-root <folder>\n")
        return 1
    else:
        root = _resolve_verified_root()
    if root is None:
        return 1
    script = root / "scripts" / "shield_hook.py"
    if not script.is_file():
        return _refuse(f"the plugin folder has no scripts/shield_hook.py ({root})", UPDATE_JANITOR)
    # subprocess, not execv: bandit B606 flags execv, and the exit code is passed on unchanged.
    return subprocess.run([sys.executable, str(script), "scan-staged", "--plugin-root", str(root)], check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
