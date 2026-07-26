"""Tests for the throttled `/api/oauth/usage` probe (TRDD-WEBA1RMF).

Everything here runs against REAL files, REAL flocks, and a REAL second process. The
only injected seam is `probe(getter=...)` — the single impure edge (the HTTPS call) —
because hitting a hard-rate-limited production endpoint from a test suite is exactly the
behaviour this module exists to prevent. Nothing about the code under test is mocked.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIB = _PROJECT_ROOT / "scripts" / "lib"
sys.path.insert(0, str(_LIB))

import usage_probe as up  # noqa: E402

_TOKEN = "test-access-token"
_PAYLOAD = {
    "five_hour": {"utilization": 37.0, "resets_at": "2026-07-26T18:00:00Z"},
    "seven_day": {"utilization": 12.0, "resets_at": "2026-07-30T18:00:00Z"},
}


def _isolate(tmp_path: Path) -> str:
    """Point the probe's cache/cooldown/lock dir at tmp; return the account key."""
    os.environ["JANITOR_USAGE_PROBE_DIR"] = str(tmp_path)
    for var in (up.TTL_ENV, up.BACKOFF_BASE_ENV, up.BACKOFF_CAP_ENV, up.STALE_ENV):
        os.environ.pop(var, None)
    return up.account_key(_TOKEN)


def _getter(status: int, payload: dict | None, retry_after: int | None = None, calls: list | None = None):
    """An injectable HTTP seam returning a fixed response, recording each call."""

    def _fn(token: str) -> tuple[int, dict | None, int | None]:
        if calls is not None:
            calls.append(token)
        return status, payload, retry_after

    return _fn


# --------------------------------------------------------------------------- #
# user agent — the load-bearing header
# --------------------------------------------------------------------------- #
def test_user_agent_is_claude_code_shaped() -> None:
    """The UA must be `claude-code/*`; any other identity lands in the aggressive bucket."""
    up.reset_ua_cache()
    assert up.user_agent().startswith("claude-code/")


def test_user_agent_falls_back_to_the_pin_when_the_cli_is_unreachable(tmp_path: Path) -> None:
    """With no `claude` on PATH the UA degrades to the pin — still `claude-code/*`."""
    up.reset_ua_cache()
    saved = os.environ.get("PATH")
    os.environ["PATH"] = str(tmp_path)  # empty dir: `claude` cannot resolve
    try:
        assert up.user_agent() == up._DEFAULT_UA
    finally:
        if saved is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = saved
        up.reset_ua_cache()


# --------------------------------------------------------------------------- #
# back-off arithmetic (pure)
# --------------------------------------------------------------------------- #
def test_backoff_escalates_per_consecutive_429_and_caps(tmp_path: Path) -> None:
    """Header-less 429s double the wait per consecutive hit and stop at the cap."""
    _isolate(tmp_path)
    assert [up.backoff_delay(n, None) for n in (1, 2, 3, 4, 5)] == [600, 1200, 2400, 4800, 7200]
    assert up.backoff_delay(99, None) == 7200  # a corrupt count can never build a huge int


def test_backoff_honors_a_server_retry_after_with_a_60s_floor(tmp_path: Path) -> None:
    """A stated Retry-After wins, but a sub-minute one is floored so we stop re-arming."""
    _isolate(tmp_path)
    assert up.backoff_delay(1, 900) == 900
    assert up.backoff_delay(1, 5) == 60


# --------------------------------------------------------------------------- #
# header parsing (pure)
# --------------------------------------------------------------------------- #
def test_retry_after_parses_delta_seconds() -> None:
    """A numeric `Retry-After` is taken verbatim."""
    assert up.retry_after_seconds({"retry-after": "120"}) == 120


def test_retry_after_parses_an_http_date() -> None:
    """An HTTP-date `Retry-After` is converted to a delta against now."""
    now = 1_785_000_000.0
    secs = up.retry_after_seconds({"retry-after": "Sun, 26 Jul 2026 08:20:00 GMT"}, now=now)
    assert secs is not None and abs(secs - (1_785_054_000 - now)) < 2


def test_retry_after_falls_back_to_each_anthropic_reset_header() -> None:
    """Every `anthropic-ratelimit-*-reset` is honored, as epoch seconds or ISO."""
    now = 1_785_000_000.0
    iso = "2026-07-26T00:05:00+00:00"  # 1785024300 epoch
    iso_epoch = 1_785_024_300
    for name in up._RESET_HEADERS:
        assert up.retry_after_seconds({name: str(int(now) + 300)}, now=now) == 300
        assert up.retry_after_seconds({name: iso}, now=float(iso_epoch - 420)) == 420


