#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""runaway-file-growth — name a file that is growing without bound (TRDD-XM3FPJC0).

THE BLIND SPOT THIS CLOSES, measured 2026-08-15. A `[system-daemon-runaway]` alert fired naming a
hot process and a 96%-full disk. The disk was CHRONIC and unrelated; underneath it sat
`/tmp/claude/statusline-debug.log` at 231 MB, appended several times per second since 2026-08-04.
Eleven days, and nothing reported it — because the janitor's three purge detectors
(`reports-purge`, `screenshot-purge`, `trashcan-purge`) are AGE-based sweeps of directories the
janitor OWNS, and `state.rotate_log_if_big` bounds only the janitor's OWN logs. Nobody watched the
SIZE of a file written by someone else, so the only signal was a disk alarm that named the wrong
culprit.

Same family as `reports-purge` (TRDD-LCO8229M): forensics on a 39 GB fseventsd runaway
(TRDD-ZNN0UK5K) tied both disk pressure and fsevents volume to high-rate automated FS churn. A log
written several times a second IS that churn. The janitor already bounds its own contribution;
this makes it able to SEE everyone else's.

## It REPORTS. It never deletes, and that is a design decision, not a limitation

The files here belong to other tools, other projects, and the user. Age-purging a directory the
janitor owns is safe; deleting a 200 MB file because it is large is not — RULE 0 and the
cross-project rule both forbid it, and the one thing worse than an unnoticed balloon is a janitor
that silently eats a file somebody needed. So this NAMES the file, its size and its growth, and a
human decides. Reporting is the whole product.

Fail-open throughout: an unreadable root, a file that vanishes mid-scan, a permission error — all
degrade to "nothing to report". A tidiness advisory must never break a heartbeat.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402

ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_GROWTH_ENABLED"
MIN_BYTES_ENV = "CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_MIN_BYTES"
ROOTS_ENV = "CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_ROOTS"
GROWTH_FACTOR_ENV = "CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_GROWTH_FACTOR"

DEFAULT_MIN_BYTES = 100 * 1024 * 1024  # 100 MB — well above any healthy log, well under a dataset
# `/tmp/claude` is where the measured balloon lived: the Claude ecosystem's shared temp dir, which
# several tools append to and NO tool prunes. Deliberately a short list — a detector that walks
# large trees every hour becomes the FS churn it exists to report.
DEFAULT_ROOTS = ("/tmp/claude",)
# Re-alert only after this much growth. Without it an hourly detector repeats the same line
# forever, and a guard that cries the same wolf every hour is one the reader learns to skip.
DEFAULT_GROWTH_FACTOR = 2.0

_STATE_FILE = "runaway-file-growth.json"


def min_bytes() -> int:
    """The size at or above which a file is worth naming. 0 disables the detector entirely."""
    return state.coerce_int(
        os.environ.get(MIN_BYTES_ENV),
        DEFAULT_MIN_BYTES,
        detector_name="runaway-file-growth",
        var_name=MIN_BYTES_ENV,
    )


def growth_factor() -> float:
    """How much a already-reported file must grow before it is worth naming again.

    A malformed or non-positive value falls back to the default rather than disabling the
    re-alert: a typo in a knob must not silently turn a guard into a one-shot.
    """
    raw = (os.environ.get(GROWTH_FACTOR_ENV) or "").strip()
    if not raw:
        return DEFAULT_GROWTH_FACTOR
    try:
        parsed = float(raw)
    except ValueError:
        return DEFAULT_GROWTH_FACTOR
    return parsed if parsed > 1.0 else DEFAULT_GROWTH_FACTOR


def roots() -> list[str]:
    """The configured scan roots, `:`-separated. Empty entries are dropped."""
    raw = (os.environ.get(ROOTS_ENV) or "").strip()
    if not raw:
        return list(DEFAULT_ROOTS)
    return [part for part in (p.strip() for p in raw.split(":")) if part]


def scan_roots(root_paths: list[str], *, threshold: int) -> dict[str, tuple[int, float]]:
    """`{realpath: (size, mtime)}` for every regular file at or above `threshold`.

    KEYED ON THE RESOLVED REALPATH, and that is load-bearing rather than tidiness: on macOS `/tmp`
    is a symlink to `/private/tmp`, so scanning both roots reaches the SAME inode twice and would
    report one balloon as two separate runaways — a false finding that makes the real one harder to
    read. Resolving collapses them.

    Never raises. A root that does not exist, a directory that cannot be read, and a file that is
    unlinked between the walk and the `stat` all reduce this to fewer entries, never to an error.
    """
    found: dict[str, tuple[int, float]] = {}
    if threshold <= 0:
        return found
    for raw_root in root_paths:
        try:
            root = Path(raw_root).expanduser()
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    st = path.stat()
                    if st.st_size >= threshold:
                        found[str(path.resolve())] = (st.st_size, st.st_mtime)
                except OSError:
                    continue  # vanished mid-scan, or unreadable — not our business
        except OSError:
            continue
    return found


def worth_reporting(size: int, previous: int | None, *, factor: float) -> bool:
    """PURE. Is this size worth naming, given what was last reported for the same path?

    First sighting always reports. After that the file must have grown by `factor`, so a large but
    STATIC file (a dataset someone parked in the scan root) is named once and then left alone,
    while a genuine balloon keeps re-announcing itself as it doubles.

    A file that SHRANK (rotated, truncated) resets to "not worth reporting" and will report again
    on its next crossing — which is correct: the balloon a human just cleared should go quiet.
    """
    if previous is None or previous <= 0:
        return True
    return size >= previous * factor


def _fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def _fmt_age(seconds: float) -> str:
    secs = max(0, int(seconds))
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def main() -> int:
    state.init_state()

    if not state.is_truthy_env(ENABLED_ENV, True):
        return 0

    threshold = min_bytes()
    if threshold <= 0:
        return 0

    sd = state.state_dir()
    stamp = sd / _STATE_FILE
    try:
        import json  # noqa: PLC0415 -- only this path needs it

        previous_raw = json.loads(stamp.read_text(encoding="utf-8"))
        previous: dict[str, int] = {
            str(k): int(v) for k, v in previous_raw.items() if isinstance(v, (int, float))
        }
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        previous = {}

    factor = growth_factor()
    now = time.time()
    found = scan_roots(roots(), threshold=threshold)

    reported: dict[str, int] = {}
    for path, (size, mtime) in sorted(found.items()):
        prior = previous.get(path)
        if worth_reporting(size, prior, factor=factor):
            grew = f", grew from {_fmt_size(prior)}" if prior else ""
            print(
                f"[runaway-file-growth] {path} is {_fmt_size(size)}{grew} "
                f"(last written {_fmt_age(now - mtime)} ago) — nothing prunes it. "
                f"Find the writer and bound it; this detector only reports."
            )
            reported[path] = size
        else:
            reported[path] = prior if prior is not None else size

    # Only paths still at or above the threshold are carried forward, so a file that was cleared
    # drops out of the state and reports again if it ever comes back. Best-effort: losing the
    # stamp costs one duplicate line next hour, which is strictly better than raising here.
    try:
        import json  # noqa: PLC0415

        state.atomic_write(stamp, json.dumps(reported))
    except OSError:
        pass

    state.rotate_log_if_big("runaway-file-growth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
