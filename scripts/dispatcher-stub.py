#!/usr/bin/env python3
"""ai-maestro-janitor cron dispatcher stub — auto-rolling dispatcher.

Installed by /janitor-arm into `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`,
a path that lives OUTSIDE the version-stamped plugin cache directory.

`${CLAUDE_PLUGIN_DATA}` resolves to `~/.claude/plugins/data/<id>/` —
a persistent directory that survives every plugin update and is only
cleaned up when the plugin is uninstalled from the last scope. The cron
prompt baked at /janitor-arm time points at THIS stub, not at any
versioned `dispatch.py`. The stub re-resolves "latest cached version"
on every fire and `os.execv`'s into it, so:

  - Plugin updates land in the cache → the next heartbeat picks them up.
  - Cache GC of any old version (CC removes orphaned versions ~7 days
    after update) is harmless: we always pick the current latest.
  - Re-arming is needed ONCE (on the upgrade to a stub-aware janitor
    version); after that, future bumps roll forward automatically.

Survival contract: this stub is fire-and-forget — zero arguments, no
state. As long as future `dispatch.py` versions stay zero-arg, the stub
never needs updating. If we ever break the contract, we accept that
users have to re-run /janitor-arm; the worst-case is the same as the
pre-stub world we're moving away from.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

PLUGIN_CACHE_ROOT = (
    Path.home() / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor"
)

# C3 (TRDD-T198DT1W) — the janitor's FIXED persistent DATA dir, resolved the SAME
# hard-coded way the daemon (launchd_keepalive._DATA_DIR) and the arm skill do,
# NOT via ${CLAUDE_PLUGIN_DATA} (which points at whichever plugin owns the running
# turn). This stub lives in this dir; the C3 trust-anchor files (the DATA-dir HMAC
# key, the last-good pin, the quarantine list) live under it, OUTSIDE the cache
# being verified — so a tampered cache version cannot forge them.
PLUGIN_DATA_ROOT = (
    Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
)
_INTEGRITY_KEY_NAME = ".integrity-key"  # 32 raw bytes (janitor_self_integrity convention)
_LAST_GOOD_REL = Path("integrity") / "last-good.json"
_QUARANTINE_REL = Path("integrity") / "quarantine.json"
_MANIFEST_REL = Path(".integrity") / "manifest-sha256.json"


def _version_key(d: Path) -> tuple[int, ...]:
    """Sort key for semver-style directory names. Non-numeric components
    sort lowest so they never out-rank a real version."""
    try:
        return tuple(int(p) for p in d.name.split("."))
    except ValueError:
        return (-1,)


def _verify_version(version_dir: Path) -> tuple[bool, str]:
    """Verify a cached version against its shipped integrity manifest (C2,
    TRDD-T198DT1W). Returns ``(ok, reason)``.

    FAIL-OPEN is the cardinal rule: a version we CANNOT check is ACCEPTED — only a
    version we can PROVE is corrupt is rejected. So a missing / unreadable /
    malformed / empty manifest, or a manifest entry with an empty expected hash,
    all return ``(True, ...)``. ONLY an explicit, completed mismatch — a
    manifest-listed file whose live sha256 differs, or a manifest-listed file that
    is gone — returns ``(False, ...)``, diverting `main()` to an older clean
    version. A bricked stub is the immortality bug this gate exists to prevent, so
    uncertainty must never block.

    The verify is INLINED stdlib (hashlib + json) ON PURPOSE: importing the cache's
    own ``janitor_self_integrity.load_manifest`` to check that same cache would be
    circular trust — a tampered version would supply its own verifier. The stub
    lives in the persistent DATA dir, OUTSIDE the cache, and trusts only itself.

    Manifest shape (written by ``janitor_self_integrity.write_manifest``):
    ``{"version": 1, "files": {"<relpath>": "<sha256hex>", ...}}``. The hashed set
    is the plugin's INSTRUCTION SURFACE (README / CLAUDE.md / skills / commands /
    rules) — so this gate is a clean-download canary + instruction-tamper guard,
    NOT a check of dispatch.py itself (a narrow gap C3's HMAC trust anchor closes;
    C2 alone is still a strict corruption-resilience win at near-zero bricking risk)."""
    manifest_path = version_dir / ".integrity" / "manifest-sha256.json"
    try:
        obj = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, "no-manifest"  # can't read/parse → never block (fail-open)
    if not isinstance(obj, dict):
        return True, "malformed-manifest"
    files = obj.get("files")
    if not isinstance(files, dict) or not files:
        return True, "empty-manifest"
    for rel, expected in files.items():
        if not isinstance(rel, str) or not isinstance(expected, str) or not expected:
            # A degenerate entry (non-str, or the empty hash compute_manifest records
            # for a file that vanished at BUILD time) is manifest UNCERTAINTY, not
            # proof of tampering → skip it (fail-open), never reject the version.
            continue
        target = version_dir / rel
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            return False, f"missing:{rel}"  # a manifest-listed file is gone → corrupt/partial
        if actual != expected:
            return False, f"mismatch:{rel}"  # explicit, PROVEN corruption/tamper
    return True, "verified"


# ── C3 — pin last-GOOD version + quarantine bad version (TRDD-T198DT1W) ───────
#
# C2 (above) catches ACCIDENTAL corruption with an UNSIGNED manifest. C3 closes
# the MALICIOUS-replacement gap: the DAEMON certifies a good version by writing
# an HMAC of its manifest — keyed by the DATA-dir `.integrity-key` the cache
# writer cannot read — into `<data>/integrity/last-good.json`. The stub
# recomputes that HMAC and compares; a version that rewrote BOTH a file AND its
# plaintext manifest still fails the HMAC. A `<data>/integrity/quarantine.json`
# lets the stub skip a proven-bad version fast.
#
# The stub INLINES its own stdlib readers (it must NOT import the cache's own
# `version_update_lib` / `janitor_self_integrity` to check that same cache —
# circular trust). FAIL-OPEN is preserved everywhere: any uncertainty (no key,
# no pin, pin for another version, no manifest, unreadable/malformed state)
# means C3 has NO OPINION and the C2 verdict stands. C3 adds exactly ONE new
# rejection: a candidate whose pin names IT but whose recomputed manifest HMAC
# differs.


def _read_key(data_root: Path) -> bytes | None:
    """The 32-byte DATA-dir HMAC key, or None when absent/wrong-size/unreadable.
    The stub only READS the key (it never mints one — minting belongs to the
    daemon/detector); a missing key simply means C3 cannot cross-check → C2-only."""
    try:
        blob = (data_root / _INTEGRITY_KEY_NAME).read_bytes()
    except OSError:
        return None
    return blob if len(blob) == 32 else None


def _read_pin(data_root: Path) -> dict | None:
    """The last-GOOD pin ``{"version", "manifest_hmac"}`` or None on any
    uncertainty (no file / unreadable / malformed / missing fields). The stub
    reads the PRIMARY file the daemon's crash-safe writer leaves in place; a torn
    primary just reads as no-pin → fail-open (uncertainty never blocks)."""
    try:
        obj = json.loads((data_root / _LAST_GOOD_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    version = obj.get("version")
    mac = obj.get("manifest_hmac")
    if not isinstance(version, str) or not version:
        return None
    if not isinstance(mac, str) or not mac:
        return None
    return {"version": version, "manifest_hmac": mac}


def _read_quarantine(data_root: Path) -> set[str]:
    """The set of quarantined version strings, or an EMPTY set on any uncertainty.
    FAIL-OPEN is critical: a corrupt quarantine file must NEVER read as "skip
    everything" — an empty set skips nothing, exactly as if no file existed."""
    try:
        obj = json.loads((data_root / _QUARANTINE_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(obj, dict):
        return set()
    versions = obj.get("versions")
    if not isinstance(versions, list):
        return set()
    return {v for v in versions if isinstance(v, str) and v}


def _pin_hmac(version_dir: Path, key: bytes) -> str | None:
    """base64(HMAC-SHA256(manifest BYTES, key)) for a cached version, or None if
    the version shipped no manifest. Recomputed from the exact on-disk bytes —
    identical to the daemon's ``version_update_lib.manifest_hmac`` — so a
    constant-time compare against the pin is unambiguous."""
    try:
        raw = (version_dir / _MANIFEST_REL).read_bytes()
    except OSError:
        return None
    return base64.b64encode(hmac.new(key, raw, hashlib.sha256).digest()).decode("ascii")


def _pin_rejects(version_dir: Path, version: str, data_root: Path) -> bool:
    """True ONLY when C3 can PROVE this version is bad via the pin: a pin exists,
    it names THIS version, the DATA key is present, this version has a manifest,
    and its recomputed HMAC differs from the pinned one. Every other state
    returns False (no opinion → fail-open; the C2 verdict already decided)."""
    pin = _read_pin(data_root)
    if pin is None or pin["version"] != version:
        return False  # no pin, or pin is about a DIFFERENT version → no opinion
    key = _read_key(data_root)
    if key is None:
        return False  # can't recompute without the key → no opinion (fail-open)
    actual = _pin_hmac(version_dir, key)
    if actual is None:
        return False  # this version has no manifest to anchor → no opinion
    # constant-time compare; a difference is PROVEN tamper (manifest rewritten
    # by someone lacking the DATA key) → reject this version.
    return not hmac.compare_digest(actual, pin["manifest_hmac"])


def main() -> int:
    if not PLUGIN_CACHE_ROOT.is_dir():
        sys.exit(f"ai-maestro-janitor cache root missing: {PLUGIN_CACHE_ROOT}")
    versions = sorted(
        (p for p in PLUGIN_CACHE_ROOT.iterdir() if p.is_dir()),
        key=_version_key,
    )
    if not versions:
        sys.exit("no ai-maestro-janitor versions cached")
    # C2 + C3 verify-before-exec (TRDD-T198DT1W): exec the NEWEST cached version that
    # has a runnable dispatch.py, is NOT quarantined (C3), verifies clean against its
    # integrity manifest (C2), AND is not proven-bad by the DATA-dir pin (C3). On any
    # EXPLICIT rejection (proven corruption, proven manifest-tamper, or a quarantine
    # entry) walk DOWN to the next-older acceptable version. FAIL-OPEN cardinal rule:
    # if NOTHING is acceptable, exec the newest RUNNABLE version anyway — a
    # possibly-bad heartbeat beats a DEAD one (a bricked stub is the immortality bug
    # this gate exists to prevent) — and warn on stderr so a human learns. Every
    # uncertainty (no/unreadable/malformed manifest, no key, no pin, pin for another
    # version, unreadable/malformed quarantine) is ACCEPTED — we never block what we
    # cannot prove bad. The quarantine read is hoisted out of the loop (one read).
    quarantined = _read_quarantine(PLUGIN_DATA_ROOT)
    newest_runnable: Path | None = None
    for version_dir in reversed(versions):  # newest first
        target = version_dir / "scripts" / "dispatch.py"
        if not target.is_file():
            continue
        if newest_runnable is None:
            # The fail-open backstop is the newest RUNNABLE version regardless of
            # quarantine/pin/verify — when all else is rejected, a heartbeat must
            # still fire. Captured BEFORE the quarantine skip on purpose.
            newest_runnable = target
        if version_dir.name in quarantined:
            sys.stderr.write(
                f"ai-maestro-janitor: cached version {version_dir.name} is "
                f"quarantined — trying an older version\n"
            )
            continue
        ok, reason = _verify_version(version_dir)
        if ok and not _pin_rejects(version_dir, version_dir.name, PLUGIN_DATA_ROOT):
            os.execv(str(target), [str(target), *sys.argv[1:]])
        why = reason if not ok else "pin-mismatch"
        sys.stderr.write(
            f"ai-maestro-janitor: cached version {version_dir.name} failed integrity "
            f"verify ({why}) — trying an older version\n"
        )
    if newest_runnable is not None:
        sys.stderr.write(
            "ai-maestro-janitor: NO cached version verified clean — running the newest "
            "runnable version anyway (fail-open: a dead heartbeat is worse)\n"
        )
        os.execv(str(newest_runnable), [str(newest_runnable), *sys.argv[1:]])
    sys.exit("no runnable ai-maestro-janitor dispatch.py in any cached version")


if __name__ == "__main__":
    main()
