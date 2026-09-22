"""llm-ext session summarization — the MANUAL lane's own copy (TRDD-RAEGS1D5 card 3 C2).

MANUAL-ONLY. The AUTOMATIC SessionStart lane (`scripts/summarize_previous_session.py`) was
rewired onto `jev_compact.py compact` in card 3 C1 and no longer calls any of this. What is left
calling it is exactly ONE production caller: `scripts/compose_agent_handoff.py`, the script behind
the `/janitor-write-handoff` skill — the owner's manual "summarize THIS session's transcript on
demand" tool, which is explicitly allowed to keep using llm-ext (see that skill's own SKILL.md).

WHY A SEPARATE MODULE, NOT A DELETION. The C2 brief calls for removing `resolve_llm_ext`,
`attempt_llm_ext_summary` and `summarize_with_retry` from `scripts/lib/external_clear.py` — that
automatic-lane module has no remaining reason to import `subprocess`-level llm-ext plumbing once
`compose_handoff` stopped needing it. But the manual tool's own dependency on this retry/classify
machinery did not go away with the automatic lane's rewiring, so the code moved here instead of
being deleted outright — "one version of the code" for the manual lane, not a second copy kept
alive beside the automatic one.

Fleet-lease serialization (`acquire_fleet_lease`/`release_fleet_lease`/`await_fleet_lease`) and
`LLM_EXT_TIMEOUT_S` (the invariant `DEFAULT_FLEET_LEASE_TTL_S` is derived FROM) stay in
`external_clear.py` — the brief keeps them there for a future automatic-lane consumer (card 3 C3
renames them), so this module imports them rather than re-implementing its own copy of the
machine-wide concurrency cap.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import external_clear as ec  # noqa: E402 -- fleet-lease serialization stays there (card 3 C3)


def _version_key(name: str) -> tuple[int, ...]:
    """A sortable numeric tuple for a version directory name; a non-numeric part sorts as 0.

    Never raises: an odd directory name costs one candidate, not the whole lookup.
    """
    out: list[int] = []
    for part in name.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def resolve_llm_ext() -> str:
    """Absolute path to the llm-ext CLI, or "" when it genuinely is not installed.

    `shutil.which` ALONE IS NOT ENOUGH, and that is MEASURED, not theoretical (TRDD-CEWVQ8DG). The
    CLI ships inside ANOTHER plugin and lives at
    `~/.claude/plugins/cache/<marketplace>/llm-externalizer/<version>/bin/llm-ext` — a directory an
    interactive shell carries on PATH because the user's profile put it there, and a hook-spawned
    detached child does not. So every cold-resume handoff on this machine degraded to the template
    (`summary: permanent — llm-ext is not on PATH; not retrying`) while the binary sat exactly
    where this function now looks. Resolving by the install's OWN documented layout — the same
    `cache/<marketplace>/<plugin>/<version>/…` convention — removes the dependency on whose
    environment happens to be inherited.

    PATH still wins when it answers, so an operator who put a specific build there keeps control.

    Versions are ordered by PARSED NUMERIC TUPLE, never lexicographically: as strings "9.0.0"
    sorts ABOVE "13.5.1", which would pin the oldest install forever and silently strand every
    later fix. Ties break on the path so the choice is deterministic across runs.
    """
    found = shutil.which("llm-ext")
    if found:
        return found
    try:
        cache = Path.home() / ".claude" / "plugins" / "cache"
        candidates = [
            (_version_key(c.parent.parent.name), str(c))
            for c in cache.glob("*/llm-externalizer/*/bin/llm-ext")
            if c.is_file()
        ]
    except OSError:  # an unreadable home must degrade to "absent", never raise into a clear
        return ""
    return max(candidates)[1] if candidates else ""


def _data_dir_fingerprint(data_dir: str) -> float:
    """llm-ext's data dir mtime, or -1.0 if it cannot be read.

    See `_NO_PROGRESS_TIMEOUT_GIVEUP` for why this is the progress signal: llm-ext's checkpoint
    write is atomic tmp+rename, and a rename bumps the CONTAINING directory's mtime — so this
    changes exactly when a chunk completes, without this codebase parsing or even naming the
    checkpoint file. -1.0 (never equal to a real mtime) means "unknown", which the caller must
    treat as "no evidence either way", not as "no progress".
    """
    try:
        return Path(data_dir).stat().st_mtime
    except OSError:
        return -1.0


def llm_ext_progress_fn() -> Callable[[], float] | None:
    """The real progress signal for `summarize_with_retry`'s `progress_fn`, or None when llm-ext
    cannot be resolved (the retry loop then simply runs without the gate — never guesses).

    Deliberately NOT the retry loop's default: a default that auto-resolves the real binary
    would make `summarize_with_retry`'s tests depend on whether llm-ext happens to be installed
    on the machine running them. Production wiring calls this explicitly; tests inject a fake
    `progress_fn` instead.
    """
    if not resolve_llm_ext():
        return None
    data_dir = llm_ext_state_dir()
    if not data_dir:
        return None
    return lambda: _data_dir_fingerprint(data_dir)


# WHERE llm-ext's per-chunk progress is actually observable.
#
# `LLM_EXT_CONFIG_DIR` else `~/.llm-externalizer` is exactly the resolution llm-ext's own
# `getConfigDir()` performs, and the maintainer confirmed it is PUBLIC and stable (documented in
# their README + setup docs) — so this asks the same question the tool asks rather than assuming
# a path.
#
# BUT THE ROOT IS THE WRONG DIRECTORY TO WATCH, and that correction came from the llm-externalizer
# maintainer after this code first pointed at it. Checkpoints land in the
# `session-summary-checkpoints/` SUBDIR (`saveCheckpoint()`: mkdir, write `<name>.tmp`, rename —
# once per completed chunk, tmp and target in that same dir). Only that subdir's mtime advances
# per chunk; the ROOT's moves solely when a top-level entry is added or removed.
_LLM_EXT_STATE_ENV = "LLM_EXT_CONFIG_DIR"
_LLM_EXT_STATE_DEFAULT = "~/.llm-externalizer"
_LLM_EXT_CHECKPOINT_SUBDIR = "session-summary-checkpoints"


def llm_ext_state_dir() -> str:
    """The directory whose mtime advances once per COMPLETED summarize chunk, or "".

    Returns the checkpoint subdir, never the config root — see the block above for why the root
    is a dead signal. "" when it does not exist yet (llm-ext has never checkpointed here), which
    the caller reads as "no gate", never as "no progress".
    """
    raw = os.environ.get(_LLM_EXT_STATE_ENV, "").strip() or _LLM_EXT_STATE_DEFAULT
    path = Path(raw).expanduser() / _LLM_EXT_CHECKPOINT_SUBDIR
    return str(path) if path.is_dir() else ""


def _default_runner(
    argv: list[str],
    *,
    capture_output: bool = True,
    text: bool = True,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> Any:
    """The real subprocess call, wrapped so `subprocess.run` is only ever CALLED, never passed.

    CPV's skillaudit flags the subprocess entry point referenced AS A VALUE — bound to a local
    via `or`, or used as a signature default — as dynamic command dispatch (SHELL_EXEC), which
    blocks the publish at MINOR. A direct call is not flagged. This call is load-bearing — it
    really does exec the llm-ext CLI — so the honest fix is to stop LOOKING like indirection
    rather than to annotate it.
    """
    return subprocess.run(
        argv,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        env=env,
        check=check,
    )


_REFUSAL_OPENERS = (
    "i'm not going to",
    "i am not going to",
    "i won't",
    "i will not",
    "i'm declining",
    "i am declining",
    "i can't help",
    "i cannot help",
    "i'm unable to",
    "i am unable to",
)


def _looks_like_refusal(text: str) -> bool:
    """True when the model DECLINED the compaction instead of performing it.

    Load-bearing, because the summary is the sole artifact that justifies destroying a live
    context: on 2026-08-18 the model answered the compaction prompt with *"I'm not going to
    produce this compaction as specified, because the transcript contains a prompt injection"*
    plus a lecture about this plugin. Exit 0, non-empty stdout — so the only validation there
    was (`out or None`) called it a summary, it was written into the handoff as the session's
    own state, and the session was cleared on the strength of it. A zero exit says the CLI ran;
    it says nothing about whether the text is a summary.

    Matched ONLY at the START of the first non-empty line (plus the line after it when that
    first line is a markdown heading). Anchoring is the whole design: a legitimate summary OF
    THAT INCIDENT opens by quoting the refusal, so a keyword found anywhere throws away a good
    summary for naming a bad one. Blockquote markers are deliberately NOT stripped for the same
    reason: a leading `>` is evidence of quoting, which is the opposite of refusing.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for candidate in lines[:2] if lines[:1] and lines[0].lstrip().startswith("#") else lines[:1]:
        # Curly apostrophes are what models actually emit; without this the guard misses
        # "I’m not going to" entirely, which is the exact phrasing of the incident above.
        head = candidate.lstrip("#*_ \t").lower().replace("’", "'")
        if head.startswith(_REFUSAL_OPENERS):
            return True
    return False