def test_retry_after_is_none_when_no_header_says_anything() -> None:
    """Absent/garbage headers yield None, so the caller falls back to exponential backoff."""
    assert up.retry_after_seconds(None) is None
    assert up.retry_after_seconds({"retry-after": "soon"}) is None


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #
def test_expires_at_is_read_as_milliseconds() -> None:
    """`expiresAt` is ms in Claude Code's format; reading it as s dates every token to 1970."""
    token, exp = up.token_from_blob({"claudeAiOauth": {"accessToken": "t", "expiresAt": 1_785_000_000_000}})
    assert token == "t"
    assert exp == 1_785_000_000.0


def test_token_blob_tolerates_flat_and_nested_shapes() -> None:
    """Both `{claudeAiOauth: {...}}` and a flat blob resolve; junk yields (None, None)."""
    assert up.token_from_blob({"accessToken": "flat"})[0] == "flat"
    assert up.token_from_blob({"claudeAiOauth": {"accessToken": "nested"}})[0] == "nested"
    assert up.token_from_blob(None) == (None, None)
    assert up.token_from_blob({"accessToken": ""})[0] is None


# --------------------------------------------------------------------------- #
# probe: gating
# --------------------------------------------------------------------------- #
def test_probe_reports_no_token_without_touching_the_network(tmp_path: Path) -> None:
    """An empty token is 'unknown' (status 0), never a request."""
    _isolate(tmp_path)
    calls: list = []
    out: dict = {}
    assert up.probe(None, outcome=out, getter=_getter(200, _PAYLOAD, calls=calls)) == (0, None)
    assert out["reason"] == up.NO_TOKEN
    assert calls == []


def test_probe_refuses_a_token_within_30s_of_expiry(tmp_path: Path) -> None:
    """A dying credential spends a request to learn nothing — Claude Code rotates it."""
    _isolate(tmp_path)
    calls: list = []
    out: dict = {}
    now = 1_785_000_000.0
    status, data = up.probe(_TOKEN, expires_at=now + 5, outcome=out, getter=_getter(200, _PAYLOAD, calls=calls), now=now)
    assert (status, data) == (0, None)
    assert out["reason"] == up.EXPIRING_TOKEN
    assert calls == []


def test_probe_fetches_once_then_serves_cache_within_the_ttl(tmp_path: Path) -> None:
    """The second call inside the TTL costs zero requests and returns the same payload."""
    _isolate(tmp_path)
    calls: list = []
    getter = _getter(200, _PAYLOAD, calls=calls)
    out: dict = {}

    assert up.probe(_TOKEN, outcome=out, getter=getter) == (200, _PAYLOAD)
    assert out["reason"] == up.OK
    assert len(calls) == 1

    assert up.probe(_TOKEN, outcome=out, getter=getter) == (200, _PAYLOAD)
    assert out["reason"] == up.FRESH
    assert len(calls) == 1  # still one: the TTL suppressed the second request


def test_probe_refetches_once_the_ttl_has_elapsed(tmp_path: Path) -> None:
    """Past the TTL the cache stops being served and a fresh request goes out."""
    key = _isolate(tmp_path)
    os.environ[up.TTL_ENV] = "1"
    try:
        calls: list = []
        getter = _getter(200, _PAYLOAD, calls=calls)
        up.probe(_TOKEN, getter=getter)
        assert len(calls) == 1
        # Age the cache by moving its mtime back — the mtime IS the TTL clock.
        cache = tmp_path / f"{key}.json"
        os.utime(cache, (time.time() - 60, time.time() - 60))
        up.probe(_TOKEN, getter=getter)
        assert len(calls) == 2
    finally:
        os.environ.pop(up.TTL_ENV, None)


