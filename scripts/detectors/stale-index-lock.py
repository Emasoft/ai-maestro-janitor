#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Stale-index-lock detector — self-clear an orphaned `.git/index.lock`.

A SIGKILLed or OOM-killed git writer leaves `.git/index.lock` behind forever
(janitor#245): git never gets a chance to clean up after itself, so every
later git write in the repo fails with "fatal: Unable to create
'.git/index.lock': File exists." — and an unattended run then stalls
indefinitely on a lock nothing will ever release. `git_utils.clear_stale_index_lock`
already implements the safe removal (no process holds the lock file itself,
no live git process could hold it, and it is old enough); this detector is
its only production caller, run on a heartbeat cadence so the lock clears
itself without a human having to notice and `rm` it by hand — see
`clear_stale_index_lock`'s own docstring for why the RECOVERY logic lives
in a periodic detector rather than a write path.

TEST SEAM: setting env `JANITOR_PS_SNAPSHOT` to a non-empty `ps` snapshot
string makes this detector pass it straight through as `clear_stale_index_lock`'s
`ps_snapshot=` argument instead of letting the helper gather a real one — the
same injection point `git_utils.clear_stale_index_lock` already exposes for
unit tests, extended here so the detector itself can be driven deterministically
regardless of what `git` processes happen to be running on the test host.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Locate scripts/lib relative to this file so the detector works regardless
# of the user's cwd. The same idiom is reused by every Python detector.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import git_utils  # noqa: E402
import state  # noqa: E402


def main() -> int:
    state.init_state()

    # Read-only probe: GIT_OPTIONAL_LOCKS=0 stops `git rev-parse` from taking
    # .git/index.lock for its optional stat-cache write-back, which would
    # otherwise collide with a concurrent writer (janitor#245).
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"

    proc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(state.project_root()),
        capture_output=True,
        text=True,
        check=False,
        env=git_env,
    )
    if proc.returncode != 0:
        state.log_line("stale-index-lock", "not a git repo — skipping")
        return 0

    threshold = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_STALE_INDEX_LOCK_MIN_AGE"), 1800
    )

    # TEST SEAM (mirrors `clear_stale_index_lock`'s own `ps_snapshot=`
    # parameter): when JANITOR_PS_SNAPSHOT is set and non-empty, pass its
    # value straight through instead of letting the helper gather a real `ps`
    # snapshot. This is what makes the detector's live-git guard
    # deterministic under test — a real snapshot on the CI/dev host almost
    # always has SOME `git` process running somewhere, which would otherwise
    # make "removed" vs "live-git" depend on the machine's current process
    # table rather than the fixture under test.
    injected_snapshot = os.environ.get("JANITOR_PS_SNAPSHOT") or None
    if injected_snapshot is not None:
        outcome = git_utils.clear_stale_index_lock(
            state.project_root(), min_age_s=threshold, ps_snapshot=injected_snapshot
        )
    else:
        # No ps_snapshot injected: the helper gathers its own and fails
        # CLOSED (removes nothing) when it cannot gather one — exactly the
        # behaviour we want from a detector, which has no caller to hand it
        # a snapshot.
        outcome = git_utils.clear_stale_index_lock(state.project_root(), min_age_s=threshold)

    seen = state.state_dir() / "stale-index-lock-seen.txt"

    # Outcomes that are ordinary, expected states — not a finding, print
    # nothing. "held"/"raced" are the new G0/TOCTOU guards' quiet outcomes,
    # alongside the pre-existing quiet set.
    if outcome in ("absent", "too-young", "live-git", "held", "raced"):
        # Forget any prior seen-key so a later genuine recovery/failure
        # re-emits instead of staying deduped against a stale bucket from an
        # earlier stall.
        dedupe.emit_forget(seen, "removed")
        dedupe.emit_forget(seen, "no-snapshot")
        dedupe.emit_forget(seen, "no-probe")
        dedupe.emit_forget(seen, "error")
        return 0

    if outcome == "removed":
        line = dedupe.emit_once(
            seen,
            "removed",
            "[stale-index-lock] Removed a stale .git/index.lock — no live git process held it and "
            f"it was older than {threshold}s. git writes in this repo were blocked until now "
            "(most likely a SIGKILLed or OOM-killed writer left it behind — janitor#245).",
        )
        if line is not None:
            print(line)
        state.rotate_log_if_big("stale-index-lock")
        return 0

    if outcome == "no-probe":
        # G0 (the lsof-based holder probe) could not determine whether the
        # lock is held — nothing was removed even if it is genuinely stale.
        line = dedupe.emit_once(
            seen,
            "no-probe",
            "[stale-index-lock] .git/index.lock may be stale but could not be verified safe to "
            "remove (holder probe unavailable — is lsof installed and on PATH?) — left in place.",
        )
        if line is not None:
            print(line)
        state.rotate_log_if_big("stale-index-lock")
        return 0

    if outcome == "error":
        # The rename-aside itself failed for a reason other than "already
        # gone" (e.g. permission denied) — a real problem worth surfacing.
        line = dedupe.emit_once(
            seen,
            "error",
            "[stale-index-lock] Attempted to clear a stale .git/index.lock but the rename failed "
            "(permission denied or similar) — left in place.",
        )
        if line is not None:
            print(line)
        state.rotate_log_if_big("stale-index-lock")
        return 0

    # outcome == "no-snapshot": the live-git guard was blind (ps could not be
    # gathered), so nothing was removed even if the lock is genuinely stale.
    line = dedupe.emit_once(
        seen,
        "no-snapshot",
        "[stale-index-lock] .git/index.lock may be stale but could not be verified safe to remove "
        "(process snapshot unavailable) — left in place.",
    )
    if line is not None:
        print(line)
    state.rotate_log_if_big("stale-index-lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
