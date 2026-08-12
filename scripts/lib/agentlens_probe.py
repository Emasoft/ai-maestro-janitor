"""Shared agentlensPro probe — config-gated, bounded, fail-open (TRDD-WUUR2DFX).

agentlensPro (the `agentlenspro` CLI) is a machine-local, OPTIONAL observability
tool. The janitor NEVER hard-depends on it: every probe here is

  1. config-gated  — an empty command string disables the probe entirely,
  2. bounded       — a short subprocess timeout (default 5 s), never on a hot path,
  3. fail-open     — a missing binary / non-zero exit / timeout / unparseable
                     output all return None, and the caller falls back to its own
                     native estimate SILENTLY.

Same contract as the #78 heartbeat-cost command (the #83 TTL-regime probe this once
mirrored, ``heartbeat_cadence.probe_account_status``, was retired by TRDD-BRHJHWW0) —
this module is deliberately the same shape so there is ONE integration pattern.

WHY the parsers only trust a NARROW slice of the payload (verified live 2026-07-12,
and the reason this is "enrich", not "switch"): agentlensPro observes token spend
via OTEL telemetry. It does NOT read Anthropic's ``/api/oauth/usage`` endpoint, so
its window budget / %-consumed / time-to-exhaustion are NULL unless a capacity is
manually configured (``AGENTLENS_WINDOW_5H_TOKENS`` …) or auto-calibrated from a
real rate-limit hit. On an unconfigured machine ``get_burn_status.window`` is
``{"capacitySource": "none"}``. So the janitor's rotator read of ``/api/oauth/usage``
stays AUTHORITATIVE for the window utilization%, and this module takes from
agentlensPro only what it IS authoritative for:

  - ``get_burn_status``   → realtime machine-wide burn RATE: ``global.costPerHour``,
    per-account ``fiveMinTokensPerMin``, and ``topSessions`` (session + workspace).
  - ``investigate_burn``  → after-the-fact CULPRIT/CAUSE attribution: a ranked
    ``findings`` list (cause + share-of-window + confidence) and an ``attribution``
    list (workspace / model / requests). This is the EXPENSIVE probe — a caller
    invokes it ONLY after it has already decided to alarm, never speculatively.

Every non-probe function here is pure and unit-tested; the one impure helper
(``probe_json``) is a thin, injectable subprocess wrapper so the parsers can be
tested against captured fixtures without a live server.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass

# Default commands. Each is overridable via its CLAUDE_PLUGIN_OPTION_* env var; an
# empty value disables that probe (pure fail-open to the native estimate). The bare
# `agentlenspro` binary is resolved from PATH by the OS — the janitor never assumes
# a path, mirroring #83's `heartbeat_account_status_command`.
DEFAULT_BURN_STATUS_COMMAND = "agentlenspro get_burn_status"
DEFAULT_INVESTIGATE_BURN_COMMAND = "agentlenspro investigate_burn"
DEFAULT_CACHE_EXPIRED_COMMAND = "agentlenspro cache-expired"

_TIMEOUT_S = 5.0

# DELIBERATELY NOT `_TIMEOUT_S`. Measured three consecutive `cache-expired` calls on one warm
# host: 0.15 s, 11.5 s, 19.7 s — the latency is wildly variable and the tail is nowhere near the
# 5 s the burn probes use. Under 5 s this probe returned None on 2 of 3 runs, which fails OPEN and
# so looks exactly like "agentlensPro is not installed": the trigger would have shipped dead, the
# defect class this whole card exists to remove. The asymmetry decides the number — too short
# silently disables the feature, too long costs wall-clock in a DETACHED one-shot watcher that
# nobody is waiting on. So: generous, and separate, so tuning the burn probes cannot re-break it.
_CACHE_EXPIRED_TIMEOUT_S = 30.0


def probe_cache_expired(
    command: str,
    *,
    project: str | None = None,
    timeout: float = _CACHE_EXPIRED_TIMEOUT_S,
    runner: object = None,
) -> bool | None:
    """TRI-STATE: has this project's conversation outlived its prompt-cache TTL?

    ``True`` = certainly expired, ``False`` = certainly fresh, ``None`` = unknown (the CLI
    is absent, the probe failed, or it explicitly could not answer). Same fail-open contract
    as ``probe_json``; the caller must treat ``None`` as "no signal", never as ``False``.

    Unlike the janitor's own ``next_fire_misses_cache``, this is a MEASUREMENT rather than a
    prediction: agentlensPro knows the session's real last-LLM-call time and the real TTL
    regime, where the native path infers the TTL from a probed file and defaults to the short
    5-minute side when it cannot.

    ⚠ THE EXIT CODE DOES NOT MEAN WHAT ``--help`` SAYS IT MEANS IN THIS FORM. The documented
    "exit 0 = EXPIRED, 1 = fresh" applies to ``-q`` ONLY. Measured on 12.x, the verbose form
    exits **0 while printing ``false``** — 0 means "I answered", and the answer is the word on
    stdout. Coding ``rc == 0 ⇒ expired`` here would report a cache miss on every healthy
    session, and the consumer of this signal fires an unrecoverable ``/clear``. So the ANSWER
    is the stdout word and the exit code is only a did-it-answer gate. Cannot-answer is exit 2
    with stdout EMPTY — the CLI never prints ``false`` for a question it could not resolve,
    which is what makes the empty case safe to read as ``None``.
    """
    command = (command or "").strip()
    if not command:
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if project:
        argv += ["--project", project]
    run = runner if callable(runner) else subprocess.run
    try:
        proc = run(  # noqa: S603 - argv from config, split with shlex, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    word = (getattr(proc, "stdout", "") or "").strip().lower()
    if word == "true":
        return True
    if word == "false":
        return False
    return None


def probe_json(command: str, *, timeout: float = _TIMEOUT_S) -> dict | None:
    """Run ``command`` and return its parsed-JSON stdout as a dict, else None.

    Fail-open by construction — the janitor must survive an absent/broken CLI:
    an empty command, an un-splittable command, a missing binary, a non-zero
    exit, a timeout, or non-object / unparseable output all return None. A JSON
    array (or any non-dict top level) also returns None: every agentlensPro tool
    this module consumes returns an object, so a non-dict is an unexpected shape
    to be treated as "probe failed".
    """
    command = (command or "").strip()
    if not command:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - argv from config, split with shlex, no shell
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class BurnStatus:
    """The slice of ``get_burn_status`` the janitor trusts (verified authoritative).

    ``cost_per_hour`` — machine-wide $/h burn (``global.costPerHour``); None when
    absent. ``active_sessions`` — live session count. ``top_workspace`` /
    ``top_session_id`` — the hottest session (``topSessions[0]``), for naming a
    culprit. Deliberately NO window %/budget field: that is null without a
    configured capacity, so the rotator's ``/api/oauth/usage`` read owns it.
    """

    cost_per_hour: float | None
    active_sessions: int | None
    top_workspace: str | None
    top_session_id: str | None


def _num(value: object) -> float | None:
    """A finite number from a JSON value, else None (bool is NOT a number here —
    a stray ``true`` must never read as 1.0)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f and f not in (float("inf"), float("-inf")) else None  # f==f rejects NaN
    return None


