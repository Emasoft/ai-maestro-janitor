#!/usr/bin/env python3
"""Do the janitor's canonical rotator root and the legacy root agree?

ai-maestro's `lib/oauth-rotator/slots.ts` (rotatorRoot, ~:105-110) returns the
canonical root when it holds a state.json, and otherwise falls through SILENTLY
to the legacy root. Both daemons share one credential store today only because
the canonical file exists. If it ever disappears — a plain janitor plugin
uninstall removes the DATA dir — ai-maestro adopts whatever the legacy root says,
which on this host is three months stale and names a DIFFERENT live account.
This is the probe for TRDD-RSSN9A0P; it answers whether that trap is armed.

Contract (the canary grammar, TRDD-6054NY8H CORRECTION 6):
  prints `CANARY roots-compared` on any run that really ran — its ABSENCE is
  verdict 2 (could-not-run) and must never be read as "cleared";
  prints `DESYNC` iff the two roots disagree on live account or slot set.

Absent legacy root is the DESIRABLE end state, not a failure: it means the trap
cannot arm, so it prints `agree`. A probe whose success condition makes it crash
is a probe that reports could-not-run forever — the failure this file exists to
avoid, so do not "helpfully" turn a missing file back into an exception.
"""

from __future__ import annotations

import json
import os
import sys

CANONICAL = "~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator/state.json"
LEGACY = "~/.claude/account-rotator/state.json"
BEACON = "~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator/live-identity.json"


def load(path: str) -> dict | None:
    """Parsed state, or None when the root simply is not there.

    Unreadable-but-present is NOT None: it is a real failure and propagates, so
    a corrupt state.json surfaces as could-not-run rather than as agreement.
    """
    full = os.path.expanduser(path)
    if not os.path.exists(full):
        return None
    with open(full, encoding="utf-8") as fh:
        return json.load(fh)


def split_brain(canonical: dict) -> None:
    """Does the rotator's BOOKKEEPING agree with the last OBSERVED live credential?

    The ai-maestro peer raised the failure this catches, and it is the dangerous
    one: if a state write is discarded while a live switch proceeds, the keychain
    holds account B while state.json still says account A. Each reader is
    self-consistent alone, so nothing notices — unlike an empty state, which
    announces itself.

    This compares state.json against `live-identity.json`, and that is NOT a
    value compared with itself: rotator.py:882 re-stamps the beacon ONLY when the
    credential actually CHANGED, and :2962 writes it from a session context that
    touches neither state.json nor the keychain. Two independent writers, so
    agreement is evidence.

    It deliberately does NOT read the keychain item itself, which would be the
    stronger check. A probe on a heartbeat cadence that reads a `security` item
    is how the July incident produced hundreds of "Security wants to use the
    login keychain" dialogs with no Always-Allow button (memory: macos-keychain).
    A detector that locks the owner out of their own machine is not a detector.
    """
    beacon = load(BEACON)
    if beacon is None:
        print("beacon-absent (no live-identity.json — cannot cross-check bookkeeping)")
        return
    if beacon.get("email") != canonical.get("live_email") or beacon.get("fp") != canonical.get("live_fp"):
        print(
            f"SPLITBRAIN state says {canonical.get('live_email')!r}/{str(canonical.get('live_fp'))[:8]} "
            f"but last observed live was {beacon.get('email')!r}/{str(beacon.get('fp'))[:8]}"
        )


def main() -> int:
    # The canary is printed BEFORE any fallible work, and that ordering is the
    # whole point of it. It proves the probe EXECUTED; if it is emitted after
    # the reads, a corrupt or half-written state.json suppresses it too, and the
    # field silently degrades from proof-of-execution to proof-of-success — the
    # same two-valued collapse the canary was introduced to prevent.
    print("CANARY roots-compared")
    canonical, legacy = load(CANONICAL), load(LEGACY)

    if canonical is None:
        # The trap is ARMED right now: ai-maestro would take the legacy root.
        print("DESYNC canonical root missing — ai-maestro would silently adopt the legacy state")
        return 0
    # Runs BEFORE the legacy-absent early return, deliberately. Retiring the
    # legacy root is the goal, and once it is gone that return fires on every
    # run — so a split-brain check placed after it would silently stop executing
    # at exactly the moment the rest of this file starts reporting "agree".
    split_brain(canonical)

    if legacy is None:
        # COUPLING, named so a future reader knows where to re-check: this
        # sentence is a claim about ai-maestro's `lib/oauth-rotator/slots.ts`
        # ::rotatorRoot — the legacy root is the ONLY fallback it has. If a
        # different fallback is ever reintroduced there, this branch reports
        # "agree" about a hazard that has simply moved somewhere else. Raised by
        # the ai-maestro peer, who owns that resolver.
        print("agree (no legacy root — slots.ts::rotatorRoot has no other fallback)")
        return 0

    c_live, l_live = canonical.get("live_email"), legacy.get("live_email")
    c_slots = set(canonical.get("slots") or {})
    l_slots = set(legacy.get("slots") or {})
    if c_live != l_live or c_slots != l_slots:
        print(f"DESYNC live {c_live!r} vs {l_live!r}; slots {len(c_slots)} vs {len(l_slots)}")
    else:
        print("agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
