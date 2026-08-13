"""External (ZERO model turn) handoff-and-clear — policy + composition (TRDD-PXP08ZQC).

The in-model lever (`dispatch._phase_idle_clear_nudge` → `/janitor-handoff-and-clear`) works,
but it costs what it is trying to save: the handoff is authored BY THE MODEL, so an abandoned
session pays a full turn on its huge context just to write the note that lets it shrink. This
module is the decision + composition half of doing the same thing from OUTSIDE the model — the
typist half already exists (`clear_trigger.py`'s verified injection chain).

Split exactly like the rest of the codebase: everything here is PURE (all runtime facts are
injected) so the gate is unit-testable without a live session. The I/O gatherer and the firing
live in `scripts/external_handoff_clear.py`.

## WHY THE TRIGGER IS NOT "the cache is expired"

The card was written as *idle + cache-expired + over-threshold*. Taken literally that lever is
DEAD on the machine it was written for, measured 2026-08-06: `ttl-regime.json` reports a probed
60-minute cache TTL and the armed cadence is `*/5 * * * *`, so a fire every 5 minutes keeps the
cache permanently warm and `cache_expired` is never true. That is the same shape
`cold_cache_compact` burned on twice — "a threshold high enough to never be met is a feature that
does not exist".

The card's *intent* is sound once expressed correctly: what costs money is not that the cache is
cold, it is that **the next fire will pay a cache MISS**. So trigger (a) asks exactly that —
`age_since_last_turn + seconds_until_next_fire >= ttl`. It fires in the idle gap BEFORE the
expensive fire, which is the timing contract the card asks for.

Trigger (b) is the owner's 2026-08-04 rule (nothing but beats for >= 1 h). It is what actually
bites in the warm case: a warm fire on a 460k context still re-reads ~10M weighted tokens, and
177.7M of one 7-day window went to heartbeat fires alone. Neither trigger subsumes the other, so
the gate ORs them and NAMES the one that fired — a lever that cannot say why it acted is one
nobody can tune.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import agentlens_probe as alp  # noqa: E402  -- sibling lib (the reactive expiry read)
import state  # noqa: E402  -- sibling lib

# --- config knobs (userConfig → env; read via the shared coercers) ----------
ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED"
MIN_CONTEXT_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_MIN_CONTEXT_TOKENS"
HEADROOM_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_HEADROOM_SECONDS"
USE_LLM_EXT_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_USE_LLM_EXT"

# DEFAULT OFF, deliberately, unlike its in-model sibling. `/clear` is unrecoverable, and this
# path fires it with NO model turn in front of it — nothing reads the handoff back before the
# context is gone. It ships opt-in until the card's "one observed end-to-end unattended cycle"
# acceptance box is ticked; flipping this default is that box's payoff, not its precondition.
DEFAULT_ENABLED = False
# Low on purpose. Size is NOT the reason to clear (owner directive 2026-08-04 dropped it from the
# in-model gate); it is only a floor below which clearing buys nothing measurable. Anything under
# this is cheap to keep, so leave it alone.
DEFAULT_MIN_CONTEXT_TOKENS = 150_000
# The chain types /clear, waits for the fresh session, then types the bootstrap. Firing with less
# than this before the next cron fire means the fire lands mid-chain — survivable (the injector
# waits for a free pane) but it wastes the very fire we were trying to prevent.
DEFAULT_HEADROOM_SECONDS = 60
# The prompt-cache TTL used when `ttl-regime.json` is absent/unreadable. 5 minutes is the
# platform's standard TTL and the SHORT side, so an unknown TTL biases toward "the next fire will
# miss" → toward acting. That is the safe direction here: the cost of a spurious clear on an
# abandoned session is one re-read of a link-only handoff.
DEFAULT_TTL_MINUTES = 5

_TTL_REGIME_FILE = "ttl-regime.json"

# Trigger names — returned in the verdict and written to the log, so a fire can always be
# attributed to the rule that caused it.
TRIGGER_NEXT_FIRE_MISSES = "next-fire-misses"
TRIGGER_LONG_IDLE = "long-idle"
TRIGGER_CACHE_CERTAIN_EXPIRED = "cache-certain-expired"
TRIGGER_RESUMED_COLD = "resumed-cold"

# The SessionStart `source` values that mean "Claude was loaded after being away", and so are
# the only ones the resume path may act on. `compact` and `clear` are excluded BY NAME because
# they are re-entries into a session that was JUST shrunk: acting on them is an infinite loop
# (shrink → SessionStart(compact) → shrink → …). Measured on this machine over the sessions
# recorded so far: compact 38, resume 7, clear 3, startup 0 — so `compact` is not a theoretical
# risk, it is the MOST COMMON source by a factor of five, and `startup` alone would never fire.
RESUME_SOURCES = frozenset({"resume", "startup"})

# The agentlensPro probe's command, overridable per the module's one integration pattern; an
# empty value disables the reactive trigger entirely and leaves the predictive one alone.
CACHE_EXPIRED_COMMAND_ENV = "CLAUDE_PLUGIN_OPTION_HEARTBEAT_CACHE_EXPIRED_COMMAND"

__all__ = [
    "ClearVerdict",
    "cache_certainly_expired",
    "compose_handoff",
    "compose_template_handoff",
    "enabled",
    "llm_ext_data_dir",
    "recent_messages",
    "run_llm_ext_summary",
    "headroom_seconds",
    "min_context_tokens",
    "next_fire_misses_cache",
    "read_ttl_minutes",
    "seconds_until_next_fire",
    "should_clear_externally",
    "terminal_from_record",
    "use_llm_ext",
]


def enabled() -> bool:
    return state.is_truthy_env(ENABLED_ENV, DEFAULT_ENABLED)


def min_context_tokens() -> int:
    return state.coerce_int(os.environ.get(MIN_CONTEXT_ENV), DEFAULT_MIN_CONTEXT_TOKENS)


def headroom_seconds() -> int:
    return state.coerce_int(os.environ.get(HEADROOM_ENV), DEFAULT_HEADROOM_SECONDS)


def use_llm_ext() -> bool:
    return state.is_truthy_env(USE_LLM_EXT_ENV, True)


# Bounded by US, not by the CLI. llm-externalizer 12.0.0 shipped with an unbounded body-read:
# its abort was disarmed once headers arrived, so its own timeout covered time-to-first-byte
# only and a stalled generation hung forever. A handoff composer that can hang is worse than
# one that degrades, because the `/clear` it precedes never happens and the session simply
# stops.
LLM_EXT_TIMEOUT_S = 240


def llm_ext_data_dir(binary: str) -> str:
    """The `CLAUDE_PLUGIN_DATA` value llm-externalizer needs, DERIVED from its own path.

    Without this set the launcher dies before doing any work:

        FATAL: native module 'better-sqlite3' is missing AND CLAUDE_PLUGIN_DATA is unset.
        The launcher cannot self-install without a persistent data directory.

    A janitor hook or detached child is exactly that context. Worse, the value is ANOTHER
    plugin's data dir and this host carries two candidates
    (`llm-externalizer-emasoft-plugins`, `llm-externalizer-inline`), so it cannot be guessed
    and picking wrong self-installs a second copy of a native module.

    Derived rather than hardcoded: the harness lays plugins out as
    `…/cache/<marketplace>/<plugin>/<version>/bin/llm-ext` and names the data dir
    `<plugin>-<marketplace>` — the same convention as this plugin's own
    `ai-maestro-janitor-ai-maestro-plugins`. So the binary that will actually run tells us
    which store belongs to it, and a reinstall under a different marketplace keeps working.
    Returns "" when the path does not match, so the caller degrades instead of inventing one.
    """
    parts = Path(binary).resolve().parts
    if "cache" not in parts:
        return ""
    i = parts.index("cache")
    if len(parts) < i + 3:
        return ""
    marketplace, plugin = parts[i + 1], parts[i + 2]
    data = Path.home() / ".claude" / "plugins" / "data" / f"{plugin}-{marketplace}"
    return str(data) if data.is_dir() else ""


def run_llm_ext_summary(
    transcript: str,
    *,
    timeout_s: int = LLM_EXT_TIMEOUT_S,
    runner: Any = None,
) -> str | None:
    """The session summary as TEXT, or None on any failure. NEVER raises.

    `--stdout` is used deliberately: without it stdout carries the report PATH and we would
    read a file the CLI may still be writing. Banner, progress and errors go to stderr, so
    stdout is the summary alone.

    The exit code is read from the process, never through a pipe — `llm-ext … | head` reports
    `head`'s status and the launcher's own failure becomes invisible.

    Returning None (rather than raising or returning a partial) is what makes the caller's
    degrade-to-template path reachable: every failure mode of a young CLI — missing binary,
    unresolvable data dir, non-zero exit, timeout, empty output — arrives here as the same
    answer, and the handoff still gets written.
    """
    binary = shutil.which("llm-ext")
    if not binary or not transcript or not Path(transcript).is_file():
        return None
    data_dir = llm_ext_data_dir(binary)
    if not data_dir:
        return None
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_dir)
    run = runner or subprocess.run
    try:
        proc = run(
            [binary, "session-summary", "--stdout", "--transcript", transcript],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except Exception:  # noqa: BLE001 - a handoff must survive ANY subprocess failure
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    out = (getattr(proc, "stdout", "") or "").strip()
    return out or None


# --- the fleet lane: at most N llm-ext calls in flight, machine-wide (owner, 2026-08-13) -----
#
# THE PROBLEM THIS EXISTS FOR, in the owner's words: *"20 compacting requests will surely result
# in a rate limit ban. to compact llm-externalizer uses free models on openrouter, and they will
# definitely won't sustain such simultaneous requests."*
#
# The trigger is a SessionStart on a cold cache, and the fleet does not wake up staggered — a
# laptop opening in the morning starts every session inside the same few seconds, so the naive
# design issues N simultaneous requests to a free-tier endpoint and every one of them 429s. The
# retry loop would then re-issue all N together on the same backoff schedule: a thundering herd,
# not a recovery.
#
# WHY A CONCURRENCY CAP AND NOT A SPACED QUEUE. The first version handed out start times spaced
# `interval` apart — session i started at `t0 + i*interval`. The owner then supplied the number
# that kills that design: *"according to the llm-externalizer tests, the compaction should take 3
# minutes on average. so the serialize option is very limited. after 3 requests in queue it must
# start to run them anyway."* At ~180 s per run, spacing 20 sessions even 45 s apart queues the
# last one 14 minutes out — long past any deadline, so it would never run at all and every late
# session would degrade to the template. Bounding CONCURRENCY instead bounds the load without
# bounding the throughput: three run at once, the fourth starts the moment one finishes.
#
# The lease is TTL'd rather than released-only, because the holder is a process that can be
# killed — an unreleased lease must expire on its own or one crash would wedge the lane forever.
FLEET_MAX_CONCURRENT_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_FLEET_MAX_CONCURRENT"
# The owner's number. 3 concurrent free-tier requests is a load an endpoint sustains; 20 is not.
DEFAULT_FLEET_MAX_CONCURRENT = 3
FLEET_LEASE_TTL_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_FLEET_LEASE_TTL_S"
# Comfortably over the ~180 s a run is expected to take AND over `LLM_EXT_TIMEOUT_S` (240 s), so
# a lease never expires under a call that is still legitimately running — that would admit a
# fourth worker while three are active, quietly defeating the cap.
DEFAULT_FLEET_LEASE_TTL_S = 300
# How long to wait between attempts to take a lease. Short enough that a freed lease is claimed
# promptly, long enough that waiting costs nothing measurable.
FLEET_POLL_S = 5.0
FLEET_LEASE_FILE = "external-clear-leases.json"
FLEET_LANE_LOCK = "external-clear-lane.lock"


def fleet_max_concurrent() -> int:
    """How many llm-ext summarize calls may run at once, machine-wide. 0 disables the lane."""
    return state.coerce_int(
        os.environ.get(FLEET_MAX_CONCURRENT_ENV, ""),
        DEFAULT_FLEET_MAX_CONCURRENT,
        detector_name="external-clear",
        var_name=FLEET_MAX_CONCURRENT_ENV,
    )


def fleet_lease_ttl_s() -> int:
    """Seconds a lease survives without release — the crash backstop, not the expected path."""
    return state.coerce_int(
        os.environ.get(FLEET_LEASE_TTL_ENV, ""),
        DEFAULT_FLEET_LEASE_TTL_S,
        detector_name="external-clear",
        var_name=FLEET_LEASE_TTL_ENV,
    )


SUMMARY_DEADLINE_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_SUMMARY_DEADLINE_S"
# How long the whole summarize effort — lane waits, attempts and backoff together — may run
# before the handoff degrades to the network-free template and the clear proceeds anyway.
#
# 540 s sits deliberately under the 600 s Claude Code allows a `command` hook by default: the
# hook is the caller, and a deadline ABOVE the hook's timeout is not a longer retry budget, it
# is a budget that gets killed mid-sleep with no handoff written and no clear fired. So the
# ceiling is chosen against the harness's limit, not against how long an outage might last —
# past this point the template fallback is strictly better than continuing to wait, because it
# shrinks the session NOW using only what is already on disk.
DEFAULT_SUMMARY_DEADLINE_S = 540


def summary_deadline_s() -> int:
    """Total seconds the summarize effort may take before degrading to the template handoff."""
    return state.coerce_int(
        os.environ.get(SUMMARY_DEADLINE_ENV, ""),
        DEFAULT_SUMMARY_DEADLINE_S,
        detector_name="external-clear",
        var_name=SUMMARY_DEADLINE_ENV,
    )


def _lane_dir() -> Path:
    """Where the lane files live — the machine-global janitor state dir.

    Imported lazily and defensively: this module is also imported by a SessionStart hook, and a
    global-state dir that cannot be resolved must degrade to "no lane" rather than break the
    caller. Losing the lane costs spacing; raising here would cost the whole clear.
    """
    try:
        import global_state as gs  # noqa: PLC0415

        return gs.global_state_dir()
    except Exception:  # noqa: BLE001 -- no global state ⇒ no lane, never a crash
        return Path()


def acquire_fleet_lease(
    *,
    now: float,
    max_concurrent: int,
    ttl_s: int,
    lane_dir: Path | None = None,
) -> str | None:
    """Take one of `max_concurrent` machine-wide llm-ext leases, or None when all are held.

    Read-prune-count-write happens under ONE exclusive flock, which is what makes the cap real:
    check-then-write in separate critical sections lets N racers all observe "2 active" and all
    admit themselves, which is precisely the simultaneous burst the lane exists to prevent.

    Expired leases are pruned on every acquire rather than on release, because the holder is a
    process that can be killed — if expiry depended on a clean release, one crash would wedge the
    lane permanently and every later session would degrade to the template forever.

    Fails OPEN, returning a sentinel lease: an unwritable dir, a missing `fcntl` or a corrupt
    store all admit the caller. A lane able to REFUSE would be able to block the clear, and an
    uncapped clear is merely rate-limited where a blocked one is the full-price turn.
    """
    if max_concurrent <= 0:
        return "lane-disabled"
    d = _lane_dir() if lane_dir is None else lane_dir
    if not d or not str(d):
        return "lane-unavailable"
    try:
        import fcntl  # noqa: PLC0415 -- POSIX-only; a platform without it simply has no lane
        import uuid  # noqa: PLC0415

        d.mkdir(parents=True, exist_ok=True)
        store = d / FLEET_LEASE_FILE
        with open(d / FLEET_LANE_LOCK, "a+") as fh:  # noqa: PTH123, SIM115
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    held = json.loads(store.read_text(encoding="utf-8"))
                    if not isinstance(held, dict):
                        held = {}
                except (OSError, ValueError):
                    held = {}
                live = {
                    k: float(v)
                    for k, v in held.items()
                    # A lease stamped absurdly far ahead is corruption or a clock jump, not a
                    # real holder — dropping it stops one bad write parking the lane for a day.
                    if isinstance(v, (int, float)) and now < float(v) <= now + ttl_s * 8
                }
                if len(live) >= max_concurrent:
                    state.atomic_write(store, json.dumps(live))
                    return None
                lease = uuid.uuid4().hex[:12]
                live[lease] = now + ttl_s
                state.atomic_write(store, json.dumps(live))
                return lease
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001 -- see the fail-open contract above
        return "lane-unavailable"


def release_fleet_lease(lease: str | None, *, lane_dir: Path | None = None) -> None:
    """Hand a lease back so the next waiter starts immediately. Best-effort by design.

    Releasing is the FAST path, not the correctness path — the TTL in `acquire_fleet_lease` is
    what guarantees the cap unwedges. So every failure here is swallowed: a lost release costs
    one slot for at most `ttl_s`, while raising would propagate into a caller whose only job is
    to shrink a session.
    """
    if not lease or lease.startswith("lane-"):
        return
    d = _lane_dir() if lane_dir is None else lane_dir
    if not d or not str(d):
        return
    try:
        import fcntl  # noqa: PLC0415

        store = d / FLEET_LEASE_FILE
        with open(d / FLEET_LANE_LOCK, "a+") as fh:  # noqa: PTH123, SIM115
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                held = json.loads(store.read_text(encoding="utf-8"))
                if isinstance(held, dict) and held.pop(lease, None) is not None:
                    state.atomic_write(store, json.dumps(held))
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001 -- the TTL is the real guarantee; see the docstring
        return


def await_fleet_lease(
    *,
    deadline: float,
    max_concurrent: int,
    ttl_s: int,
    lane_dir: Path | None = None,
    now_fn: Callable[[], float] = time.time,
    sleeper: Callable[[float], Any] = time.sleep,
    poll_s: float = FLEET_POLL_S,
) -> str | None:
    """Poll for a lease until one frees or `deadline` passes. None ⇒ the caller must NOT run.

    Waiting (rather than spacing) is what the owner's ~3-minute run time demands: the fourth
    session starts the moment one of the three finishes, so throughput is bounded by the cap and
    not by an ever-growing queue of reservations that would push late sessions past any deadline.
    """
    while True:
        lease = acquire_fleet_lease(
            now=float(now_fn()), max_concurrent=max_concurrent, ttl_s=ttl_s, lane_dir=lane_dir
        )
        if lease is not None:
            return lease
        if float(now_fn()) + poll_s >= deadline:
            return None
        sleeper(poll_s)


# --- classified attempts + the retry loop --------------------------------------------------

OUTCOME_OK = "ok"
# Retrying CANNOT help: the binary is not installed, or its data dir cannot be derived. Both are
# install-time facts, identical on attempt 100 as on attempt 1.
OUTCOME_PERMANENT = "permanent"
# Retrying is exactly right: a timeout, a dropped connection, a 429, a 5xx. The owner's case —
# *"even if it gets timeouts or error or disconnects from the internet for hours"*.
OUTCOME_TRANSIENT = "transient"
# A non-zero exit we cannot read. Retried (bias toward trying), but only while it keeps looking
# different — see `_UNKNOWN_REPEAT_GIVEUP`.
OUTCOME_UNKNOWN = "unknown"

# Substrings that mark a failure as worth retrying. Deliberately broad and lowercase-matched:
# a false "transient" costs one more retry, a false "permanent" costs the whole summary.
_TRANSIENT_MARKERS = (
    "timeout", "timed out", "etimedout", "econnreset", "econnrefused", "enotfound", "eai_again",
    "socket hang up", "network", "fetch failed", "getaddrinfo", "connection", "dns",
    "429", "rate limit", "rate-limit", "too many requests", "quota", "overloaded",
    "500", "502", "503", "504", "bad gateway", "service unavailable", "gateway timeout",
    "temporarily", "try again", "unavailable", "reset by peer", "tls", "ssl", "handshake",
)

# An UNKNOWN failure that reproduces identically this many times is treated as permanent. Without
# this, a genuinely broken invocation (wrong flag ⇒ exit 2 in 50 ms, forever) would burn the whole
# deadline before falling back — blocking a session start for ten minutes to learn nothing. The
# signature must be IDENTICAL, so a server rotating error messages keeps retrying.
_UNKNOWN_REPEAT_GIVEUP = 3

# Backoff between attempts, in seconds, then the last value repeats. Capped at 5 min: past that
# the lane's own spacing dominates and a longer sleep only delays the fallback.
_BACKOFF_S = (5, 10, 20, 40, 80, 160, 300)


@dataclass(frozen=True)
class SummaryAttempt:
    """One llm-ext invocation: what it produced, and whether trying again could help."""

    text: str | None
    outcome: str
    detail: str = ""


def classify_llm_ext_failure(*, returncode: int, stderr: str, timed_out: bool) -> str:
    """PURE: is this failure worth retrying? A timeout always is — it is the shape a stalled
    generation and a dead network both take."""
    if timed_out:
        return OUTCOME_TRANSIENT
    blob = (stderr or "").lower()
    if any(m in blob for m in _TRANSIENT_MARKERS):
        return OUTCOME_TRANSIENT
    return OUTCOME_UNKNOWN


def failure_signature(*, returncode: int, stderr: str) -> str:
    """A stable identity for 'the same failure again' — exit code + the first stderr line.

    First LINE only, because a wrapper that stamps a timestamp or a request id into later lines
    would otherwise make every identical failure look novel and defeat the give-up entirely.
    """
    first = ""
    for line in (stderr or "").splitlines():
        if line.strip():
            first = line.strip()[:200]
            break
    return f"{returncode}|{first}"


def attempt_llm_ext_summary(
    transcript: str,
    *,
    timeout_s: int = LLM_EXT_TIMEOUT_S,
    runner: Any = None,
) -> SummaryAttempt:
    """One classified llm-ext summarize attempt. NEVER raises.

    The classified sibling of `run_llm_ext_summary`, which keeps its `str | None` shape for the
    callers that only care whether they got text. Everything the retry loop needs to decide
    "again?" lives here, because collapsing every failure to None — as the original did — makes
    an unplugged network indistinguishable from an uninstalled binary, and those want opposite
    responses.
    """
    binary = shutil.which("llm-ext")
    if not binary:
        return SummaryAttempt(None, OUTCOME_PERMANENT, "llm-ext is not on PATH")
    if not transcript or not Path(transcript).is_file():
        return SummaryAttempt(None, OUTCOME_PERMANENT, "no readable transcript")
    data_dir = llm_ext_data_dir(binary)
    if not data_dir:
        return SummaryAttempt(None, OUTCOME_PERMANENT, "llm-ext data dir unresolvable")
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_dir)
    run = runner or subprocess.run
    try:
        proc = run(
            [binary, "session-summary", "--stdout", "--transcript", transcript],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SummaryAttempt(None, OUTCOME_TRANSIENT, f"timed out after {timeout_s}s")
    except Exception as exc:  # noqa: BLE001 - a handoff must survive ANY subprocess failure
        return SummaryAttempt(None, OUTCOME_TRANSIENT, f"spawn failed: {exc!r}")
    rc = int(getattr(proc, "returncode", 1) or 0)
    err = getattr(proc, "stderr", "") or ""
    if rc != 0:
        return SummaryAttempt(None, classify_llm_ext_failure(
            returncode=rc, stderr=err, timed_out=False
        ), failure_signature(returncode=rc, stderr=err))
    out = (getattr(proc, "stdout", "") or "").strip()
    if not out:
        # Exit 0 with nothing on stdout: the CLI answered without producing a summary. Retryable
        # — an empty generation is a normal free-tier outcome under load, not a broken install.
        return SummaryAttempt(None, OUTCOME_TRANSIENT, "empty summary on a zero exit")
    return SummaryAttempt(out, OUTCOME_OK)


def summarize_with_retry(
    transcript: str,
    *,
    deadline: float,
    now_fn: Callable[[], float] = time.time,
    sleeper: Callable[[float], Any] = time.sleep,
    attempt: Callable[[str], SummaryAttempt] | None = None,
    max_concurrent: int | None = None,
    lease_ttl_s: int | None = None,
    lane_dir: Path | None = None,
    jitter: Callable[[], float] | None = None,
    log: Callable[[str], Any] | None = None,
) -> SummaryAttempt:
    """Keep trying to summarize until it works, the deadline passes, or trying is pointless.

    THE CONTRACT THE OWNER ASKED FOR — *"the compacting must succeed no matter what"* — is met by
    the CALLER, not by this function, and the distinction matters. What must never fail is the
    CLEAR; this only decides how good the handoff that precedes it is. So the loop is bounded by
    `deadline` and returns a failed attempt rather than blocking forever: past that point the
    caller composes the template handoff (which needs no network at all) and clears anyway. A
    session held hostage to a summary is the very cost this feature exists to avoid — it would
    block a startup for hours to protect against a 700k-token turn, i.e. spend the thing it is
    saving.

    Three stopping rules, in order:
      * OK — done.
      * PERMANENT — no binary / no data dir / no transcript. Attempt 100 fails exactly like
        attempt 1, so stop at once rather than sleeping through the whole budget.
      * UNKNOWN repeating identically `_UNKNOWN_REPEAT_GIVEUP` times — a broken invocation
        reproducing byte-for-byte. Anything that keeps CHANGING keeps being retried.
    TRANSIENT never stops on its own: it retries until the deadline, which is what "disconnected
    for hours" needs.

    Every attempt — including retries — holds a fleet lease while it runs, so at most
    `max_concurrent` llm-ext calls exist machine-wide and N sessions recovering from one outage
    cannot re-form the herd on a shared backoff schedule.
    """
    run_attempt = attempt or attempt_llm_ext_summary
    cap = fleet_max_concurrent() if max_concurrent is None else max_concurrent
    ttl = fleet_lease_ttl_s() if lease_ttl_s is None else lease_ttl_s
    say: Callable[[str], Any] = log if log is not None else (lambda _msg: None)
    seen: dict[str, int] = {}
    last = SummaryAttempt(None, OUTCOME_TRANSIENT, "no attempt was made before the deadline")

    for i in range(len(_BACKOFF_S) * 64):  # a bound, not a policy — `deadline` is the policy
        now = float(now_fn())
        if now >= deadline:
            say(f"summary: deadline reached after {i} attempt(s) — {last.detail}")
            return SummaryAttempt(None, last.outcome, f"deadline: {last.detail}")

        lease = await_fleet_lease(
            deadline=deadline, max_concurrent=cap, ttl_s=ttl, lane_dir=lane_dir,
            now_fn=now_fn, sleeper=sleeper,
        )
        if lease is None:
            say("summary: fleet lane full through the deadline — degrading to the template")
            return SummaryAttempt(None, last.outcome, f"lane full: {last.detail}")
        # try/finally, not a bare call: an exception between here and the release would strand
        # the lease for its full TTL, shrinking the fleet's capacity by one for five minutes.
        try:
            last = run_attempt(transcript)
        finally:
            release_fleet_lease(lease, lane_dir=lane_dir)
        if last.outcome == OUTCOME_OK:
            say(f"summary: ok on attempt {i + 1}")
            return last
        if last.outcome == OUTCOME_PERMANENT:
            say(f"summary: permanent — {last.detail}; not retrying")
            return last
        if last.outcome == OUTCOME_UNKNOWN:
            seen[last.detail] = seen.get(last.detail, 0) + 1
            if seen[last.detail] >= _UNKNOWN_REPEAT_GIVEUP:
                say(f"summary: identical failure x{seen[last.detail]} — {last.detail}; giving up")
                return SummaryAttempt(None, OUTCOME_PERMANENT, f"repeated: {last.detail}")

        base = float(_BACKOFF_S[min(i, len(_BACKOFF_S) - 1)])
        # Jitter so a fleet that failed together does not retry together. The lane already
        # staggers starts; this keeps the SCHEDULES from re-converging across many rounds.
        spread: float = _default_jitter() if jitter is None else float(jitter())
        wait = base * spread
        say(f"summary: {last.outcome} — {last.detail}; retrying in {wait:.0f}s")
        remaining = deadline - float(now_fn())
        if remaining <= 0:
            return SummaryAttempt(None, last.outcome, f"deadline: {last.detail}")
        sleeper(min(wait, remaining))

    return last


def _default_jitter() -> float:
    """A multiplier in [0.75, 1.25]. Isolated so tests inject a deterministic one."""
    import random  # noqa: PLC0415 -- only the jittered path needs it

    return random.uniform(0.75, 1.25)  # noqa: S311 -- scheduling spread, not cryptography


def recent_messages(transcript: str, *, limit: int = 12) -> list[str]:
    """The last `limit` conversation turns as `ROLE: text` lines. ZERO model tokens.

    Read straight off the JSONL, so this part of the payload costs nothing and cannot be
    paraphrased — which matters because it is the part a resuming session checks its own
    understanding against. Tool payloads and thinking blocks are skipped: they are the bulk of
    a transcript and the least useful thing to restore into a context we are trying to empty.
    """
    out: list[str] = []
    try:
        with Path(transcript).open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message") or {}
                role = msg.get("role") or rec.get("type") or ""
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    text = " ".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    )
                else:
                    text = str(content or "")
                text = " ".join(text.split())
                if text:
                    out.append(f"{role.upper()}: {text}")
    except OSError:
        return []
    return out[-limit:]


def compose_handoff(
    inputs: HandoffInputs,
    *,
    now_iso: str,
    summary: str | None,
    tail: Sequence[str] = (),
    max_bytes: int = 8192,
) -> str:
    """The full injected payload: scriptable facts + llm-ext summary + a TRUNCATED tail.

    THE HARD CONSTRAINT (owner, 2026-08-12): the injection must not refill the context it was
    built to empty. A handoff that restores a large payload at session start pays back the
    cache-write we just avoided, one turn later — so the WHOLE payload carries one budget, not
    one per part. Three "small" parts add up.

    Priority under that single budget, and the order is the design:
      1. the scriptable facts — small, load-bearing, and the part that must never be
         paraphrased, so it is composed FIRST and always survives;
      2. the llm-ext summary — high value, absent whenever the CLI failed;
      3. the message tail — the ELASTIC part, trimmed from the OLDEST end because a resuming
         session needs the most recent exchanges.

    Truncation is STATED, never silent: a clipped tail reads as a complete record, which is
    worse than an explicitly short one — the reader cannot tell that anything is missing.
    """
    facts = compose_template_handoff(inputs, now_iso=now_iso, max_bytes=max_bytes)
    used = len(facts.encode("utf-8"))

    # ALLOCATION ORDER IS NOT OUTPUT ORDER. The tail is allocated BEFORE the summary even
    # though it prints last, because the summary is unbounded (7 KB in practice) and would
    # otherwise consume the whole remainder, leaving a handoff with no recent turns at all —
    # measured, after the first version did exactly that. The owner asked for the latest
    # messages explicitly, so the tail gets a guaranteed slice and the summary takes what is
    # left. Both remain elastic; only the scriptable facts are unconditional.
    tail_note_max = " — 9999 earlier message(s) dropped"
    tail_header = f"\n## Recent turns{tail_note_max}\n\n"
    tail_budget = min(max_bytes // 3, max(0, max_bytes - used - 200))
    kept: list[str] = []
    if tail and tail_budget > len(tail_header.encode("utf-8")):
        spent = len(tail_header.encode("utf-8"))
        for line in reversed(list(tail)):  # the OLDEST end is what gets dropped
            cost = len(line.encode("utf-8")) + 1
            if spent + cost > tail_budget:
                break
            kept.append(line)
            spent += cost
        kept.reverse()
        used += spent

    summary_part = ""
    if summary:
        head = "\n## Session summary (llm-externalizer, $0)\n\n"
        # The truncation NOTICE is charged before slicing, not appended after. Appending it to
        # a body already filled to `room` overran by exactly its own length every time
        # (measured: +38 at every budget — a constant offset is the signature of a fixed-size
        # string added outside the accounting).
        notice = "\n\n_(summary truncated to fit the handoff budget)_"
        room = max_bytes - used - len(head.encode("utf-8")) - len(notice.encode("utf-8")) - 8
        if room > 400:
            raw = summary.encode("utf-8")
            body = raw[:room].decode("utf-8", "ignore").rstrip()
            if len(raw) > room:
                body += notice
            summary_part = head + body

    parts = [facts]
    if summary_part:
        parts.append(summary_part)
    if kept:
        dropped = len(tail) - len(kept)
        note = f" — {dropped} earlier message(s) dropped" if dropped else ""
        parts.append(f"\n## Recent turns{note}\n\n" + "\n".join(kept))
    return "\n".join(parts)


# --- pure policy ------------------------------------------------------------


def seconds_until_next_fire(cron: str, now: int) -> int | None:
    """Seconds from `now` until the next `*/N * * * *` fire, or None when the cron is not that
    shape. PURE apart from reading the LOCAL timezone (cron fires on local wall-clock).

    Only the minute-step form the janitor arms is understood — anything else returns None so the
    caller falls back to "unknown headroom" rather than inventing a schedule from a cron it
    cannot actually read (the same contract as `orphaned_resume.cadence_seconds`).

    The wrap is computed over the real minute-of-hour set, not by adding the step: cron's `*/7`
    fires at minutes 0,7,…,56 and then 0, a FOUR-minute gap. `cur_min + step` would report 7
    there and we would think we had headroom we do not have.
    """
    field_min = (cron or "").strip().split(" ")[0] if cron else ""
    if not field_min.startswith("*/"):
        return None
    step_raw = field_min[2:]
    if not step_raw.isdigit():
        return None
    step = int(step_raw)
    if step <= 0 or step > 59:
        return None
    tm = time.localtime(now)
    fire_minutes = [m for m in range(60) if m % step == 0]
    later = [m for m in fire_minutes if m > tm.tm_min]
    if later:
        minutes_ahead = later[0] - tm.tm_min
    else:
        minutes_ahead = (60 - tm.tm_min) + fire_minutes[0]
    return minutes_ahead * 60 - tm.tm_sec


def next_fire_misses_cache(
    *,
    last_turn_age_s: int | None,
    seconds_to_next_fire: int | None,
    ttl_minutes: int,
) -> bool:
    """PURE. Will the NEXT heartbeat fire land on an EXPIRED prompt cache (and so pay the full
    cache-creation write on this session's whole context)?

    This is the card's trigger, expressed as the question that actually costs money. Asking
    instead whether the cache is *already* cold makes the lever unreachable whenever the cadence
    is faster than the TTL — which is the normal, healthy configuration (see the module
    docstring's measurement).

    Unknown inputs return False: an unknown schedule or an unmeasurable transcript is not
    evidence that a miss is coming, and the long-idle trigger still covers the abandoned case.
    """
    if last_turn_age_s is None or seconds_to_next_fire is None:
        return False
    if ttl_minutes <= 0:
        return False
    return (last_turn_age_s + seconds_to_next_fire) >= ttl_minutes * 60


def should_clear_on_resume(
    *,
    source: str,
    cache_expired: bool | None,
    context_tokens: int | None,
    min_context: int,
    in_cooldown: bool,
    already_fired_this_session: bool,
) -> ClearVerdict:
    """PURE. Shrink a session that was RESUMED onto a dead prompt cache, before its first turn.

    A SEPARATE predicate from `should_clear_externally`, not a relaxation of it, because the two
    protect different things and the difference is the whole safety argument.

    `should_clear_externally` vetoes on `user_present` and on an unknown `idle_seconds`: it
    hunts ABANDONED sessions, and `/clear` is unrecoverable, so it must never fire into a pane
    somebody is working in. On a resume BOTH of those vetoes are structurally true — the user
    just launched the thing, idle is zero — so reusing that gate here would refuse every time.
    That is exactly why this path was never finished.

    What makes clearing legitimate here is not that the vetoes were inconvenient, it is that
    the hazard they guard against does not exist yet: at SessionStart NO turn has run in this
    session. There is no in-flight work to destroy, no half-finished tool call, nothing the
    user is mid-sentence on. The transcript is on disk and the summary is composed from it.

    The cost of NOT firing is the reason the window matters: with a dead cache the very first
    turn re-reads the whole context at full price. On a ~700k session across a fleet of
    concurrent sessions that is the single most expensive event the janitor can prevent, and it
    is preventable only in the gap between "loaded" and "first turn" — a gap nothing else
    watches.

    The vetoes that DO survive, and why each one is load-bearing:

      * `source` — must be a genuine load-after-away (`RESUME_SOURCES`). `compact`/`clear` are
        re-entries into a just-shrunk session; acting on them loops forever.
      * `cache_expired is not True` — the ENTIRE point. `False` means the cache is warm and
        clearing would THROW AWAY a live cache to save nothing; `None` means agentlensPro could
        not answer, and an unknown must never authorize a destructive act (the same asymmetry
        `probe_cache_expired` documents).
      * `in_cooldown` — shared with every other clear lever, so whichever fired first stands
        the rest down.
      * `already_fired_this_session` — belt to the cooldown's braces, keyed on the session id:
        if SessionStart is ever delivered twice for one session, the second is a no-op.

    `context_tokens is None` deliberately does NOT veto, matching the correction made to
    `should_clear_externally`: an unmeasurable transcript must not silently disable the lever.
    A KNOWN-small context does veto — under `min_context` there is nothing worth reclaiming and
    a clear would cost the user their scrollback for no gain.
    """
    if source not in RESUME_SOURCES:
        return ClearVerdict(False, why=f"source={source or '?'} — not a load-after-away")
    if already_fired_this_session:
        return ClearVerdict(False, why="already fired for this session")
    if in_cooldown:
        return ClearVerdict(False, why="cooldown")
    if cache_expired is not True:
        return ClearVerdict(
            False,
            why="cache warm" if cache_expired is False else "cache state unknown — not clearing",
        )
    if context_tokens is not None and context_tokens < min_context:
        return ClearVerdict(
            False, why=f"context {context_tokens} < {min_context} — nothing worth reclaiming"
        )
    return ClearVerdict(
        True,
        TRIGGER_RESUMED_COLD,
        f"resumed on a dead cache (context={context_tokens if context_tokens is not None else '?'})"
        " — shrinking before the first turn pays full price for it",
    )


def cache_certainly_expired(project_dir: str | Path | None = None) -> bool | None:
    """The REACTIVE trigger's input: is this project's prompt cache ALREADY cold?

    Tri-state, straight through from `agentlens_probe.probe_cache_expired` — `None` means
    "no signal" (agentlensPro absent, disabled, or unable to answer) and MUST NOT be read as
    `False`. Impure and injectable-free by design: the decision itself stays pure, and this is
    the one I/O call feeding it.

    Why this exists next to `next_fire_misses_cache` rather than instead of it: the predictive
    path can only see expiries the SCHEDULE implies. The card names the ones it cannot — an API
    error that ended a turn, an AskUser prompt nobody answered, a network gap — where no fire
    happened at all and the cache died unobserved. Conversely this one cannot pre-empt the
    restart case, because by the time it says "expired" the miss is already unavoidable on the
    next turn. Each covers the other's blind spot; either alone is a partial feature.
    """
    command = os.environ.get(CACHE_EXPIRED_COMMAND_ENV, alp.DEFAULT_CACHE_EXPIRED_COMMAND)
    return alp.probe_cache_expired(command, project=str(project_dir) if project_dir else None)


@dataclass(frozen=True)
class ClearVerdict:
    """Whether to clear, which rule decided it, and a human-readable why.

    `why` is populated on BOTH branches on purpose. A refusal that cannot explain itself is how
    a silently-dead lever looks from the outside, and this project has shipped that twice.
    """

    fire: bool
    trigger: str = ""
    why: str = ""


def should_clear_externally(
    *,
    idle_seconds: int | None,
    last_turn_age_s: int | None,
    ttl_minutes: int,
    seconds_to_next_fire: int | None,
    context_tokens: int | None,
    min_context: int,
    min_idle_s: int,
    headroom_s: int,
    active_waiting: bool,
    in_cooldown: bool,
    cache_expired: bool | None = None,
) -> ClearVerdict:
    """PURE. The whole external-clear decision, with the deciding rule named.

    THE USER'S PRESENCE IS NOT AN INPUT HERE, AND MUST NOT BE RE-ADDED (owner, 2026-08-13:
    *"my presence must not even be mentioned"*). It used to be the first veto — `user_present`
    → refuse — which is what left this whole lever dead: the injection layer migrated to the
    three ratified rules on 2026-08-02 (`terminal_trigger.inject_until_sent`: inject only into
    an empty field, STOP the moment a key is typed, retry 8 s later, never cancel), but the
    DECISION layer never followed. So the gate kept answering "user-present" and the injector
    that would have politely deferred was never even asked. Presence is now handled in exactly
    one place — the injector — where it DELAYS by 8 s per keystroke and never refuses. A veto
    here would silently re-break that, because a refusal at this layer never reaches the
    injector at all.

    Vetoes, in the order they are cheapest to establish:

      * `in_cooldown`    — a clear already fired recently. Shared with the in-model lever via
        `cold_cache_compact`'s `idle-clear-fired.ts`, so whichever path fires first stands the
        other down. That sharing IS the coexistence contract while both exist.
      * `active_waiting` — a resume or a background agent is in flight. NOT about the user:
        this is machine state, and firing into it would type over a chain already running.
      * `idle_seconds is None` — an UNKNOWN idle age must never authorize a destructive action.
        Note the deliberate asymmetry with `context_tokens`, below.
      * headroom — a fire is imminent, so the chain would be typing into a session mid-turn.
        Wait for the next gap; nothing is lost, the gap recurs every cadence period. An UNKNOWN
        headroom (a cron shape we cannot read) does NOT veto — that would make an unreadable
        cron silently disable the lever.

    Then the three triggers, OR'd (see the module docstring for why none subsumes the others).
    `cache_expired` is the agentlensPro MEASUREMENT and is checked first, ahead of the
    prediction that models the same cost — when both agree, attributing the fire to the
    measurement is what makes the log line worth reading. Its `None` is "no signal", never
    `False`: an absent CLI must leave the other two triggers exactly as they were.

    `context_tokens is None` is NOT a veto, and that is a correction, not an oversight: the
    unknown-context veto is exactly what silently disabled `should_clear_when_long_idle` for
    every session whose transcript could not be measured (owner directive 2026-08-04). An
    unmeasurable context skips the size clause and the idle/miss terms decide alone.
    """
    if in_cooldown:
        return ClearVerdict(False, why="cooldown")
    if active_waiting:
        return ClearVerdict(False, why="active-waiting")
    if idle_seconds is None:
        return ClearVerdict(False, why="idle-unknown")
    if seconds_to_next_fire is not None and seconds_to_next_fire < headroom_s:
        return ClearVerdict(
            False, why=f"no-headroom ({seconds_to_next_fire}s < {headroom_s}s to next fire)"
        )
    if context_tokens is not None and context_tokens < min_context:
        return ClearVerdict(
            False, why=f"context {context_tokens} < {min_context} — nothing worth reclaiming"
        )

    if cache_expired is True:
        return ClearVerdict(
            True,
            TRIGGER_CACHE_CERTAIN_EXPIRED,
            "agentlensPro reports this session's prompt cache is ALREADY expired — the next "
            "turn pays a full cache-creation write on the whole context",
        )
    if next_fire_misses_cache(
        last_turn_age_s=last_turn_age_s,
        seconds_to_next_fire=seconds_to_next_fire,
        ttl_minutes=ttl_minutes,
    ):
        return ClearVerdict(
            True,
            TRIGGER_NEXT_FIRE_MISSES,
            f"next fire lands {last_turn_age_s}+{seconds_to_next_fire}s after the last turn, "
            f"past the {ttl_minutes}min cache TTL — it would pay a full miss",
        )
    if idle_seconds >= min_idle_s:
        return ClearVerdict(
            True,
            TRIGGER_LONG_IDLE,
            f"nothing but heartbeats for {idle_seconds}s (>= {min_idle_s}s)",
        )
    return ClearVerdict(
        False, why=f"idle {idle_seconds}s < {min_idle_s}s and the next fire is still warm"
    )


def terminal_from_record(record: Mapping[str, str]) -> dict[str, str]:
    """PURE adapter: the FLEET-shaped pane identity a session records at start →
    the `terminal_trigger` shape (`kind` + channel key).

    Two dict shapes for one concept exist in this codebase and they are NOT interchangeable:
    `session_liveness.capture_terminal_identity` / `fleet_restart.recorded_terminal` emit
    `{iterm_session_id, tmux_pane}`, while `terminal_trigger` and `clear_trigger._this_terminal`
    consume `{kind, pane|session_id}`. Handing the former straight to the latter yields
    `kind=""`, which every builder treats as "unsupported channel" — a silent no-op.

    tmux is preferred over iTerm for the same reason `_this_terminal()` prefers it: its pane can
    be read back cheaply, which is what lets the chain VERIFY a command before submitting it.

    `ITERM_SESSION_ID` is recorded verbatim and is `<tty>:<UUID>`; the UUID must be split off
    here or `clear_trigger._UUID_RE` rejects the whole string and refuses to build the osascript.
    """
    pane = (record.get("tmux_pane") or "").strip()
    if pane:
        return {"kind": "tmux", "pane": pane}
    iterm = (record.get("iterm_session_id") or "").strip()
    if iterm:
        return {"kind": "iterm", "session_id": iterm.split(":")[-1].strip()}
    return {"kind": "unknown"}


# --- best-effort readers (never raise) --------------------------------------


def read_ttl_minutes(state_dir: Path) -> int:
    """The probed prompt-cache TTL the dispatcher cached, or `DEFAULT_TTL_MINUTES`.

    `ttl-regime.json` was written by the dynamic-cadence phase's TTL probe, retired by
    TRDD-BRHJHWW0 — nothing writes this file any more, so this reader now always falls
    back to `DEFAULT_TTL_MINUTES`. Left in place (rather than deleted) because a future
    probe could still populate the same file, and a watcher that runs outside the model
    has no business spending a subprocess on a probe of its own.
    """
    import json  # noqa: PLC0415 -- only this reader needs it

    try:
        data = json.loads((state_dir / _TTL_REGIME_FILE).read_text(encoding="utf-8"))
        minutes = int(data["minutes"])
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError):
        return DEFAULT_TTL_MINUTES
    return minutes if minutes > 0 else DEFAULT_TTL_MINUTES


# --- the zero-token handoff (template fallback) ------------------------------


@dataclass
class HandoffInputs:
    """Everything the template composer needs, already gathered from disk.

    A dataclass rather than a pile of keyword args because the llm-ext composer consumes the
    same inputs — it is handed these PATHS (never their contents; `use-llm-externalizer.md`),
    and this template is what runs when llm-ext is absent or fails.
    """

    cards: Sequence[tuple[str, str, str]] = field(default_factory=list)  # (id, column, title)
    commits: Sequence[tuple[str, str]] = field(default_factory=list)  # (sha, subject)
    findings: Sequence[str] = field(default_factory=list)
    memory_dir: str = ""
    trigger: str = ""
    idle_seconds: int | None = None
    context_tokens: int | None = None


def compose_template_handoff(inputs: HandoffInputs, *, now_iso: str, max_bytes: int = 4096) -> str:
    """PURE. Build a link-only handoff from on-disk facts, with ZERO model tokens.

    It must satisfy `clear_trigger.check_handoff_concise` BY CONSTRUCTION, because the thing it
    is handed to is unrecoverable and nobody reviews it first:
      * under `max_bytes` — enforced by trimming the tail of each list (see below), not hoped for;
      * carries a reference — the `memgrep recall` line is unconditional, so even a handoff with
        no cards, no commits and no findings still points at the payload store;
      * no fenced blocks at all — so the `inlined-block` check cannot trip.

    Trimming drops list ITEMS from the tail rather than truncating the text mid-line: a handoff
    cut mid-sentence can leave a half-written TRDD id, which reads as a real pointer and resolves
    to nothing. Losing a whole low-priority line is recoverable; a corrupted pointer is not.
    """
    cards = list(inputs.cards)
    commits = list(inputs.commits)
    findings = list(inputs.findings)

    def render(n_cards: int, n_commits: int, n_findings: int) -> str:
        idle_h = "unknown" if inputs.idle_seconds is None else f"~{inputs.idle_seconds // 3600}h"
        ctx = "unknown" if inputs.context_tokens is None else f"~{inputs.context_tokens // 1000}k"
        out = [
            f"# Handoff — {now_iso} (auto-composed, no model turn — TRDD-PXP08ZQC)",
            "",
            f"Written by the janitor's EXTERNAL watcher, not by the model: trigger "
            f"`{inputs.trigger}`, idle {idle_h}, context {ctx}. Link-only by construction — "
            "every pointer below is resolved on demand, nothing is inlined.",
            "",
            "## NEXT ACTION (one step, runnable)",
            "",
            "Read the `## STATE` block of the first in-flight card below, then continue its "
            "NEXT ACTION. A card's STATE block is authoritative; this handoff is only an index.",
        ]
        if cards[:n_cards]:
            out += ["", "## In-flight cards (open work)", ""]
            out += [f"- TRDD-{cid} (`{col}`) — {title}" for cid, col, title in cards[:n_cards]]
        if commits[:n_commits]:
            out += ["", "## Recent commits (the WHY lives in the messages — `git show <sha>`)", ""]
            out += [f"- {sha} {subject}" for sha, subject in commits[:n_commits]]
        if findings[:n_findings]:
            out += ["", "## Open findings", ""]
            out += [f"- {f}" for f in findings[:n_findings]]
        recall_dir = inputs.memory_dir or ".claude/project/memory"
        out += [
            "",
            "## Recall",
            "",
            f'Deep knowledge is in the wiki, not here: `memgrep recall "<symptom>" {recall_dir}`.',
            "",
        ]
        return "\n".join(out)

    n_cards, n_commits, n_findings = len(cards), len(commits), len(findings)
    text = render(n_cards, n_commits, n_findings)
    # Drop the least load-bearing section first (findings are re-derivable from the ledger every
    # session; commits from git; the CARDS are the only thing that says what was being worked on).
    while len(text.encode("utf-8")) > max_bytes and (n_findings or n_commits or n_cards > 1):
        if n_findings:
            n_findings -= 1
        elif n_commits:
            n_commits -= 1
        else:
            n_cards -= 1
        text = render(n_cards, n_commits, n_findings)
    return text