def _excerpt(text: str, *, head: int = 300, tail: int = 400) -> str:
    """A bounded, single-line window on a blob — BOTH ENDS, never just one.

    Programs print the DIAGNOSIS first and the raw underlying error last, so a head-only
    excerpt keeps exactly the wrong half of a stack trace and a tail-only one keeps the
    wrong half of a refusal. Newlines are escaped because this lands in a line-oriented log
    that is read with grep.

    tail=400 is a CONTRACT with llm-externalizer's driver: its `(nonconforming)` stderr
    message ends with a 400-char excerpt of the model's own words, so a shorter tail would
    clip the one part of the message that answers "what did the model actually say".
    """
    blob = " ".join((text or "").split())
    if len(blob) <= head + tail:
        return blob
    return f"{blob[:head]} …[{len(blob) - head - tail} chars elided]… {blob[-tail:]}"


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

# The distinguishing signal for a single chunk provably stuck past `ec.LLM_EXT_TIMEOUT_S`: whether
# llm-ext's OWN checkpoint state changed between two consecutive timeouts (TRDD-YOZ9TS3W). 2, not
# `_UNKNOWN_REPEAT_GIVEUP`'s 3: a stuck-timeout retry costs a full `ec.LLM_EXT_TIMEOUT_S` (600s)
# AND a fleet lease, so confirming "stuck" a third time would spend the entire deadline learning
# what two attempts already showed.
_NO_PROGRESS_TIMEOUT_GIVEUP = 2


