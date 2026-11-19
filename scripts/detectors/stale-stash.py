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

Dedup keys on the commit sha of each stash, not on the positional `stash@{N}` ref. A
push or a drop shifts every positional index, but a stash commit sha never changes, so
reordering `git stash list` does not re-emit a stash that was already nudged. The suggested
commands name the sha for the same reason.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
from exe_path import exe  # noqa: E402


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
        [exe("git"), "rev-parse", "--git-dir"],
        cwd=str(project_root),
        capture_output=True, text=True, check=False,
        env=git_env,
    ).returncode != 0:
        state.log_line("stale-stash", "not a git repo — skipping")
        return 0

    # Stash list with one tab-separated row per entry: ref, commit sha, ISO-8601
    # creation time (committer date — what the user expects), short
    # subject. `--format` uses %x09 for literal tab so subjects with
    # colons or whitespace parse cleanly downstream.
    proc = subprocess.run(
        [exe("git"), "stash", "list", "--format=%gd%x09%H%x09%cI%x09%s"],
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
        parts = raw_line.split("\t", 3)
        if len(parts) < 4:
            continue
        ref, sha, iso_ts, subject = parts

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

        # WHY the key is the commit sha and not the ref: the ref is the positional
        # stash@{N} at emit time, and it shifts when a newer stash is pushed above
        # this one or a stash is dropped, so keying on it re-emitted every older
        # stash after each push. The commit sha of a stash never changes, so it is stable.
        # The key moved from the crc32 form to the sha form, so each already-nudged stash is reported once more after the upgrade, by design.
        line = dedupe.emit_once(
            seen,
            f"stash@{sha}@w{week_bucket}",
            f"[stale-stash] commit {sha} '{clean_subject}' has been stashed for {age_days}d. "
            f"Inspect with: git stash show -p {sha}. To reapply and remove it, or to discard it, find the line of git stash list --format='%gd %H' whose hash is {sha}. "
            f"Then run git stash pop <that stash@{{N}}> to reapply and remove it, or git stash drop <that stash@{{N}}> to discard it, where stash@{{N}} is the first field of that line. "
            f"Indexes shift when stashes are pushed or dropped, so look the index up at the moment of use and never reuse one from an earlier advisory.",
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big("stale-stash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