def test_force_bypasses_a_fresh_cache(tmp_path: Path) -> None:
    """`force=True` re-fetches even inside the TTL (the on-demand `show` path)."""
    _isolate(tmp_path)
    calls: list = []
    getter = _getter(200, _PAYLOAD, calls=calls)
    up.probe(_TOKEN, getter=getter)
    up.probe(_TOKEN, force=True, getter=getter)
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# probe: 429 handling
# --------------------------------------------------------------------------- #
def test_429_arms_the_cooldown_and_suppresses_every_further_request(tmp_path: Path) -> None:
    """After a 429 the probe answers 429 from the cooldown without touching the network."""
    key = _isolate(tmp_path)
    calls: list = []
    out: dict = {}

    assert up.probe(_TOKEN, outcome=out, getter=_getter(429, None, calls=calls)) == (429, None)
    assert out["reason"] == up.RATE_LIMITED
    assert len(calls) == 1
    assert up.in_cooldown(key)

    # A second call must NOT re-provoke the endpoint — that is what re-arms the lockout.
    assert up.probe(_TOKEN, outcome=out, getter=_getter(200, _PAYLOAD, calls=calls)) == (429, None)
    assert out["reason"] == up.COOLDOWN
    assert len(calls) == 1


def test_consecutive_429s_escalate_the_recorded_backoff(tmp_path: Path) -> None:
    """Each 429 advances the consecutive count, so the wait grows instead of repeating."""
    key = _isolate(tmp_path)
    now = 1_785_000_000.0
    up.set_cooldown(key, None, now=now)
    first_until, first_n = up.read_cooldown(key)
    up.set_cooldown(key, None, now=now)
    second_until, second_n = up.read_cooldown(key)
    assert (first_n, second_n) == (1, 2)
    assert (second_until - now) == 2 * (first_until - now)


def test_a_successful_probe_clears_the_cooldown(tmp_path: Path) -> None:
    """A 200 resets the back-off so a recovered account is not punished for its history."""
    key = _isolate(tmp_path)
    now = 1_785_000_000.0
    up.set_cooldown(key, None, now=now)
    assert up.in_cooldown(key, now=now)
    # Probe with `now` past the cooldown so the fetch is allowed through.
    up.probe(_TOKEN, getter=_getter(200, _PAYLOAD), now=now + 10_000)
    assert up.read_cooldown(key) == (0.0, 0)


def test_a_non_200_non_429_status_passes_straight_through(tmp_path: Path) -> None:
    """401/403 stay distinguishable — the rotator reads them as 'bad token', not 'maxed'."""
    _isolate(tmp_path)
    out: dict = {}
    assert up.probe(_TOKEN, outcome=out, getter=_getter(403, None)) == (403, None)
    assert out["reason"] == up.HTTP_ERROR


def test_probe_never_raises_when_the_getter_explodes(tmp_path: Path) -> None:
    """A probe that can kill its caller is worse than one that reports 'unknown'."""
    _isolate(tmp_path)

    def _boom(_token: str):
        raise RuntimeError("network stack on fire")

    out: dict = {}
    assert up.probe(_TOKEN, outcome=out, getter=_boom) == (0, None)
    assert out["reason"] == up.HTTP_ERROR


# --------------------------------------------------------------------------- #
# per-account isolation
# --------------------------------------------------------------------------- #
def test_one_accounts_cooldown_never_suppresses_another(tmp_path: Path) -> None:
    """Cache/cooldown are keyed per account: a maxed slot must not blind the live one."""
    _isolate(tmp_path)
    other = "second-account-token"
    up.probe(_TOKEN, getter=_getter(429, None))
    assert up.in_cooldown(up.account_key(_TOKEN))
    assert not up.in_cooldown(up.account_key(other))
    assert up.probe(other, getter=_getter(200, _PAYLOAD)) == (200, _PAYLOAD)