@dataclass(frozen=True)
class SummaryAttempt:
    """One llm-ext invocation: what it produced, and whether trying again could help."""

    text: str | None
    outcome: str
    detail: str = ""
    # What the process ACTUALLY produced, for the post-mortem. Separate from `detail` on
    # purpose: `detail` is the retry key and must stay CONSTANT across attempts (the UNKNOWN
    # bound counts identical details), while evidence is free-form and differs every time.
    evidence: str = ""


def classify_llm_ext_failure(*, returncode: int, stderr: str, timed_out: bool) -> str:
    """PURE: is this failure worth retrying? A timeout always is — it is the shape a stalled
    generation and a dead network both take."""
    if timed_out:
        return OUTCOME_TRANSIENT
    blob = (stderr or "").lower()
    if "(nonconforming)" in blob:
        # llm-ext >=13.5.4 contract: non-zero exit + this literal token means every candidate
        # model produced non-schema output (usually a refusal). This check must come FIRST, or
        # the marker scan below would call it TRANSIENT and burn the whole retry deadline on
        # generations that keep refusing.
        return OUTCOME_UNKNOWN
    if any(m in blob for m in _TRANSIENT_MARKERS):
        return OUTCOME_TRANSIENT
    return OUTCOME_UNKNOWN


def failure_signature(*, returncode: int, stderr: str) -> str:
    """A stable identity for 'the same failure again' — exit code + the first stderr line.

    First LINE only, because a wrapper that stamps a timestamp or a request id into later lines
    would otherwise make every identical failure look novel and defeat the give-up entirely.
    """
    if "(nonconforming)" in (stderr or ""):
        # Constant on purpose: the driver interpolates the model ids it tried into this message,
        # so a first-line signature would differ on every attempt and defeat the UNKNOWN
        # give-up — the same bound-loss the stdout refusal's constant detail guards against.
        return f"{returncode}|(nonconforming)"
    first = ""
    for line in (stderr or "").splitlines():
        if line.strip():
            first = line.strip()[:200]
            break
    return f"{returncode}|{first}"


