"""Human-notification channel — DAEMON-ONLY (TRDD-4649ZLE0, ARCHITECTURE.md §5, ratified).

The owner's directive (2026-07-17, verbatim intent): *"if the claude instance of that
project is not executed for weeks, any error will remain undetected … report any error
and any output of the security scanners to the human, maybe via some notification …
so the human will start the claude code instance interested by the issue."* The one
process guaranteed alive (the daemon) gets a severity-gated path to a human; the
notification's job is to get the human to START the right Claude — never to carry the
full report (the body lives in the ticket/TRDD/ledger the message's project points at).

DAEMON-ONLY by design: N sessions pushing would stampede the channel with duplicates — the
single-writer daemon is the only steady caller (the per-session surface is the heartbeat
drift line / findings ledger, TRDD-FENWWB4E). `notify_episode` is the machine-wide
once-per-episode form (USER ruling 2026-10-21); its key lives in the same `notify-sent.txt`,
so the one session-side exception (a hung or dead daemon cannot report its own stall) shares
the daemon's key and still yields ONE notification.

Two tiers:
  1. native desktop notification — DEFAULT ON, zero config: macOS `osascript
     display notification`, Linux `notify-send` when present. Best-effort, no secrets.
  2. generic HTTPS webhook — OPT-IN via `CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL`:
     one JSON POST (`{"text": …}`) covers Slack, Telegram bot URLs, Discord, ntfy.sh.
     No per-service SDKs, no stored tokens beyond the URL the user supplied. Email is
     deliberately NOT built (SMTP credential handling ≫ value; a webhook covers it).

Anti-spam gates, ALL required before a push leaves the machine:
  * severity ≥ `CLAUDE_PLUGIN_OPTION_NOTIFY_MIN_SEVERITY` (default HIGH);
  * content-hash dedupe — the same message NEVER pushes twice (`notify-sent.txt` in the
    global-state dir, structurally trimmed);
  * a rolling 24 h cap (`CLAUDE_PLUGIN_OPTION_NOTIFY_MAX_PER_DAY`, default 3) — pushes
    over the cap collapse into ONE per-day digest line naming how many were folded.

Fail-open everywhere: a notification failure must never break the daemon loop.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional, TypeVar

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import global_state as gs  # noqa: E402  -- sibling lib (daemon-side state dir)
import state  # noqa: E402  -- sibling lib
import terminal_trigger  # noqa: E402  -- applescript_quote (the ONE AppleScript escaper)
import tls_context  # noqa: E402  -- sibling lib (TRDD-X6I04SAO)

SENT_NAME = "notify-sent.txt"
DIGEST_STAMP_NAME = "notify-digest.ts"
_SENT_KEEP_LINES = 500
_T = TypeVar("_T")
_MAX_MSG_CHARS = 200

_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MAJOR": 2, "MEDIUM": 2, "LOW": 1, "MINOR": 1}

# Outcomes push() reports (logged by the caller; tests assert on them).
PUSHED = "pushed"
PUSHED_DIGEST = "pushed-digest"
DEDUPED = "deduped"
CAPPED = "capped"
BELOW_SEVERITY = "below-severity"
DISABLED = "disabled"
EPISODE_ACTIVE = "episode-active"  # notify_episode: this episode was already notified

# notify_episode: a condition absent for longer than this is a new episode.
EPISODE_FLAP_S = 3600
_EPISODE_PREFIX = "ep-"  # digest prefix of an episode (sent) line in the sent-store
_CLEAR_PREFIX = "epx-"  # digest prefix of an OBSERVED-clear line of the same episode
_EPISODE_PREFIXES = (_EPISODE_PREFIX, _CLEAR_PREFIX)


def enabled() -> bool:
    return state.is_truthy_env("CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED", True)


def webhook_url() -> str:
    return os.environ.get("CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL", "").strip()


def _min_severity_rank() -> int:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_NOTIFY_MIN_SEVERITY", "HIGH").strip().upper()
    return _SEV_RANK.get(raw, 3)


def _max_per_day() -> int:
    return state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_NOTIFY_MAX_PER_DAY"), 3)


def _sent_path() -> Path:
    return gs.global_state_dir() / SENT_NAME


def _clean(text: object, cap: int) -> str:
    """Sanitize + single-line + cap — same discipline as the findings ledger: summaries
    quote attacker-influenceable content (issue titles, repo names)."""
    return " ".join(state.sanitize_for_drift_line(str(text)).split())[:cap]


def build_message(*, sev: str, code: str, project: str, summary: str, hint: str = "/janitor-findings") -> str:
    """The one-line push body (ARCHITECTURE.md §5 shape): name the project so the human
    opens THAT project's Claude; carry a pointer, never the report."""
    sev_c = _clean(sev, 12).upper()
    code_c = _clean(code, 24)
    proj_c = _clean(project, 48)
    sum_c = _clean(summary, _MAX_MSG_CHARS)
    hint_c = _clean(hint, 48)
    return f"[janitor] {sev_c} {code_c} on {proj_c}: {sum_c} — open a Claude session there and run {hint_c}"