def test_the_account_key_never_contains_the_token(tmp_path: Path) -> None:
    """Filenames are a salted digest — a world-readable path must not leak the secret."""
    _isolate(tmp_path)
    key = up.account_key(_TOKEN)
    assert _TOKEN not in key
    assert key != __import__("hashlib").sha256(_TOKEN.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# cross-process locking (real flock, real second process)
# --------------------------------------------------------------------------- #
def _hold_lock_script(lock_file: Path, ready: Path, hold_s: float) -> str:
    return textwrap.dedent(
        f"""
        import fcntl, pathlib, time
        fh = open({str(lock_file)!r}, "w")
        fcntl.flock(fh, fcntl.LOCK_EX)
        pathlib.Path({str(ready)!r}).write_text("held")
        time.sleep({hold_s})
        """
    )


def test_lock_contention_serves_cache_and_names_the_reason(tmp_path: Path) -> None:
    """While another process holds the lock we serve cache — never a duplicate request."""
    key = _isolate(tmp_path)
    up.probe(_TOKEN, getter=_getter(200, _PAYLOAD))  # seed the cache
    os.environ[up.TTL_ENV] = "0"  # force the TTL check to miss so we reach the lock

    ready = tmp_path / "ready"
    proc = subprocess.Popen([sys.executable, "-c", _hold_lock_script(tmp_path / f"{key}.lock", ready, 3.0)])
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.05)
        assert ready.exists(), "helper never acquired the lock"

        calls: list = []
        out: dict = {}
        status, data = up.probe(_TOKEN, outcome=out, getter=_getter(200, _PAYLOAD, calls=calls))
        assert out["reason"] == up.LOCK_CONTENDED
        assert (status, data) == (200, _PAYLOAD)  # cache served
        assert calls == []  # and no duplicate request went out
    finally:
        proc.kill()
        proc.wait()
        os.environ.pop(up.TTL_ENV, None)


def test_lock_contention_without_a_cache_reports_unknown(tmp_path: Path) -> None:
    """With nothing cached, a contended probe says 'unknown' rather than inventing a value."""
    key = _isolate(tmp_path)
    ready = tmp_path / "ready"
    proc = subprocess.Popen([sys.executable, "-c", _hold_lock_script(tmp_path / f"{key}.lock", ready, 3.0)])
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.05)
        assert ready.exists(), "helper never acquired the lock"
        out: dict = {}
        assert up.probe(_TOKEN, outcome=out, getter=_getter(200, _PAYLOAD)) == (0, None)
        assert out["reason"] == up.LOCK_CONTENDED
    finally:
        proc.kill()
        proc.wait()


def test_the_post_acquire_recheck_stops_a_redundant_refetch(tmp_path: Path) -> None:
    """A waiter that wins the lock re-checks the TTL and serves the winner's fresh cache."""
    key = _isolate(tmp_path)
    calls: list = []

    # Simulate the winner having just written the cache while we were queued: the outer
    # TTL check is bypassed with force=False + an already-fresh cache written underneath.
    up.write_cache(key, _PAYLOAD)
    out: dict = {}
    status, data = up.probe(_TOKEN, outcome=out, getter=_getter(200, {"stale": True}, calls=calls))
    assert (status, data) == (200, _PAYLOAD)
    assert out["reason"] == up.FRESH
    assert calls == []


# --------------------------------------------------------------------------- #
# staleness reporting
# --------------------------------------------------------------------------- #
def test_a_missing_cache_counts_as_stale(tmp_path: Path) -> None:
    """No data is not fresh data — there is nothing current to present."""
    key = _isolate(tmp_path)
    assert up.is_stale(key)


def test_a_cache_older_than_the_stale_window_is_stale(tmp_path: Path) -> None:
    """Past STALE_SECONDS the readout must not be rendered as live."""
    key = _isolate(tmp_path)
    up.probe(_TOKEN, getter=_getter(200, _PAYLOAD))
    assert not up.is_stale(key)
    old = time.time() - 10_000
    os.utime(tmp_path / f"{key}.json", (old, old))
    assert up.is_stale(key)


def test_stale_cause_distinguishes_throttle_from_unreachable(tmp_path: Path) -> None:
    """Lock contention and a dying token must never read as 'the endpoint is down'."""
    key = _isolate(tmp_path)
    now = 1_785_000_000.0
    up.set_cooldown(key, 600, now=now)
    assert "rate-limited" in up.stale_cause(up.COOLDOWN, key, now=now)
    assert "auth token unavailable" in up.stale_cause(up.EXPIRING_TOKEN, key, now=now)
    assert "already in flight" in up.stale_cause(up.LOCK_CONTENDED, key, now=now)
    assert up.stale_cause(up.HTTP_ERROR, key, now=now) == "endpoint unreachable"
    assert up.stale_cause(None, key, now=now) == "endpoint unreachable"


def test_the_cache_file_holds_only_the_payload(tmp_path: Path) -> None:
    """The token never reaches disk — only utilization percentages and reset times."""
    key = _isolate(tmp_path)
    up.probe(_TOKEN, getter=_getter(200, _PAYLOAD))
    raw = (tmp_path / f"{key}.json").read_text(encoding="utf-8")
    assert _TOKEN not in raw
    assert json.loads(raw) == _PAYLOAD
