"""Throttled single-writer probe for Anthropic's `/api/oauth/usage` (TRDD-WEBA1RMF).

`/api/oauth/usage` is the ONLY source of the 5h/7d **utilization %** and `resets_at`
that the rotator's rotation decisions and the `window-burn-rate` detector are built on.
agentlensPro cannot substitute: it measures from OTEL telemetry, so it has a numerator
(tokens, cost) and no denominator — `get_account_status` reports `windowSource: none`
and a null window % until a capacity is configured. See TRDD-WEBA1RMF §2.

The endpoint is rate-limited HARD, and its 429s *worsen* under retry: knocking again on
a fixed short clock re-arms the server-side lockout so the token's usage bucket never
drains. Before this module the janitor probed the live account every 60 s (the
`oauth-rotator-tick` beat) plus every known account every 900 s (`window-burn-rate`),
with no cache, no cooldown, and no `Retry-After` handling — and it sent
`User-Agent: claude-account-rotator`, which per ccgauge lands the caller in an
aggressive bucket that 429s persistently. The cost of that 429 is not cosmetic: the
rotator reads a probe 429 as "this account is MAXED", so a throttle makes both the live
account and every alternate look unusable and rotation stalls exactly when it is needed
(the 2026-07-18 deadlock in TRDD-WBYFTU2L; the owner's repeated "you failed to rotate
again").

Technique credit: the throttling design (runtime `claude-code/*` UA, mtime-as-TTL-clock,
`Retry-After`/`anthropic-ratelimit-*-reset` honoring with exponential fallback,
non-blocking refresh lock, outcome-reason plumbing, honest staleness) is adapted from
**ccgauge** by pizzimenti — https://github.com/pizzimenti/ccgauge — MIT licensed.

Two janitor-specific extensions ccgauge does not need:

* **Per-account keying.** ccgauge only ever reads the one live credential; the rotator
  probes the live account AND every captured slot. Cache, cooldown, and lock are keyed
  by a salted digest of the access token, so one account's cooldown can never suppress
  another's probe. The token itself is never written anywhere.
* **An injectable HTTP getter.** Every rule below is then testable for real — no network,
  and no mocking of the code under test, only a seam at the one impure edge.

Never raises: every path degrades to "unknown", because a telemetry probe that can break
its caller is worse than one that returns nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess  # nosec B404 -- fixed argv (`claude --version`), no shell, bounded timeout
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    import fcntl
except ImportError:  # non-POSIX: degrade to unlocked best-effort (see `_acquire_lock`)
    fcntl = None  # type: ignore[assignment]

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import memory_scopes  # noqa: E402  -- sibling lib
import state  # noqa: E402  -- sibling lib
import tls_context  # noqa: E402  -- sibling lib (TRDD-X6I04SAO)

URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"

# The User-Agent is LOAD-BEARING, not cosmetic: without a `claude-code/*` UA the endpoint
# drops the caller into an aggressive rate-limit bucket that 429s persistently (ccgauge,
# README "The data source"). Derived from the installed CLI at runtime so it tracks Claude
# Code updates on its own; the pin is only the fallback for when `claude --version` cannot
# be read. Do NOT replace this with a static identity string — that is the bug this module
# exists to fix.
_DEFAULT_UA = "claude-code/2.1.212"
_UA_CACHE: str | None = None

TTL_ENV = "CLAUDE_PLUGIN_OPTION_USAGE_PROBE_TTL_SECONDS"
BACKOFF_BASE_ENV = "CLAUDE_PLUGIN_OPTION_USAGE_PROBE_BACKOFF_BASE_SECONDS"
BACKOFF_CAP_ENV = "CLAUDE_PLUGIN_OPTION_USAGE_PROBE_BACKOFF_CAP_SECONDS"
STALE_ENV = "CLAUDE_PLUGIN_OPTION_USAGE_PROBE_STALE_SECONDS"
TIMEOUT_ENV = "CLAUDE_PLUGIN_OPTION_USAGE_PROBE_TIMEOUT_SECONDS"

_TTL_DEFAULT = 600  # never re-fetch one account inside this window
_BACKOFF_BASE_DEFAULT = 600  # first 429 waits this long when the server states nothing...
_BACKOFF_CAP_DEFAULT = 7200  # ...doubling per consecutive 429, capped here (2h)
_STALE_DEFAULT = 1800  # past this a readout is "last known", never presented as live

RETIRE_ENV = "CLAUDE_PLUGIN_OPTION_USAGE_PROBE_RETIRE_SECONDS"
_RETIRE_DEFAULT = 86400  # past this an entry can never serve a read — delete it
_TIMEOUT_DEFAULT = 6

# A server-stated Retry-After is trusted, but floored: a 429 answered in under a minute is
# how a fixed-clock retry loop re-arms the lockout in the first place.
_MIN_SERVER_WAIT = 60

# Anthropic's own reset headers, tried in order after the standard `Retry-After`.
_RESET_HEADERS = (
    "anthropic-ratelimit-unified-reset",
    "anthropic-ratelimit-unified-5h-reset",
    "anthropic-ratelimit-requests-reset",
    "anthropic-ratelimit-tokens-reset",
)

# Outcome reasons — a stale readout must be able to name its REAL cause. Re-deriving the
# cause after the fact both mislabels lock contention as "endpoint down" and races the
# cooldown/token state it re-reads.
FRESH = "fresh"
OK = "ok"
COOLDOWN = "cooldown"
NO_TOKEN = "no_token"
EXPIRING_TOKEN = "expiring_token"
RATE_LIMITED = "429"
LOCK_CONTENDED = "lock_contended"
HTTP_ERROR = "http_error"

_NO_LOCK = object()  # sentinel: proceed unlocked (fcntl absent, or the FS refuses locks)


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
def _int_option(name: str, default: int) -> int:
    """A non-negative int knob, coerced exactly like every other janitor option."""
    return state.coerce_int(os.environ.get(name), default, var_name=name)


def ttl_seconds() -> int:
    return _int_option(TTL_ENV, _TTL_DEFAULT)


def stale_seconds() -> int:
    return _int_option(STALE_ENV, _STALE_DEFAULT)


def probe_dir() -> Path:
    """Where this module's per-account cache/cooldown/lock files live.

    Under the janitor's persistent plugin-DATA dir — NOT `~/.claude/`, which belongs to
    Claude Code. `JANITOR_USAGE_PROBE_DIR` overrides it for tests.
    """
    override = os.environ.get("JANITOR_USAGE_PROBE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "plugins" / "data" / memory_scopes.JANITOR_DATA_DIR_NAME / "usage-probe"


def account_key(token: str) -> str:
    """A stable, non-secret per-account filename key.

    A plain digest of the token would be a verifier for the secret itself (an attacker
    holding a candidate token could confirm it from a world-readable filename), so the
    digest is domain-separated by a fixed label. 16 hex is ample to separate a handful
    of accounts and short enough to keep paths readable.
    """
    return hashlib.sha256(b"janitor-usage-probe\0" + token.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    return probe_dir() / f"{key}.json"


def _cooldown_path(key: str) -> Path:
    return probe_dir() / f"{key}.cooldown"


def _lock_path(key: str) -> Path:
    return probe_dir() / f"{key}.lock"


# --------------------------------------------------------------------------- #
# user agent
# --------------------------------------------------------------------------- #
def user_agent() -> str:
    """`claude-code/<installed version>`, or the pinned fallback. Cached per process."""
    global _UA_CACHE
    if _UA_CACHE is not None:
        return _UA_CACHE
    ua = _DEFAULT_UA
    try:
        out = subprocess.run(  # nosec B603 B607 -- fixed argv, no shell, bounded timeout
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
        m = re.search(r"(\d+\.\d+\.\d+)", out or "")
        if m:
            ua = "claude-code/" + m.group(1)
    except Exception:
        pass
    _UA_CACHE = ua
    return ua


def reset_ua_cache() -> None:
    """Test seam: forget the per-process UA so a fresh derivation can be observed."""
    global _UA_CACHE
    _UA_CACHE = None


# --------------------------------------------------------------------------- #
# cache + cooldown
# --------------------------------------------------------------------------- #
def read_cache(key: str) -> dict | None:
    """The last payload cached for this account, or None. Never raises."""
    try:
        with _cache_path(key).open(encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def cache_age(key: str, *, now: float | None = None) -> float | None:
    """Seconds since this account's cache was written, or None when there is none.

    The cache file's mtime IS the TTL clock: no second state file to keep in step, and it
    survives restarts for free.
    """
    try:
        mtime = _cache_path(key).stat().st_mtime
    except Exception:
        return None
    return (time.time() if now is None else now) - mtime


def retire_seconds() -> int:
    """Age past which a probe entry is litter that can never serve a read again."""
    return _int_option(RETIRE_ENV, _RETIRE_DEFAULT)


def prune_retired(*, now: float | None = None, max_age_s: int | None = None) -> int:
    """Delete probe entries older than `max_age_s`. Returns how many files were removed.

    The cache key is a digest of the ACCESS TOKEN, and access tokens rotate (~8h per account
    in practice), so every rotation strands the previous entry forever: measured 51 files for
    3 accounts, the oldest 6 days old and describing a 7d window that had already reset. The
    dead entries are unreachable rather than dangerous — a lookup only ever computes the key
    for the CURRENT token — but they accumulate without bound, and any future code that scans
    the directory instead of computing a key would read one account's stale 97% as another
    account's current value.

    An entry older than `retire_seconds` cannot serve a read no matter what: `ttl_seconds`
    (600s) governs re-use and `stale_seconds` (1800s) governs whether it may even be shown,
    so a day-old entry is already unusable by both. Its cooldown is likewise long expired.
    Best-effort — a prune failure must never break the probe that triggered it."""
    at = time.time() if now is None else now
    cutoff = at - (retire_seconds() if max_age_s is None else max_age_s)
    removed = 0
    try:
        entries = list(probe_dir().glob("*.json"))
    except Exception:
        return 0
    for cache in entries:
        try:
            if cache.stat().st_mtime >= cutoff:
                continue
            stem = cache.with_suffix("")
            for path in (cache, Path(f"{stem}.cooldown"), Path(f"{stem}.lock")):
                try:
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
        except Exception:
            continue
    return removed


def write_cache(key: str, payload: dict) -> bool:
    """Persist a fetched payload atomically. Returns True iff the write landed.

    Pruning rides the write because that is the one event that can mint a NEW key (a rotated
    access token), so the directory can only grow at the moment it is also swept — no cadence
    stamp, no second caller to forget."""
    try:
        state.atomic_write(_cache_path(key), json.dumps(payload))
    except Exception:
        return False
    try:
        prune_retired()
    except Exception:
        pass
    return True


def read_cooldown(key: str) -> tuple[float, int]:
    """`(until_epoch, consecutive_429_count)`; `(0.0, 0)` when absent or unreadable."""
    try:
        raw = _cooldown_path(key).read_text(encoding="utf-8").strip()
    except Exception:
        return 0.0, 0
    try:
        data = json.loads(raw)
        return float(data.get("until", 0)), int(data.get("consecutive", 0))
    except Exception:
        return 0.0, 0


def in_cooldown(key: str, *, now: float | None = None) -> bool:
    until, _ = read_cooldown(key)
    return until > (time.time() if now is None else now)


def backoff_delay(consecutive: int, retry_after: int | None) -> int:
    """PURE: how long to wait after a 429.

    The server's own `Retry-After` wins when present (floored at `_MIN_SERVER_WAIT`);
    otherwise back off exponentially on the CONSECUTIVE count, capped. Escalating on the
    count is the load-bearing part — a run of header-less 429s answered on a fixed clock
    keeps re-arming the lockout instead of letting the usage bucket drain.
    """
    if retry_after and retry_after > 0:
        return max(int(retry_after), _MIN_SERVER_WAIT)
    base = _int_option(BACKOFF_BASE_ENV, _BACKOFF_BASE_DEFAULT)
    cap = _int_option(BACKOFF_CAP_ENV, _BACKOFF_CAP_DEFAULT)
    step = max(0, consecutive - 1)
    # Cap the exponent before shifting: a corrupt/huge consecutive count would otherwise
    # build an enormous int before min() ever discarded it.
    if step > 32:
        return cap
    return min(base * (2**step), cap)


def set_cooldown(key: str, retry_after: int | None = None, *, now: float | None = None) -> int:
    """Arm this account's 429 back-off; return the chosen delay in seconds."""
    _, prev = read_cooldown(key)
    consecutive = prev + 1
    delay = backoff_delay(consecutive, retry_after)
    at = time.time() if now is None else now
    try:
        state.atomic_write(
            _cooldown_path(key),
            json.dumps({"until": at + delay, "consecutive": consecutive}),
        )
    except Exception:
        pass
    return delay