def _read_sent(now: int) -> tuple[set[str], int]:
    """(the set of already-pushed content hashes, pushes within the last 24 h). Episode lines
    (`ep-` digests, see `notify_episode`) are not pushes: they neither dedupe a content hash nor
    count against the daily cap."""
    hashes: set[str] = set()
    recent = 0
    try:
        for line in _sent_path().read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) != 2 or not parts[0].isdigit() or parts[1].startswith(_EPISODE_PREFIXES):
                continue
            ts, digest = int(parts[0]), parts[1]
            hashes.add(digest)
            if now - ts <= 86400:
                recent += 1
    except OSError:
        pass
    return hashes, recent


def _is_episode_line(line: str) -> bool:
    parts = line.split()
    return len(parts) == 2 and parts[1].startswith(_EPISODE_PREFIXES)


def _trim_sent_lines(lines: list[str]) -> list[str]:
    """Structural trim with SEPARATE budgets: push content-hash lines and episode lines each keep
    their newest `_SENT_KEEP_LINES`, so a burst of episode lines can never evict the permanent
    content-hash records of `push` (an evicted hash is a repeated notification)."""
    push_lines = [ln for ln in lines if not _is_episode_line(ln)]
    ep_lines = [ln for ln in lines if _is_episode_line(ln)]
    return push_lines[-_SENT_KEEP_LINES:] + ep_lines[-_SENT_KEEP_LINES:]


def _rewrite_sent_unlocked(drop: set[str], add: tuple[int, str]) -> None:
    """Drop every line whose digest is in `drop`, append `add`, trim, atomic-replace. The caller
    holds the sent-store lock. Dropping the digest's older lines keeps ONE line per episode digest."""
    path = _sent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    kept = [ln for ln in lines if not (len(ln.split()) == 2 and ln.split()[1] in drop)]
    kept.append(f"{add[0]} {add[1]}")
    state.atomic_write(path, "\n".join(_trim_sent_lines(kept)) + "\n")


def _record_sent(digest: str, now: int) -> None:
    """Locked append + structural trim."""
    try:
        _under_sent_lock(lambda: _append_sent_unlocked(digest, now))
    except Exception:  # noqa: BLE001 -- bookkeeping must never block a push
        pass


def _append_sent_unlocked(digest: str, now: int) -> None:
    """Append + structural trim (every append site must rotate or trim). The caller holds the
    sent-store lock: the trim is a read-modify-write that would drop a concurrent append."""
    _rewrite_sent_unlocked(set(), (now, digest))


def _under_sent_lock(fn: Callable[[], _T]) -> _T:
    """Run `fn` holding an exclusive flock on the sent-store lock file. WHY a lock: the daemon
    (alert thread, tick thread, main loop) and every session heartbeat write notify-sent.txt,
    and the trim rewrites the whole file, so an unlocked append can be lost to it - a lost
    record is a repeated notification. The lock lives in a sidecar because the trim replaces
    the sent file's inode, which would release a lock held on the file itself."""
    return under_lock(_sent_path().with_name(SENT_NAME + ".lock"), fn)