def attempt_llm_ext_summary(
    transcript: str,
    *,
    timeout_s: int = ec.LLM_EXT_TIMEOUT_S,
    runner: Any = _default_runner,  # see _default_runner — never pass subprocess.run as a value
) -> SummaryAttempt:
    """One classified llm-ext summarize attempt. NEVER raises.

    Everything the retry loop needs to decide "again?" lives here, because collapsing every
    failure to None makes an unplugged network indistinguishable from an uninstalled binary,
    and those want opposite responses. Default `timeout_s` is `external_clear.LLM_EXT_TIMEOUT_S`
    — the SAME per-attempt ceiling the fleet-lease TTL there was derived from.
    """
    binary = resolve_llm_ext()
    if not binary:
        # "not installed", NOT "not on PATH": PATH is no longer the criterion, and the old wording
        # is the exact string in the incident logs — keeping it would make a fixed host
        # indistinguishable from a broken one in the next post-mortem.
        return SummaryAttempt(None, OUTCOME_PERMANENT, "llm-ext is not installed")
    if not transcript or not Path(transcript).is_file():
        return SummaryAttempt(None, OUTCOME_PERMANENT, "no readable transcript")
    # DO NOT derive llm-ext's data dir here, and DO NOT pass ours through. The launcher
    # self-resolves it since 13.5.x, and the launcher deriving from its OWN resolved path is
    # authoritative where every caller can only guess. The env var must be REMOVED, not merely
    # left alone: in a janitor hook/daemon child CLAUDE_PLUGIN_DATA names the JANITOR's data dir,
    # and the env var WINS over the launcher's derivation, so inheriting it would self-install
    # llm-ext's native module into the wrong plugin's store.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
    try:
        size = Path(transcript).stat().st_size
    except OSError:
        size = -1
    started = time.monotonic()
    try:
        proc = runner(
            [binary, "session-summary", "--stdout", "--transcript", transcript],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SummaryAttempt(
            None, OUTCOME_TRANSIENT, f"timed out after {timeout_s}s",
            evidence=f"transcript={transcript} bytes={size} elapsed={time.monotonic() - started:.1f}s",
        )
    except Exception as exc:  # noqa: BLE001 - a handoff must survive ANY subprocess failure
        return SummaryAttempt(
            None, OUTCOME_TRANSIENT, f"spawn failed: {exc!r}",
            evidence=f"transcript={transcript} bytes={size}",
        )
    rc = int(getattr(proc, "returncode", 1) or 0)
    err = getattr(proc, "stderr", "") or ""
    out_raw = getattr(proc, "stdout", "") or ""
    # The forensic record of THIS invocation — both ends of both streams, so "the compaction
    # failed" is answerable without a repro. stderr gets a WIDER tail (~20 lines) than the
    # default excerpt: llm-ext's stdout is the summary alone by contract, so every diagnostic
    # for a failed/empty attempt lives on stderr.
    evidence = (
        f"transcript={transcript} bytes={size} rc={rc} "
        f"elapsed={time.monotonic() - started:.1f}s "
        f"stdout[{len(out_raw)}]={_excerpt(out_raw)!r} "
        f"stderr[{len(err)}]={_excerpt(err, tail=2000)!r}"
    )
    if rc != 0:
        return SummaryAttempt(None, classify_llm_ext_failure(
            returncode=rc, stderr=err, timed_out=False
        ), failure_signature(returncode=rc, stderr=err), evidence=evidence)
    out = out_raw.strip()
    if not out:
        # Exit 0 with nothing on stdout: the CLI answered without producing a summary. Retryable
        # — an empty generation is a normal free-tier outcome under load, not a broken install.
        return SummaryAttempt(
            None, OUTCOME_TRANSIENT, "empty summary on a zero exit", evidence=evidence
        )
    if _looks_like_refusal(out):
        # UNKNOWN, and the detail is a CONSTANT on purpose. A refusal is probabilistic, so a
        # retry can legitimately succeed (PERMANENT would give up too early) — but its trigger
        # is the transcript's content, which does not change, so TRANSIENT would burn the whole
        # deadline on paid generations that all refuse.
        return SummaryAttempt(
            None, OUTCOME_UNKNOWN, "refusal-shaped output on a zero exit", evidence=evidence
        )
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
    progress_fn: Callable[[], float] | None = None,
    lease_wait_budget_s: float | None = None,
) -> SummaryAttempt:
    """Keep trying to summarize until it works, the deadline passes, or trying is pointless.

    THE CONTRACT THE OWNER ASKED FOR — *"the compacting must succeed no matter what"* — is met by
    the CALLER, not by this function, and the distinction matters. What must never fail is the
    CLEAR; this only decides how good the handoff that precedes it is. So the loop is bounded by
    `deadline` and returns a failed attempt rather than blocking forever.

    Four stopping rules, in order:
      * OK — done.
      * PERMANENT — no binary / no data dir / no transcript. Attempt 100 fails exactly like
        attempt 1, so stop at once rather than sleeping through the whole budget.
      * UNKNOWN repeating identically `_UNKNOWN_REPEAT_GIVEUP` times — a broken invocation
        reproducing byte-for-byte. Anything that keeps CHANGING keeps being retried.
      * TIMEOUT repeating `_NO_PROGRESS_TIMEOUT_GIVEUP` times with `progress_fn()` unchanged
        between them — a chunk provably stuck past `ec.LLM_EXT_TIMEOUT_S` (TRDD-YOZ9TS3W). Only
        engaged when `progress_fn` is supplied; production wiring passes `llm_ext_progress_fn()`.
    TRANSIENT otherwise never stops on its own: it retries until the deadline, which is what
    "disconnected for hours" needs.

    Every attempt — including retries — holds a fleet lease from `external_clear.py` (the machine-
    wide serialization stays there; card 3 C3 renames it) while it runs, so at most
    `max_concurrent` llm-ext calls exist machine-wide and N sessions recovering from one outage
    cannot re-form the herd on a shared backoff schedule.
    """
    run_attempt = attempt or attempt_llm_ext_summary
    cap = ec.fleet_max_concurrent() if max_concurrent is None else max_concurrent
    ttl = ec.fleet_lease_ttl_s() if lease_ttl_s is None else lease_ttl_s
    say: Callable[[str], Any] = log if log is not None else (lambda _msg: None)
    seen: dict[str, int] = {}
    last = SummaryAttempt(None, OUTCOME_TRANSIENT, "no attempt was made before the deadline")
    # `progress_fn` is opt-in (see its docstring). `stuck_timeouts` counts CONSECUTIVE timeouts
    # observed with an unchanged fingerprint; any progress (or any non-timeout outcome) resets
    # it to 0.
    last_fingerprint: float | None = progress_fn() if progress_fn is not None else None
    stuck_timeouts = 0

    for i in range(len(_BACKOFF_S) * 64):  # a bound, not a policy — `deadline` is the policy
        now = float(now_fn())
        if now >= deadline:
            say(f"summary: deadline reached after {i} attempt(s) — {last.detail}")
            return SummaryAttempt(None, last.outcome, f"deadline: {last.detail}")

        # `lease_wait_budget_s` caps how long ONE wait for a lane slot may poll (a caller running
        # inside a blocking human-facing hook would pass a small budget here). A lane that stays
        # full past the budget is treated as a verdict: decline now, let the caller proceed.
        lease_deadline = (
            deadline if lease_wait_budget_s is None
            else min(deadline, now + float(lease_wait_budget_s))
        )
        lease = ec.await_fleet_lease(
            deadline=lease_deadline, max_concurrent=cap, ttl_s=ttl, lane_dir=lane_dir,
            now_fn=now_fn, sleeper=sleeper,
        )
        if lease is None:
            if lease_deadline < deadline:
                say(
                    f"summary: fleet lane full past the {lease_wait_budget_s:.0f}s lease budget "
                    "— declining fast"
                )
                return SummaryAttempt(None, last.outcome, f"lane full past budget: {last.detail}")
            say("summary: fleet lane full through the deadline — degrading to the template")
            return SummaryAttempt(None, last.outcome, f"lane full: {last.detail}")
        # try/finally, not a bare call: an exception between here and the release would strand
        # the lease for its full TTL, shrinking the fleet's capacity by one for five minutes.
        try:
            last = run_attempt(transcript)
        finally:
            ec.release_fleet_lease(lease, lane_dir=lane_dir)
        # Log the forensics of every attempt that did NOT succeed, at the moment it happens.
        if last.outcome != OUTCOME_OK and last.evidence:
            say(f"attempt {i + 1} [{last.outcome}] {last.detail} | {last.evidence}")
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

        # The progress-observed gate (option B, TRDD-YOZ9TS3W) — only for TIMEOUT-classified
        # TRANSIENT outcomes, and only when `progress_fn` was supplied.
        if progress_fn is not None:
            is_timeout = (
                last.outcome == OUTCOME_TRANSIENT and last.detail.startswith("timed out after")
            )
            if is_timeout:
                new_fingerprint = progress_fn()
                if (
                    last_fingerprint is not None
                    and new_fingerprint == last_fingerprint
                    and new_fingerprint != -1.0
                ):
                    stuck_timeouts += 1
                    if stuck_timeouts >= _NO_PROGRESS_TIMEOUT_GIVEUP:
                        say(
                            f"summary: {stuck_timeouts} timeouts with zero checkpoint progress — "
                            "giving up rather than burning the deadline on a chunk that cannot "
                            "finish"
                        )
                        return SummaryAttempt(None, OUTCOME_PERMANENT, f"no progress: {last.detail}")
                else:
                    stuck_timeouts = 0
                last_fingerprint = new_fingerprint
            else:
                stuck_timeouts = 0
                last_fingerprint = progress_fn()

        base = float(_BACKOFF_S[min(i, len(_BACKOFF_S) - 1)])
        # Jitter so a fleet that failed together does not retry together.
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
