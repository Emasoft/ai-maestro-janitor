#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""repin-integrity — manual escape hatch for the C3 last-good pin (F2,
TRDD-ZM5LZ24Y).

WHY THIS EXISTS. `certify_newest_if_clean` (scripts/lib/version_update_lib.py)
is the daemon's PERIODIC re-pin: on every `task_version_update` fire it
certifies the newest cached version that is runnable, non-quarantined, and
C2-clean, PROVIDED the GitHub `releases/latest` tag agrees (the F1 provenance
gate). That gate fails CLOSED on any machine that cannot reach GitHub this
fire — offline, no `gh` on PATH, no releases yet — which means such a machine
can NEVER advance its own pin through the daemon path alone. This command is
the deliberate manual override for exactly that situation (and for "the
daemon is down" more generally): a human running it IS the provenance F1
would otherwise require from the release channel.

It reuses `certify_newest_if_clean`'s OWN predicate (runnable + non-quarantined
+ C2-clean) via its `force=True` parameter — it does NOT re-derive a second,
subtly different notion of "the version we trust". A second predicate is
exactly how the earlier quarantine defect got into this codebase (see the
quarantine-walk comment in `certify_newest_if_clean`); this script is
deliberately thin so there is nowhere for that mistake to recur.

The override is ALWAYS announced on stdout in plain words, so an unattended
reader (a log, a heartbeat transcript, another agent) can never mistake this
manual certification for the daemon's automatic, provenance-gated one.

Exit code:
  0 — certified a version (newly pinned) OR the pin was already current
  1 — nothing on disk was eligible to pin (no cached versions / none
      runnable+clean+non-quarantined) — the pin, if any, is left untouched
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import version_update_lib as vu  # type: ignore[import-not-found]  # noqa: E402

# This script lives at `<plugin-root>/scripts/repin_integrity.py`, so the
# plugin root (the version-stamped cache dir, e.g. `.../ai-maestro-janitor/
# 3.2.0/`) is one level up — same resolution `daemon.py::task_version_update`
# uses for `plugin_root`. Its PARENT is the cache root `certify_newest_if_clean`
# walks (every `<cache>/<version>/` sibling).
_PLUGIN_ROOT = _HERE.parent


def main() -> int:
    # resolve_cache_parent guards the staged-DATA-closure case (TRDD-ZM5LZ24Y):
    # invoked from the cache it returns _PLUGIN_ROOT.parent unchanged; invoked
    # from a staged copy it falls back to the canonical cache instead of
    # silently walking an empty dir.
    cache_parent = vu.resolve_cache_parent(_PLUGIN_ROOT)

    print(
        "MANUAL OVERRIDE: bypassing the F1 provenance gate (TRDD-ZM5LZ24Y). "
        "This certification is NOT confirmed against the GitHub release "
        "channel — you, running this command deliberately, are the "
        "provenance. The daemon's own periodic re-pin never does this.",
    )

    prior = vu.read_last_good()
    prior_version = prior.get("version") if prior else None

    pinned = vu.certify_newest_if_clean(cache_parent, force=True)

    current = vu.read_last_good()
    current_version = current.get("version") if current else None

    if pinned is not None:
        print(f"certified last-good={pinned} (C3 manifest-HMAC trust anchor written)")
        return 0
    if current_version is not None and current_version == prior_version:
        # certify_newest_if_clean's own "already current" short-circuit — the
        # anchor already names the version the stub would actually exec.
        print(f"already current: last-good={current_version} (nothing to do)")
        return 0
    print(
        "nothing eligible to pin: no cached version is both runnable and "
        "C2-clean and non-quarantined — the existing pin (if any) was left "
        "untouched",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