def under_lock(lock_path: Path, fn: Callable[[], _T]) -> _T:
    """Run `fn` holding an exclusive flock on the sidecar `lock_path` (created if missing).
    The shared helper for every read-modify-write of a state file several processes write."""
    import fcntl  # noqa: PLC0415 -- POSIX-only; global_state already requires it

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _last_episode_ts(digest: str) -> Optional[int]:
    """Newest timestamp recorded for an episode digest, or None."""
    last: Optional[int] = None
    try:
        for line in _sent_path().read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == digest and parts[0].isdigit():
                last = max(last or 0, int(parts[0]))
    except OSError:
        pass
    return last


def _episode_key(condition: str, kind: str, slot: str) -> str:
    return hashlib.sha256("\0".join((condition, kind, slot)).encode("utf-8")).hexdigest()[:12]


def notify_episode(
    *,
    condition: str,
    kind: str = "",
    slot: str = "",
    message: str,
    now: Optional[float] = None,
    runner: Optional[Callable[[list[str]], None]] = None,
    opener: Optional[Callable[[str, bytes], None]] = None,
    window_s: int = EPISODE_FLAP_S,
) -> str:
    """Notify ONCE per episode of a condition (USER ruling 2026-10-21: never repeat a
    notification already sent, never one copy per Claude Code instance).

    The episode key is condition + kind + slot, stored as an `ep-` line in the SAME sent-store
    `push` uses (`notify-sent.txt`), so the record survives a daemon restart and is shared by
    every process on the machine. The check, the record and the lock are one step: two callers
    racing on the same key get exactly one notification.

    An episode ends ONLY on an OBSERVED clear (`clear_episode`, called by whoever saw the
    condition go away) - never on a gap in observation: session heartbeats can be hours apart,
    and a silent gap says nothing about the condition. After a clear, the condition coming back
    within `window_s` is a flap (same episode, no notification); coming back later is a NEW
    episode. There is no daily repeat inside an episode.

    This is the owner-alarm path: it deliberately BYPASSES `push`'s severity floor and its
    rolling daily cap - an owner alarm must not be swallowed by either. Returns PUSHED,
    EPISODE_ACTIVE or DISABLED."""
    t = int(time.time()) if now is None else int(now)
    if not enabled():
        return DISABLED
    key = _episode_key(condition, kind, slot)
    sent_d, clear_d = _EPISODE_PREFIX + key, _CLEAR_PREFIX + key

    def _decide() -> bool:
        if _last_episode_ts(sent_d) is None:
            _rewrite_sent_unlocked(set(), (t, sent_d))
            return True
        cleared = _last_episode_ts(clear_d)
        if cleared is None:
            return False
        if t - cleared > window_s:
            _rewrite_sent_unlocked({sent_d, clear_d}, (t, sent_d))
            return True
        # Back within the flap window: the clear is void, same episode, no notification.
        _drop_clear_unlocked(clear_d)
        return False

    # Record BEFORE delivering: a crash or a failed delivery must never turn into a repeat.
    if not _under_sent_lock(_decide):
        return EPISODE_ACTIVE
    # The "[janitor]" prefix is added HERE, after sanitizing: _clean defangs bracketed markers.
    _deliver(f"[janitor] {_clean(message, _MAX_MSG_CHARS + 40)}", runner=runner, opener=opener)
    state.log_line("daemon", f"notify-episode: sent condition={_clean(condition, 48)} kind={_clean(kind, 48)}")
    return PUSHED


def _drop_clear_unlocked(clear_d: str) -> None:
    path = _sent_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not (len(ln.split()) == 2 and ln.split()[1] == clear_d)]
    state.atomic_write(path, "\n".join(kept) + "\n")


