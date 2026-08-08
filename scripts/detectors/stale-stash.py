#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Stale-stash detector — Python port of stale-stash.sh.

Surfaces git stashes that have been sitting longer than the configured
threshold. A forgotten stash is a real WIP signal: the work is
recoverable but invisible to `git status` and `git log`, so it rarely
surfaces until a stash conflict on `git pull` reminds the user it
exists. Threshold default 30d; tune via `stash_stale_days` userConfig.

Dedup uses (stash-ref, creation-timestamp) so dropping/reapplying a
stash rotates the dedup key naturally, and `git stash list` reordering
after a `git stash drop stash@{0}` doesn't false-trigger a re-emit on
stashes that were already nudged.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


def _parse_iso8601(ts: str) -> Optional[int]:
    """ISO-8601 with timezone → epoch seconds. None on parse failure."""
    s = ts.strip()
    # Python 3.11+ accepts the trailing `Z` natively; 3.10 needs a swap.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Stash creation times are always tz-aware in `%cI` output, but
        # if a future git version drops the offset we'd be vulnerable to
        # local-tz drift. Treat naive as UTC rather than local for
        # consistency with `git stash list --format=%cI` semantics.
        return int(dt.timestamp())
    return int(dt.timestamp())


def _crc32(s: str) -> int:
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "stale-stash-seen.txt"
    stale_days = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_STASH_STALE_DAYS"), 30)

    project_root = state.project_root()

    # Read-only: GIT_OPTIONAL_LOCKS=0 so these never take .git/index.lock and
    # collide with a concurrent `publish.py` commit (janitor#245).
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"

    if subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(project_root),
        capture_output=True, text=True, check=False,
        env=git_env,
    ).returncode != 0:
        state.log_line("stale-stash", "not a git repo — skipping")
        return 0

    # Stash list with one tab-separated row per entry: ref, ISO-8601
    # creation time (committer date — what the user expects), short
    # subject. `--format` uses %x09 for literal tab so subjects with
    # colons or whitespace parse cleanly downstream.
    proc = subprocess.run(
        ["git", "stash", "list", "--format=%gd%x09%cI%x09%s"],
        cwd=str(project_root),
        capture_output=True, text=True, check=False,
        env=git_env,
    )
    if proc.returncode != 0:
        state.log_line("stale-stash", "git stash list failed — skipping")
        return 0

    if not proc.stdout.strip():
        return 0

    now = int(time.time())
    threshold_sec = stale_days * 86400

    for raw_line in proc.stdout.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t", 2)
        if len(parts) < 3:
            continue
        ref, iso_ts, subject = parts

        created = _parse_iso8601(iso_ts)
        if created is None:
            state.log_line("stale-stash", f"could not parse date '{iso_ts}' for {ref} — skipping entry")
            continue

        age_sec = now - created
        if age_sec < threshold_sec:
            continue

        age_days = age_sec // 86400
        # Truncate to 80 then defang any [/] that might mimic our marker
        # convention. A stash subject is fully user-controlled; without
        # sanitization a subject like `[janitor-resume] do X` would render
        # as a near-identical line to our own [janitor-X] markers.
        clean_subject = state.sanitize_for_drift_line(subject[:80])

        # Re-emit at most once per week of additional staleness so a
        # long-ignored stash doesn't go fully silent — the user still
        # gets a cue every 7d.
        week_bucket = age_sec // (7 * 86400)

        # Use the ref together with the ISO timestamp as the entropy of
        # the dedup key: `git stash drop` shifts higher refs down by one,
        # but the timestamp of any given stash never changes once committed.
        fp = _crc32(f"{ref}\t{iso_ts}")

        line = dedupe.emit_once(
            seen,
            f"stash@{fp}@w{week_bucket}",
            f"[stale-stash] {ref} '{clean_subject}' has been stashed for {age_days}d. "
            f"Inspect with: git stash show -p {ref}. Then either reapply (git stash pop {ref}) "
            f"or discard (git stash drop {ref}).",
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big("stale-stash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
