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

import hashlib
import json
import os
import sys
from pathlib import Path

PLUGIN_CACHE_ROOT = (
    Path.home() / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor"
)


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


def main() -> int:
    if not PLUGIN_CACHE_ROOT.is_dir():
        sys.exit(f"ai-maestro-janitor cache root missing: {PLUGIN_CACHE_ROOT}")
    versions = sorted(
        (p for p in PLUGIN_CACHE_ROOT.iterdir() if p.is_dir()),
        key=_version_key,
    )
    if not versions:
        sys.exit("no ai-maestro-janitor versions cached")
    # C2 verify-before-exec (TRDD-T198DT1W): exec the NEWEST cached version that has a
    # runnable dispatch.py AND verifies clean against its integrity manifest. On an
    # EXPLICIT verify-fail (proven corruption) walk DOWN to the next-older clean
    # version. FAIL-OPEN cardinal rule: if NOTHING verifies clean, exec the newest
    # runnable version anyway — a possibly-corrupt heartbeat beats a DEAD one (a
    # bricked stub is the immortality bug this gate exists to prevent) — and warn on
    # stderr so a human learns. A version with no/unreadable/malformed manifest is
    # ACCEPTED by _verify_version (we never block what we cannot check).
    newest_runnable: Path | None = None
    for version_dir in reversed(versions):  # newest first
        target = version_dir / "scripts" / "dispatch.py"
        if not target.is_file():
            continue
        if newest_runnable is None:
            newest_runnable = target  # remember the fail-open fallback
        ok, reason = _verify_version(version_dir)
        if ok:
            os.execv(str(target), [str(target), *sys.argv[1:]])
        sys.stderr.write(
            f"ai-maestro-janitor: cached version {version_dir.name} failed integrity "
            f"verify ({reason}) — trying an older version\n"
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