def parse_burn_status(data: object) -> BurnStatus | None:
    """Extract the trusted ``BurnStatus`` slice from a ``get_burn_status`` payload.

    Pure. Returns None on a non-dict; otherwise best-effort per field (a missing
    or malformed field is None, never a raise) so a partial/renamed payload
    degrades to "less info", not a crash. Requires at least a cost_per_hour OR a
    top session to be worth returning — an empty shell is None so the caller
    falls back cleanly.
    """
    if not isinstance(data, dict):
        return None
    glob = data.get("global")
    cost = _num(glob.get("costPerHour")) if isinstance(glob, dict) else None
    active = _num(data.get("activeSessions"))
    top_ws: str | None = None
    top_id: str | None = None
    tops = data.get("topSessions")
    if isinstance(tops, list) and tops and isinstance(tops[0], dict):
        ws = tops[0].get("workspace")
        sid = tops[0].get("sessionId")
        top_ws = ws if isinstance(ws, str) and ws else None
        top_id = sid if isinstance(sid, str) and sid else None
    if cost is None and top_ws is None and top_id is None:
        return None
    return BurnStatus(
        cost_per_hour=cost,
        active_sessions=int(active) if active is not None else None,
        top_workspace=top_ws,
        top_session_id=top_id,
    )


@dataclass(frozen=True)
class BurnCause:
    """The top culprit from ``investigate_burn`` — for one enrichment clause.

    ``cause`` — the classifier verdict (e.g. ``FORK_STORM``). ``share`` — its
    fraction of the window [0,1] or None. ``confidence`` — ``high``/``medium``/…
    or None. ``workspace`` — set ONLY when the finding itself names exactly one
    location; ``multi_workspace`` marks a finding that spans several, which is a
    fact worth reporting rather than a detail to collapse.
    """

    cause: str
    share: float | None
    confidence: str | None
    workspace: str | None
    multi_workspace: bool = False


