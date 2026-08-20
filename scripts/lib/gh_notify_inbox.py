"""The fleet-wide GitHub notification inbox (TRDD-079778RM).

WHY THIS EXISTS. `gh-reply-watch` polls `GET /notifications`, whose `X-Poll-Interval: 60`
is scoped to the ACCOUNT, not the caller. Every janitor-armed project on this host shares
the one owner identity, so the floor has to be machine-wide — and it was, via a single
first-come stamp (janitor#215). That capped the account's poll rate correctly and starved
almost every project: measured 2026-08-20 with **40** armed projects, the whole
`gh-reply-watch.log` held **3** non-deferred lines, every other entry deferred. Crons fire
on synchronised 5-minute boundaries, so the same early project won the token nearly every
round. The lane looked healthy — an entry per heartbeat — while doing essentially nothing,
and a reply could sit undetected for weeks.

Raising the floor or granting per-project bypasses both push the ACCOUNT past the
documented interval (40 projects x any useful rate), trading a silent lane for rate-limit
failures everywhere. The fix is to stop making projects compete for the right to make the
same request: ONE fetch, fleet-wide, whose RESULT every project reads.

The split that makes this work: a notification list is ACCOUNT-scoped and therefore
identical for all 40 projects, while the `registry.json` that decides which threads matter
is PER-PROJECT. So the network call is shared and the filtering stays local — no project
sees another's threads, because no project's registry gained an entry.

This module owns the inbox's location, format, and retention, so the daemon writer and the
detector reader cannot drift about any of the three.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import global_state as gs
import state

_INBOX_NAME = "gh-notify-inbox.json"

# How long a thread stays in the inbox after its `updated_at`.
#
# This is the WORST-CASE LATENCY BOUND the TRDD asks to be stated in code: a project sees
# every reply whose thread was fetched within this window, so a project whose heartbeat is
# down for less than RETAIN_S misses nothing. 24 h is far above the ~5 min heartbeat and
# still small enough that the file stays a few hundred KB at fleet scale.
RETAIN_S = 86_400

# An inbox older than this is not trusted, and the reader falls back to polling `gh`
# itself under the old machine-wide floor. Set well above the daemon's write cadence so
# ordinary jitter never triggers a fallback, but low enough that a dead daemon degrades to
# the previous behaviour within one heartbeat instead of silently serving stale threads
# forever. A STALE INBOX MUST NOT LOOK LIKE AN EMPTY ONE: empty means "nothing new",
# stale means "nobody is fetching", and only the second warrants spending a poll token.
MAX_AGE_S = 600


def inbox_path() -> Path:
    """The one inbox, in the machine-global control dir — the same place the poll stamp
    already lives, because both answer a question about the ACCOUNT rather than a project."""
    return gs.control_dir() / _INBOX_NAME


def prune(threads: list[dict[str, Any]], now: int) -> list[dict[str, Any]]:
    """Drop threads whose `updated_at` fell out of the retention window.

    A thread with an unparseable or missing `updated_at` is KEPT, not dropped: the cost of
    keeping it is a few bytes and one extra dedupe check, while dropping it would silently
    lose a reply because GitHub changed a field's shape. Fail toward remembering.
    """
    cutoff = now - RETAIN_S
    kept: list[dict[str, Any]] = []
    for t in threads:
        raw = str((t or {}).get("updated_at") or "")
        if not raw:
            kept.append(t)
            continue
        try:
            # `2026-08-20T19:44:32Z` — normalise the military Z the API emits.
            stamp = int(
                time.mktime(time.strptime(raw.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z"))
            )
        except (ValueError, OverflowError):
            kept.append(t)
            continue
        if stamp >= cutoff:
            kept.append(t)
    return kept


def write(threads: list[dict[str, Any]], now: int | None = None) -> bool:
    """Publish a fetch, MERGED with what is still in retention. True iff it landed.

    MERGE, NEVER REPLACE — this is the correctness core. The fetch is incremental
    (`since=`), so a plain overwrite would publish only the newest delta and any project
    that had not read the previous one would never see it. Merging on the thread id keeps
    every project's view complete regardless of when it last read, which is what makes the
    latency bound above true for a slow project as well as a fast one.
    """
    now = int(time.time()) if now is None else now
    merged: dict[str, dict[str, Any]] = {}
    for t in read_threads(ignore_age=True) + list(threads):
        tid = str((t or {}).get("id") or "")
        if tid:
            merged[tid] = t  # later wins — the fresher copy of the same thread
    payload = {"fetched_at": now, "threads": prune(list(merged.values()), now)}
    try:
        state.atomic_write(inbox_path(), json.dumps(payload))
        return True
    except (OSError, TypeError, ValueError):
        return False  # best-effort: a failed publish degrades readers to a direct poll


def _load() -> dict[str, Any] | None:
    try:
        raw = inbox_path().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return None  # a torn/corrupt inbox is treated as absent, never as empty
    return doc if isinstance(doc, dict) else None


def age_s(now: int | None = None) -> int | None:
    """Seconds since the last successful fetch, or None when there is no readable inbox."""
    doc = _load()
    if doc is None:
        return None
    try:
        fetched = int(doc.get("fetched_at") or 0)
    except (TypeError, ValueError):
        return None
    if fetched <= 0:
        return None
    return max(0, (int(time.time()) if now is None else now) - fetched)


def is_fresh(now: int | None = None) -> bool:
    """True iff a fetch landed recently enough to be served instead of a direct poll."""
    age = age_s(now)
    return age is not None and age <= MAX_AGE_S


def read_threads(*, ignore_age: bool = False, now: int | None = None) -> list[dict[str, Any]]:
    """The retained notification threads, or `[]` when there is no usable inbox.

    `ignore_age` is for the WRITER's merge only — it must fold in what is on disk even
    when the previous fetch is old, or a daemon that was down for an hour would truncate
    the inbox to its first delta on the way back up.
    """
    doc = _load()
    if doc is None:
        return []
    if not ignore_age and not is_fresh(now):
        return []
    threads = doc.get("threads")
    return [t for t in threads if isinstance(t, dict)] if isinstance(threads, list) else []