def clear_episode(
    *, condition: str, kind: str = "", slot: str = "", now: Optional[float] = None
) -> None:
    """Record that the caller OBSERVED the condition gone: the episode may end (see
    `notify_episode`). A no-op when no episode was ever notified, or when a clear is already
    recorded (the absence is measured from the FIRST observed clear). Never raises."""
    t = int(time.time()) if now is None else int(now)
    key = _episode_key(condition, kind, slot)
    sent_d, clear_d = _EPISODE_PREFIX + key, _CLEAR_PREFIX + key

    def _mark() -> None:
        if _last_episode_ts(sent_d) is not None and _last_episode_ts(clear_d) is None:
            _rewrite_sent_unlocked(set(), (t, clear_d))

    try:
        _under_sent_lock(_mark)
    except Exception:  # noqa: BLE001 -- bookkeeping must never break the caller
        pass


def _deliver(
    message: str,
    *,
    runner: Optional[Callable[[list[str]], None]] = None,
    opener: Optional[Callable[[str, bytes], None]] = None,
) -> None:
    """Fire both tiers, best-effort. `runner`/`opener` are injectable for tests (and so
    a unit test can NEVER pop a real desktop notification or hit a real URL)."""

    def _default_runner(argv: list[str]) -> None:
        subprocess.run(argv, capture_output=True, timeout=10, check=False)

    def _default_opener(url: str, payload: bytes) -> None:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=10, context=tls_context.verifying_context())  # noqa: S310 -- user-supplied webhook URL  # nosec B310 -- user-configured webhook, not attacker input

    run = runner or _default_runner
    open_ = opener or _default_opener

    # Tier 1 — native desktop notification (default-on, zero config).
    try:
        if sys.platform == "darwin":
            script = (
                f'display notification "{terminal_trigger.applescript_quote(message)}" '
                f'with title "ai-maestro-janitor"'
            )
            run(["osascript", "-e", script])
        elif shutil.which("notify-send"):
            run(["notify-send", "ai-maestro-janitor", message])
    except Exception:  # noqa: BLE001 -- best-effort; tier 2 still gets its chance
        pass

    # Tier 2 — user-configured webhook (opt-in; NEVER called without the URL).
    try:
        url = webhook_url()
        if url:
            open_(url, json.dumps({"text": message}).encode("utf-8"))
    except Exception:  # noqa: BLE001 -- a down webhook must not break the daemon
        pass


def push(
    *,
    sev: str,
    code: str,
    project: str,
    summary: str,
    hint: str = "/janitor-findings",
    now: Optional[int] = None,
    runner: Optional[Callable[[list[str]], None]] = None,
    opener: Optional[Callable[[str, bytes], None]] = None,
) -> str:
    """THE gated push. Returns the outcome constant (for the daemon log + tests).

    Gate order matters: cheap config gates first, then the dedupe (a repeat is the
    common case and must not count against the daily cap), then the cap — whose
    overflow collapses into one per-day digest so a burst can neither spam the human
    nor vanish silently.
    """
    t = int(time.time()) if now is None else int(now)
    if not enabled():
        return DISABLED
    if _SEV_RANK.get(_clean(sev, 12).upper(), 0) < _min_severity_rank():
        return BELOW_SEVERITY
    message = build_message(sev=sev, code=code, project=project, summary=summary, hint=hint)
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]
    sent, recent = _read_sent(t)
    if digest in sent:
        return DEDUPED
    if recent >= _max_per_day():
        # Over the cap: fold into ONE digest line per local day. The finding itself is
        # NOT lost — it is in the affected project's findings ledger; this only bounds
        # how often the human's phone/desktop buzzes.
        stamp = gs.global_state_dir() / DIGEST_STAMP_NAME
        today = time.strftime("%Y-%m-%d", time.localtime(t))
        try:
            if stamp.read_text(encoding="utf-8").strip() == today:
                _record_sent(digest, t)  # remember it so it never re-pushes later
                return CAPPED
        except OSError:
            pass
        try:
            state.atomic_write(stamp, today)
        except Exception:  # noqa: BLE001
            pass
        _deliver(
            f"[janitor] daily notification cap reached — more findings were recorded; "
            f"run /janitor-findings in the affected projects (latest: {_clean(project, 48)})",
            runner=runner,
            opener=opener,
        )
        _record_sent(digest, t)
        return PUSHED_DIGEST
    _deliver(message, runner=runner, opener=opener)
    _record_sent(digest, t)
    return PUSHED