def clear_cooldown(key: str) -> None:
    try:
        _cooldown_path(key).unlink()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def retry_after_seconds(headers: Mapping[str, str] | None, *, now: float | None = None) -> int | None:
    """PURE: back-off seconds parsed from a 429's headers, or None.

    Prefers the standard `Retry-After` (delta-seconds or an HTTP-date), then Anthropic's
    `anthropic-ratelimit-*-reset` (epoch seconds or an ISO timestamp).
    """
    if not headers:
        return None
    at = time.time() if now is None else now

    def _get(name: str) -> str | None:
        try:
            value = headers.get(name)
        except Exception:
            return None
        return value.strip() if isinstance(value, str) else None

    ra = _get("retry-after") or _get("Retry-After")
    if ra:
        if ra.isdigit():
            return int(ra)
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(ra)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return max(0, int(dt.timestamp() - at))
        except Exception:
            pass
    for name in _RESET_HEADERS:
        value = _get(name)
        if not value:
            continue
        if value.isdigit():
            epoch_delta = int(value) - int(at)
            if epoch_delta > 0:
                return epoch_delta
        iso_delta = _secs_until(value, now=at)
        if iso_delta and iso_delta > 0:
            return iso_delta
    return None


def _secs_until(iso: str | None, *, now: float | None = None) -> int | None:
    """Seconds from `now` until an ISO timestamp, or None when unparseable."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() - (time.time() if now is None else now))


HttpGet = Callable[[str], "tuple[int, dict | None, int | None]"]


def http_get(token: str) -> tuple[int, dict | None, int | None]:
    """`(status, payload, retry_after)`. status 0 == no HTTP response at all."""
    req = urllib.request.Request(  # nosec B310 -- hardcoded https endpoint, not caller-controlled
        URL,
        headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": OAUTH_BETA,
            "User-Agent": user_agent(),
            "Accept": "application/json",
        },
        method="GET",
    )
    timeout = _int_option(TIMEOUT_ENV, _TIMEOUT_DEFAULT)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=tls_context.verifying_context()) as resp:  # nosec B310 -- as above
            body = json.loads(resp.read().decode("utf-8", "replace"))
            status = int(getattr(resp, "status", 200) or 200)
            return status, (body if isinstance(body, dict) else None), None
    except urllib.error.HTTPError as exc:  # MUST precede URLError — it is a subclass
        return int(exc.code), None, retry_after_seconds(getattr(exc, "headers", None))
    except Exception:
        return 0, None, None


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #
#
# This module deliberately does NOT locate a credential — it is handed a token.
#
# ccgauge reads `~/.claude/.credentials.json`, which is the LINUX/WINDOWS store. On macOS
# Claude Code keeps the live OAuth blob in the **Keychain** and that file may be absent or
# stale, so copying ccgauge's reader here would silently return "no token" on the owner's
# own platform. `rotator.read_live_blob()` already owns the correct cross-platform ladder
# (keychain -> keychain mirror -> file), and duplicating it would be a second source of
# truth that drifts.
#
# There is a second, sharper reason: a Keychain read can raise the macOS authorization
# dialog, and an unattended probe on a 60 s beat is exactly how that becomes the dialog
# FLOOD recorded in the `macos-keychain` memory. Credential access stays behind the
# rotator's `safe_storage` gate (which carries the denied-latch); this module only ever
# receives the token the caller already resolved.
def token_from_blob(blob: Mapping[str, Any] | None) -> tuple[str | None, float | None]:
    """`(access_token, expires_at_epoch_seconds)` from a credential blob.

    Tolerates either the `claudeAiOauth` nesting or a flat blob. `expiresAt` is
    MILLISECONDS in Claude Code's format — reading it as seconds would place every expiry
    in 1970 and make every token look long-dead.
    """
    if not isinstance(blob, Mapping):
        return None, None
    inner = blob.get("claudeAiOauth")
    oauth: Mapping[str, Any] = inner if isinstance(inner, Mapping) else blob
    token = oauth.get("accessToken")
    exp = oauth.get("expiresAt")
    exp_s = (exp / 1000.0) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None
    return (token if isinstance(token, str) and token else None), exp_s


# --------------------------------------------------------------------------- #
# refresh lock
# --------------------------------------------------------------------------- #
def _acquire_lock(key: str) -> Any:
    """Grab this account's refresh lock, non-blocking.

    Returns the held handle, `None` when another refresh genuinely holds it (the caller
    serves cache instead of firing a duplicate request), or `_NO_LOCK` when locking is
    unavailable — `fcntl` missing, or a filesystem that refuses advisory locks (some
    NFS/FUSE homes). Degrading to unlocked is deliberate: serving cache forever on a home
    dir that cannot lock would silently disable the probe.
    """
    if not fcntl:
        return _NO_LOCK
    try:
        probe_dir().mkdir(parents=True, exist_ok=True)
        handle = _lock_path(key).open("w")
    except Exception:
        return _NO_LOCK
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    except OSError:
        handle.close()
        return _NO_LOCK
    return handle


def _release_lock(handle: Any) -> None:
    if handle is _NO_LOCK or handle is None:
        return
    try:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# core
# --------------------------------------------------------------------------- #
def probe(
    token: str | None,
    expires_at: float | None = None,
    *,
    force: bool = False,
    outcome: dict | None = None,
    getter: HttpGet | None = None,
    now: float | None = None,
) -> tuple[int, dict | None]:
    """Return `(status, payload)` for ONE account, fetching only when allowed.

    The status vocabulary is the rotator's existing load-bearing contract and is preserved
    exactly: `200` + payload, `429` == rate-limited, `401/403` == bad token, `0` ==
    unknown (no HTTP response, no usable token). Callers that already debounce a 429
    keep working unchanged; the only behavioural change is that a 429 now SUPPRESSES
    further probing for the back-off window instead of being re-provoked every 60 s.

    `outcome` (when given) receives `outcome["reason"]` — see the reason constants.
    `getter` is the injectable HTTP seam; production leaves it None.
    """

    def _out(reason: str) -> None:
        if outcome is not None:
            outcome["reason"] = reason

    at = time.time() if now is None else now
    if not token:
        _out(NO_TOKEN)
        return 0, None
    key = account_key(token)

    if not force:
        age = cache_age(key, now=at)
        if age is not None and age < ttl_seconds():
            cached = read_cache(key)
            if cached is not None:
                _out(FRESH)
                return 200, cached

    # A cooldown is reported as 429 rather than swallowed: for a genuinely maxed account
    # that IS the truth, and it keeps the rotator's existing 429 debounce semantics intact
    # while costing zero requests.
    if in_cooldown(key, now=at):
        _out(COOLDOWN)
        return 429, None

    if expires_at and expires_at < at + 30:
        # Expired or about to be. Claude Code rotates its own credential; probing with a
        # token that dies mid-flight would spend a request to learn nothing.
        _out(EXPIRING_TOKEN)
        return 0, None

    # Serialize the fetch across processes. The 60 s daemon beat and a session detector can
    # both clear the checks above before either fires; without this they double-hit the
    # endpoint and, both reading the same consecutive-429 count, fail to escalate the
    # back-off. The loser serves cache rather than sending a duplicate request.
    lock = _acquire_lock(key)
    if lock is None:
        cached = read_cache(key)
        _out(LOCK_CONTENDED)
        return (200, cached) if cached is not None else (0, None)
    try:
        # Re-check under the lock: whoever won it may have just refreshed the cache or
        # armed the cooldown. Skipping this re-check is a real TOCTOU — it is how a queue
        # of waiters each fires one now-redundant request the moment the winner releases.
        if in_cooldown(key, now=at):
            _out(COOLDOWN)
            return 429, None
        if not force:
            age = cache_age(key, now=at)
            if age is not None and age < ttl_seconds():
                cached = read_cache(key)
                if cached is not None:
                    _out(FRESH)
                    return 200, cached

        try:
            status, payload, retry_after = (getter or http_get)(token)
        except Exception:
            # `http_get` already swallows everything, so this only catches an injected
            # getter. It still belongs here: "never raises" must hold for every caller,
            # and a probe that can kill the daemon tick is worse than one that says
            # "unknown".
            _out(HTTP_ERROR)
            return 0, None
        if status == 200 and payload is not None:
            # A failed cache write is survivable but NOT free: the mtime clock never
            # advances, so the next call re-fetches. On a read-only DATA dir the cooldown
            # write fails too, which means no throttling at all — the probe degrades to
            # exactly the pre-TRDD-WEBA1RMF behaviour rather than to silence. That is the
            # right trade (live data beats no data), but it is why the DATA dir being
            # writable is a real precondition, not an incidental one.
            write_cache(key, payload)
            clear_cooldown(key)
            _out(OK)
            return 200, payload
        if status == 429:
            set_cooldown(key, retry_after, now=at)
            _out(RATE_LIMITED)
            return 429, None
        _out(HTTP_ERROR)
        return status, None
    finally:
        _release_lock(lock)


def is_stale(key: str, *, now: float | None = None) -> bool:
    """True when this account's cached readout must NOT be presented as live.

    A missing cache counts as stale: there is nothing current to show. Callers must also
    suppress any countdown derived from a stale `resets_at` — the window it describes may
    already have reset, so rendering it live is worse than rendering nothing.
    """
    age = cache_age(key, now=now)
    return age is None or age > stale_seconds()


def stale_cause(reason: str | None, key: str, *, now: float | None = None) -> str:
    """A human cause for a stale readout, named from `probe`'s own outcome.

    Derived from what the probe actually DID, so lock contention and a mid-rotation
    credential are never mislabelled as "the endpoint is down".
    """
    if reason in (COOLDOWN, RATE_LIMITED):
        until, _ = read_cooldown(key)
        wait = max(0, int(until - (time.time() if now is None else now)))
        return f"endpoint rate-limited (429) — next retry in {wait // 60}m{wait % 60:02d}s"
    if reason in (NO_TOKEN, EXPIRING_TOKEN):
        return "auth token unavailable (login expired or refreshing) — retry next turn"
    if reason == LOCK_CONTENDED:
        return "another refresh is already in flight — retry next turn"
    return "endpoint unreachable"