def _is_workspace_path(value: object) -> bool:
    """True iff ``value`` is a real workspace, i.e. a filesystem path.

    agentlensPro puts NON-locations in the same slots and they must never be
    rendered as one: a truncation marker (``… +2 more — use verbosity:"full"``)
    and unattributable sentinels such as ``(subagent/no-env-block)``. A workspace
    is always a path, so requiring a leading ``/`` or ``~`` rejects both with one
    rule — and it is the sentinel, printed verbatim as a location, that a reader
    reasonably mistakes for an identified culprit.
    """
    return isinstance(value, str) and value.startswith(("/", "~"))


def parse_investigate_cause(data: object) -> BurnCause | None:
    """Extract the single top culprit from an ``investigate_burn`` payload. Pure.

    None unless there is at least one ``findings`` entry with a non-empty
    ``cause`` — no finding means no attribution to add, and the caller's line is
    still worth emitting without it.

    The location comes from the FINDING'S OWN ``evidence.workspaces`` and from
    nowhere else. It used to be taken from ``attribution[0]``, which is a
    SEPARATELY-ranked list: splicing the two produced a "<cause> in <workspace>"
    claim that neither list makes, and a live payload shows exactly how wrong that
    gets — a ``FORK_STORM`` spanning five workspaces was reported as happening in
    the one workspace that happened to top the unrelated attribution ranking.
    A consumer acted on such a line, throttling off agent launches and deferring
    authorized work (janitor#121), so a confident wrong cause is more costly here
    than no cause at all: when the finding does not name exactly one location, we
    say it spans several and name none.
    """
    if not isinstance(data, dict):
        return None
    findings = data.get("findings")
    if not (isinstance(findings, list) and findings and isinstance(findings[0], dict)):
        return None
    top = findings[0]
    cause = top.get("cause")
    if not (isinstance(cause, str) and cause.strip()):
        return None
    share = _num(top.get("shareOfWindow"))
    conf = top.get("confidence")

    evidence = top.get("evidence")
    listed = evidence.get("workspaces") if isinstance(evidence, dict) else None
    listed = listed if isinstance(listed, list) else []
    real = [w for w in listed if _is_workspace_path(w)]
    # A non-path entry alongside real paths is the "+N more" marker, so the true
    # count exceeds what we can see — still "several", just not a countable one.
    truncated = len(real) != len(listed)
    single = len(real) == 1 and not truncated
    # With NO real path we know nothing: the entries are unattributable sentinels
    # like `(subagent/no-env-block)`, which assert the opposite of a location.
    # Reporting that as "several workspaces" would invent breadth from ignorance,
    # which is the same error as inventing a single culprit — so stay silent.
    multi = len(real) > 1 or (len(real) == 1 and truncated)

    return BurnCause(
        cause=cause.strip(),
        share=share if share is not None and 0.0 <= share <= 1.0 else None,
        confidence=conf.strip() if isinstance(conf, str) and conf.strip() else None,
        workspace=real[0] if single else None,
        multi_workspace=multi,
    )


def format_cause_clause(cause: BurnCause) -> str:
    """Render a ``BurnCause`` as a compact, greppable one-line suffix (leading space).

    Pure. Example: `` agentlensPro: FORK_STORM (18% of window, high) in ~/Code/x``.
    Untrusted-safe: the workspace/cause come from the CLI, but no user-controlled
    interpolation slot is opened — the fields are placed positionally into a fixed
    template, and the caller sanitizes before printing to a drift line.

    A multi-workspace finding says so rather than naming one of them: the reader's
    next action is "go look at X", so an invented X sends them to the wrong place.
    """
    parts: list[str] = [cause.cause]
    detail: list[str] = []
    if cause.share is not None:
        detail.append(f"{cause.share * 100:.0f}% of window")
    if cause.confidence:
        detail.append(cause.confidence)
    if detail:
        parts.append(f"({', '.join(detail)})")
    if cause.workspace:
        tail = f" in {cause.workspace}"
    elif cause.multi_workspace:
        tail = " spanning several workspaces"
    else:
        tail = ""
    return f" agentlensPro cause: {' '.join(parts)}{tail}."
